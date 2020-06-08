import PyPDF2
import PyPDF2.utils
import imghdr
import re
from datetime import date
from flask import g, session, json
from flask_login import current_user
from flask_wtf import Form
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import StringField, PasswordField, TextAreaField, FloatField, BooleanField, IntegerField, SelectField, \
    HiddenField
from wtforms.fields.html5 import DateField
from wtforms.fields import Field
from wtforms.widgets import TextInput
from wtforms.validators import DataRequired, Length, Regexp, EqualTo, NumberRange, ValidationError, URL, Optional, \
    Email, StopValidation

from app import app
from app.helpers import APIError
from app.models import Category, User, Variable, Product, UserVerificationPhoto
from app.utils import tz
from app.utils.country import COUNTRY_CHOICES


class JSONField(Field):
    widget = TextInput()

    def _value(self):
        if self.data:
            return json.dumps(self.data)
        else:
            return u''

    def process_formdata(self, valuelist):
        if type(valuelist) in (list, dict):
            self.data = valuelist
        else:
            self.data = None


class EmptyForm(Form):
    pass


class PasswordChangeForm(Form):
    old_password = PasswordField('Old password', validators=[DataRequired()])

    password = PasswordField('New password', validators=[
        DataRequired(),
        EqualTo('password2', message='Passwords must match.')])
    password2 = PasswordField('Confirm password', validators=[DataRequired()])

    def validate_old_password(self, field):
        if not g.user.verify_password(field.data):
            raise ValidationError('The old password is wrong')


class DeleteAccountForm(Form):
    password = PasswordField('Password', validators=[DataRequired()])

    captcha = StringField('Captcha')

    def validate_password(self, field):
        if not g.user.verify_password(field.data):
            raise ValidationError('The password is wrong')

    def validate_captcha(self, field):
        if field.data != session['captcha']:
            raise ValidationError('Wrong captcha value')


class ProfilePhotoForm(Form):
    photo = FileField('Photo', validators=[FileAllowed(app.config.get('ALLOWED_PHOTO_EXTENSIONS'))])


class ProfileForm(Form):
    profile_description = TextAreaField('Public profile')
    #privacy_policy = TextAreaField('Privacy policy')
    #private_description = TextAreaField('Private description (visible by administrator)')


class WithdrawBTCAPIForm(Form):
    address = StringField('Your bitcoin address', validators=[
        DataRequired(),
        Regexp(r'^[13][a-km-zA-HJ-NP-Z0-9]{26,33}$', 0, 'Invalid bitcoin address')
    ])

    amount = FloatField('Amount', validators=[
        DataRequired(),
        NumberRange(0, 10)
    ])

    def validate_amount(self, field):
        rate = Variable.get_exchange_rate()
        if not rate:
            raise ValidationError('Exchange rate is not available')

        amount = int(rate * field.data * 100)

        if g.user.credit < (amount + app.config['MIN_BALANCE']):
            raise ValidationError('You requested too much. Minimal balance you need to keep on the site is %.2f USD' % (app.config['MIN_BALANCE'] / 100.0))

        if field.data < app.config['WITHDRAWAL_THRESHOLD_BTC']:
            raise ValidationError('Minimal withdrawal amount is %.2f BTC' % app.config['WITHDRAWAL_THRESHOLD_BTC'])


class BaseWithdrawAPIForm(Form):
    address = StringField('E-mail', validators=[DataRequired(), Email()])
    amount = FloatField('Amount')

    def validate_amount(self, field):
        amount = int(field.data * 100)

        if g.user.credit < (amount + app.config['MIN_BALANCE']):
            raise ValidationError('You requested too much. Minimal balance you need to keep on the site is %.2f USD' % (app.config['MIN_BALANCE'] / 100.0))


class WithdrawPayPalAPIForm(BaseWithdrawAPIForm):
    def validate_amount(self, field):
        super(WithdrawPayPalAPIForm, self).validate_amount(field)
        amount = int(field.data * 100)
        if not (app.config.get('WITHDRAWAL_RANGE_PAYPAL')[0] <= amount <= app.config.get('WITHDRAWAL_RANGE_PAYPAL')[1]):
            raise ValidationError('Minimal withdrawal amount is %.2f USD. Maximum withdrawal amount is %.2f USD' % (app.config.get('WITHDRAWAL_RANGE_PAYPAL')[0] / 100.0, app.config.get('WITHDRAWAL_RANGE_PAYPAL')[1] / 100.0))


class WithdrawPayZaAPIForm(BaseWithdrawAPIForm):
    def validate_amount(self, field):
        amount = int(field.data * 100)
        if not (app.config.get('WITHDRAWAL_RANGE_PAYZA')[0] <= amount <= app.config.get('WITHDRAWAL_RANGE_PAYZA')[1]):
            raise ValidationError('Minimal withdrawal amount is %.2f USD. Maximum withdrawal amount is %.2f USD' % (app.config.get('WITHDRAWAL_RANGE_PAYZA')[0] / 100.0, app.config.get('WITHDRAWAL_RANGE_PAYZA')[1] / 100.0))


class WithdrawPayoneerAPIForm(BaseWithdrawAPIForm):
    def validate_amount(self, field):
        amount = int(field.data * 100)
        if not (app.config.get('WITHDRAWAL_RANGE_PAYONEER')[0] <= amount <= app.config.get('WITHDRAWAL_RANGE_PAYONEER')[1]):
            raise ValidationError('Minimal withdrawal amount is %.2f USD. Maximum withdrawal amount is %.2f USD' % (app.config.get('WITHDRAWAL_RANGE_PAYONEER')[0] / 100.0, app.config.get('WITHDRAWAL_RANGE_PAYONEER')[1] / 100.0))


class WithdrawSkrillAPIForm(BaseWithdrawAPIForm):
    def validate_amount(self, field):
        amount = int(field.data * 100)
        if not (app.config.get('WITHDRAWAL_RANGE_SKRILL')[0] <= amount <= app.config.get('WITHDRAWAL_RANGE_SKRILL')[1]):
            raise ValidationError('Minimal withdrawal amount is %.2f USD. Maximum withdrawal amount is %.2f USD' % (app.config.get('WITHDRAWAL_RANGE_SKRILL')[0] / 100.0, app.config.get('WITHDRAWAL_RANGE_SKRILL')[1] / 100.0))


class DepositCardAPIForm(Form):
    stripeSource = StringField('Stripe Source')
    existing = BooleanField('Existing Stripe Source?')
    remember = BooleanField('Remember')

    amount = FloatField('Amount')


class WithdrawWUForm(Form):
    first_name = StringField('First name', validators=[DataRequired()])
    middle_name = StringField('Middle name (optional)', validators=[])
    last_name = StringField('Last name', validators=[DataRequired()])
    country = StringField('Country', validators=[DataRequired()])
    city = StringField('City', validators=[DataRequired()])

    amount = FloatField('Amount')

    def validate_amount(self, field):
        amount = int(field.data * 100)

        if g.user.credit < (amount + app.config['MIN_BALANCE']):
            raise ValidationError('You requested too much. Minimal balance you need to keep on the site is %.2f USD' % (app.config['MIN_BALANCE'] / 100.0))

        if not (app.config.get('WITHDRAWAL_RANGE_WU')[0] <= amount <= app.config.get('WITHDRAWAL_RANGE_WU')[1]):
            raise ValidationError('Minimal withdrawal amount is %.2f USD. Maximum withdrawal amount is %.2f USD' % (app.config.get('WITHDRAWAL_RANGE_WU')[0] / 100.0, app.config.get('WITHDRAWAL_RANGE_WU')[1] / 100.0))


class TransferFundsForm(Form):
    recipient = StringField('Recipient username', validators=[DataRequired()])

    amount = FloatField('Amount (USD)', validators=[
        DataRequired(),
        NumberRange(0, 10)
    ])

    note = StringField('Note')

    def validate_recipient(self, field):
        if field.data == g.user.username:
            raise ValidationError('You can\'t transfer funds to yourself')

        recipient = User.query.filter_by(username=field.data).first()
        if not recipient:
            raise ValidationError('No such user')
        if recipient.is_deleted:
            raise ValidationError('User is currently inactive')

    def validate_amount(self, field):
        amount = int(field.data * 100)
        if g.user.credit < (amount + app.config['MIN_BALANCE']):
            raise ValidationError('You requested too much. Minimal balance you need to keep on the site is %.2f USD' % (app.config['MIN_BALANCE'] / 100.0))

        if amount < app.config['TRANSFER_THRESHOLD']:
            raise ValidationError('Minimal transfer amount is %.2f USD' % (app.config['TRANSFER_THRESHOLD'] / 100.0))


class NewOrderForm(Form):
    # This is actually JSON string
    extras = HiddenField()
    additional_files = HiddenField()

    additional_info = HiddenField()


class AbstractProductForm(Form):
    title = StringField('Title', validators=[DataRequired(), Length(15, 80)])
    is_private = BooleanField('Private product', default=False)
    category_id = IntegerField('Category', validators=[DataRequired()])

    description = TextAreaField('Description', validators=[DataRequired()])
    price = FloatField('Price (USD)', validators=[DataRequired(), NumberRange(1)])

    is_quantity_limited = BooleanField('Product quantity is limited', default=False)
    quantity = IntegerField('Quantity', default=0)

    additional_info_message = TextAreaField('Additional info needed from customer for doing this service')

    delivery_time = IntegerField('Delivery time (days)', validators=[NumberRange(1, 60)])
    revision_count = IntegerField('Revision count', validators=[NumberRange(-1, 1000)])

    youtube_href = StringField('Link to the YouTube video', validators=[Optional(), URL()])

    # This is actually JSON string
    extras = HiddenField(default='[]')

    # This is actually JSON string
    faq = HiddenField(default='[]')

    # This is actually JSON string
    tags = HiddenField(default='[]')

    def validate_category_id(self, field):
        if not Category.query.get(field.data):
            raise ValidationError('No category specified')

        # TODO: optimize
        # if len(field.data.read()) > app.config.get('MAX_ATTACHMENT_SIZE'):
        #     raise ValidationError('File too large')


class ShipProductForm(Form):
    private_description = TextAreaField('Private message to the buyer', validators=[DataRequired()])
    private_attachment = FileField('Private attachment', validators=[DataRequired(), FileAllowed(app.config.get('ALLOWED_ATTACHMENT_EXTENSIONS'))])


class NewProductForm(AbstractProductForm):
    photo = FileField('Photo', validators=[FileRequired('At least the first photo is required'), FileAllowed(app.config.get('ALLOWED_PHOTO_EXTENSIONS'))])
    photo2 = FileField('Photo', validators=[FileAllowed(app.config.get('ALLOWED_PHOTO_EXTENSIONS'))])
    photo3 = FileField('Photo', validators=[FileAllowed(app.config.get('ALLOWED_PHOTO_EXTENSIONS'))])
    photo4 = FileField('Photo', validators=[FileAllowed(app.config.get('ALLOWED_PHOTO_EXTENSIONS'))])


# class EditProductForm(AbstractProductForm):
#     pass


class EditProductForm(Form):
    title = StringField('Title', validators=[DataRequired(), Length(15, 80)])
    is_private = BooleanField('Private product', default=True)
    category_id = IntegerField('Category', validators=[DataRequired()])

    description = TextAreaField('Description', validators=[DataRequired()])
    price = FloatField('Price (USD)', validators=[DataRequired(), NumberRange(1)])

    additional_info_message = TextAreaField('Additional info needed from customer for doing this service')

    is_quantity_limited = BooleanField('Product quantity is limited', default=False)
    quantity = IntegerField('Quantity', default=0)

    delivery_time = IntegerField('Delivery time (days)', validators=[NumberRange(1, 60)])
    revision_count = IntegerField('Revision count', validators=[NumberRange(-1, 1000)])

    youtube_href = StringField('Link to the YouTube video', validators=[Optional(), URL()])

    # This is actually JSON string
    extras = HiddenField(default='[]')

    # This is actually JSON string
    faq = HiddenField(default='[]')

    # This is actually JSON string
    tags = HiddenField(default='[]')

    def validate_category_id(self, field):
        if not Category.query.get(field.data):
            raise ValidationError('No category specified')

        # TODO: optimize
        # if len(field.data.read()) > app.config.get('MAX_ATTACHMENT_SIZE'):
        #     raise ValidationError('File too large')


class NewProductPhotoForm(Form):
    photo = FileField('Add photo', validators=[FileRequired(), FileAllowed(app.config.get('ALLOWED_PHOTO_EXTENSIONS'))])


class ReportAbuseForm(Form):
    text = TextAreaField('Text of the message', validators=[DataRequired()])
    email = StringField('Your email')

    def validate_email(self, field):
        if g.user.is_authenticated:
            return

        validator = Email()
        validator(self, field)


class TwoFactorAuthForm(Form):
    enabled = SelectField('2-FA enabled', choices=[(0, 'No'), (1, 'Yes')], coerce=int)


class NewsletterForm(Form):
    subject = StringField('Email Subject:', validators=[DataRequired()])
    text = TextAreaField('Message:', validators=[DataRequired()])


class EmailSettingsForm(Form):
    is_newsletter_enabled = BooleanField('Newsletter', default=False)
    is_sales_report_enabled = BooleanField('Sales Report', default=False)
    is_marketplace_digest_enabled = BooleanField('Marketplace Digest', default=False)


class VoucherActivateForm(Form):
    code = StringField('Voucher code:', validators=[DataRequired(), Length(15, 15)])


class NewOfferForm(Form):
    product_id = IntegerField('Product', validators=[DataRequired()])

    value = FloatField('Value', validators=[
        DataRequired(),
        NumberRange(0)
    ])

    type = SelectField('Type', validators=[DataRequired()], choices=(('relative', '%'), ('absolute', 'USD')))

    start_date = DateField('Start date', validators=[DataRequired()])
    end_date = DateField('End date', validators=[DataRequired(), ])

    def validate_product_id(self, field):
        product = Product.query.get(field.data)
        if not product or product.seller_id != g.user.id:
            raise ValidationError('No product specified')

    def validate_value(self, field):
        if self.type.data == 'relative' and (field.data >= 100 or field.data < 1):
            raise ValidationError('Please specify correct number of percents')

    def validate_end_date(self, field):
        delta = field.data - self.start_date.data
        if delta.days < 0:
            raise ValidationError('End date should be greater start date')

        delta = field.data - date.today()
        if delta.days < 0:
            raise ValidationError('End date should be at least today')


class NewDiscountForm(Form):
    product_id = IntegerField('Product', validators=[DataRequired()])

    value = FloatField('Value', validators=[
        DataRequired(),
        NumberRange(0)
    ])

    type = SelectField('Type', validators=[DataRequired()], choices=(('relative', '%'), ('absolute', 'USD')))

    def validate_product_id(self, field):
        product = Product.query.get(field.data)
        if not product or product.seller_id != g.user.id:
            raise ValidationError('No product specified')

    def validate_value(self, field):
        if self.type.data == 'relative' and (field.data >= 100 or field.data < 1):
            raise ValidationError('Please specify correct number of percents')


class NewInviteForm(Form):
    type = SelectField('Freebie', validators=[DataRequired()], choices=(('seller', 'Free seller'),))


# API FORMS


class ServiceCreateAPIForm(Form):
    title = StringField('Title', validators=[DataRequired(), Length(15, 80)])
    category_id = IntegerField('Category', validators=[DataRequired()])
    is_private = BooleanField('Private', validators=[DataRequired()])

    description = TextAreaField('Description', validators=[DataRequired(), Length(min=120)])

    # The following are JSON objects
    faqs = JSONField()
    tags = JSONField()
    requirements = JSONField()
    extras = JSONField()

    def validate_category_id(self, field):
        if not field.data:
            raise ValidationError('Category is required')

        category = Category.query.get(field.data)
        if not category or category.parent_id is None:
            raise ValidationError('Wrong category specified')

    def validate_faqs(self, field):
        if not field.data:
            return

        try:
            if type(field.data) is not list:
                raise


            for item in field.data:
                if (set(item) != set(('a', 'q',))):
                    raise
        except:
            raise ValidationError('Wrong FAQ format')

    def validate_tags(self, field):
        if not field.data:
            raise ValidationError('Min. 1 tag is required')

        try:
            if type(field.data) is not list:
                raise

            if len(field.data) > 5:
                raise ValidationError('Max. 5 tags are allowed')

            for item in field.data:
                if type(item) not in (str, unicode):
                    raise

        except:
            raise ValidationError('Wrong tags format')

    def validate_requirements(self, field):
        if not field.data:
            return

        try:
            if type(field.data) is not list:
                raise


            for item in field.data:
                if (set(item) != set(('type', 'text', 'required', 'id',))):
                    raise
        except:
            raise ValidationError('Wrong requirements format')

    def validate_extras(self, field):
        if not field.data:
            return

        try:
            if type(field.data) is not list:
                raise


            for item in field.data:
                if (set(item) != set(('text', 'description', 'type', 'price', 'id',))):
                    raise

                if type(item['price']) is not int or item['price'] < 0:
                    raise
        except:
            raise ValidationError('Wrong extras format')


class ServiceUpdateAPIForm(ServiceCreateAPIForm):
    price = FloatField('Price (USD)', validators=[DataRequired()])
    delivery_time = IntegerField('Delivery time (days)', validators=[NumberRange(1, 60)])
    revision_count = IntegerField('Revision count', validators=[NumberRange(-1, 1000)])

    def validate_price(self, field):
        price_range = app.config['SERVICE_PRICE_RANGE']

        if field.data < price_range[0]:
            raise ValidationError('Minimum allowed price is {0:.2f} USD'.format(price_range[0] / 100))

        if field.data > price_range[1]:
            raise ValidationError('Maximum allowed price is {0:.2f} USD'.format(price_range[1] / 100))


class ProfileUpdateAPIForm(Form):
    profile_description = TextAreaField('Public profile')
    profile_headline = TextAreaField('Headline', validators=[Length(0, 100)])


class SettingsUpdateAPIForm(Form):
    tz = StringField('Timezone')
    profile_first_name = StringField('First Name')
    profile_last_name = StringField('Last Name')
    is_affiliate_panel_enabled = IntegerField('Show Affiliate Program', validators=[NumberRange(0, 1)])

    def validate_tz(self, field):
        if field.data not in tz.get_names_list():
            raise ValidationError('Unknown timezone')


class ProfilePhotoAPIForm(Form):
    photo = FileField('Photo', validators=[DataRequired(), FileAllowed(app.config.get('ALLOWED_PHOTO_EXTENSIONS'))])


class ProfileCoverAPIForm(Form):
    cover = FileField('Cover', validators=[DataRequired(), FileAllowed(app.config.get('ALLOWED_PHOTO_EXTENSIONS'))])


class PasswordChangeAPIForm(Form):
    old_password = PasswordField('Old password')

    password = PasswordField('New password', validators=[
        DataRequired(),
        EqualTo('password2', message='Passwords must match')])
    password2 = PasswordField('Confirm password', validators=[DataRequired()])

    def validate_old_password(self, field):
        if not g.user.password_hash:
            # Do not verify empty password
            return

        if not g.user.verify_password(field.data):
            raise ValidationError('The old password is wrong')


class PhoneNumberVerifyAPIForm(Form):
    phone_number = StringField('Phone number', validators=[DataRequired()])

    code = StringField('Security code')

    def validate_phone_number(self, field):
        if not re.match(r'^\+[0-9]{7,}$', field.data):
            raise ValidationError('Wrong phone number format')

    def validate_code(self, field):
        if field.data and not (field.data.isdigit() and len(field.data) == 6):
            raise ValidationError('Wrong security code')


class TransferFundsAPIForm(Form):
    recipient = StringField('Username', validators=[DataRequired()])

    amount = FloatField('Amount (USD)', validators=[DataRequired()])

    note = StringField('Note')

    def validate_recipient(self, field):
        if field.data == g.user.username:
            raise ValidationError('You are not allowed to transfer funds to yourself')

        recipient = User.query.filter(User.username==field.data, User.is_deleted!=True).first()

        if not recipient:
            raise ValidationError('User with such username doesn\'t exist')

        if recipient.is_disabled:
            raise ValidationError('User has been disabled')

    def validate_amount(self, field):
        amount = int(field.data * 100)

        if amount <= 0:
            raise ValidationError('Please enter positive amount')

        if g.user.credit < (amount + app.config['MIN_BALANCE']):
            raise ValidationError('You requested too much. Minimal balance you need to keep on the site is %.2f USD' % (app.config['MIN_BALANCE'] / 100.0))

        if amount < app.config['TRANSFER_THRESHOLD']:
            raise ValidationError('Minimal transfer amount is %.2f USD' % (app.config['TRANSFER_THRESHOLD'] / 100.0))


class NewDiscountAPIForm(Form):
    product_id = StringField('Product', validators=[DataRequired()])

    value = FloatField('Value', validators=[
        DataRequired(),
        NumberRange(0)
    ])

    type = SelectField('Type', validators=[DataRequired()], choices=(('relative', '%'), ('absolute', 'USD')))

    def validate_product_id(self, field):
        product = Product.get_by_custom_id(field.data)
        if not product or product.seller_id != g.user.id:
            raise ValidationError('No product specified')

    def validate_value(self, field):
        if self.type.data == 'relative' and (field.data >= 100 or field.data < 1):
            raise ValidationError('Please specify correct number of percents')


class EditOfferAPIForm(Form):
    value = FloatField('Value', validators=[
        DataRequired(),
        NumberRange(0)
    ])

    type = SelectField('Type', validators=[DataRequired()], choices=(('relative', '%'), ('absolute', 'USD')))

    start_date = DateField('Start date', validators=[DataRequired()], format='%d-%m-%Y')
    end_date = DateField('End date', validators=[DataRequired(), ], format='%d-%m-%Y')

    def validate_value(self, field):
        if self.type.data == 'relative' and (field.data >= 100 or field.data < 1):
            raise ValidationError('Please specify correct number of percents')

    def validate_end_date(self, field):
        delta = field.data - self.start_date.data
        if delta.days < 0:
            raise ValidationError('End date should be greater start date')

        delta = field.data - date.today()
        if delta.days < 0:
            raise ValidationError('End date should be at least today')


class NewOfferAPIForm(EditOfferAPIForm):
    product_id = StringField('Product', validators=[DataRequired()])

    def validate_product_id(self, field):
        product = Product.get_by_custom_id(field.data)
        if not product or product.seller_id != g.user.id:
            raise ValidationError('No product specified')


class FeedbackAPIForm(Form):
    text = StringField('Text', validators=[Length(max=500)])

    rating = IntegerField('Rating', validators=[
        NumberRange(-1, 1)
    ])


class RevisionAPIForm(Form):
    description = TextAreaField('Description', validators=[DataRequired(), Length(min=5)])
    files = JSONField()


class DisputeAPIForm(Form):
    kind = StringField('Kind', validators=[DataRequired()])
    resolution_kind = StringField('Kind', validators=[DataRequired()])
    text = StringField('Text', validators=[DataRequired(), Length(max=1000)])


class DeliverAPIForm(Form):
    text = StringField('Text', validators=[DataRequired(), Length(max=1000)])
    files = JSONField()

    def validate_files(self, field):
        if not field.data:
            return

        try:
            if type(field.data) is not list:
                raise

            for item in field.data:
                if (set(item) != set(('filename', 'attachmentId', 'size',))):
                    raise
        except:
            raise ValidationError('Wrong files format')


class CustomOfferAPIForm(Form):
    message = StringField('Message', validators=[DataRequired(), Length(max=500)])
    message_attachments = JSONField()
    custom_extras = JSONField()
    extras = JSONField()
    delivery_time = IntegerField('Delivery time (days)', validators=[NumberRange(1, 60)])

    def validate_extras(self, field):
        if not field.data:
            return

        if type(field.data) is not list:
            raise ValidationError('Wrong extras format')

    def validate_custom_extras(self, field):
        if not field.data:
            return

        try:
            if type(field.data) is not list:
                raise

            for item in field.data:
                if set(item) != set(('text', 'price',)):
                    raise

                if type(item['price']) is not int or item['price'] <= 0:
                    raise
        except:
            raise ValidationError('Wrong custom extra format')

    def validate_message_attachments(self, field):
        if not field.data:
            return

        try:
            if type(field.data) is not list:
                raise

            for item in field.data:
                if set(item) != set(('filename', 'attachmentId', 'size',)):
                    raise
        except:
            raise ValidationError('Wrong attachments format')


class ServiceOfferAPIForm(Form):
    message = StringField('Message', validators=[Length(max=500)])
    price = FloatField('Price (USD)', validators=[DataRequired(), NumberRange(1)])
    delivery_time = IntegerField('Delivery time (days)', validators=[NumberRange(1, 60)])
    revision_count = IntegerField('Revision count', validators=[NumberRange(-1, 1000)])
    expiration_time = IntegerField('Expiration time (days)')
    service_id = StringField('Service ID', validators=[DataRequired()])
    enquiry_id = IntegerField('Enquiry ID', validators=[DataRequired()])

    def validate_price(self, field):
        price_range = app.config['SERVICE_PRICE_RANGE']

        if field.data < price_range[0]:
            raise ValidationError('Minimum allowed price is {0:.2f} USD'.format(price_range[0] / 100))

        if field.data > price_range[1]:
            raise ValidationError('Maximum allowed price is {0:.2f} USD'.format(price_range[1] / 100))


class InviteAPIForm(Form):
    email = StringField('E-mail', validators=[DataRequired(), Email()])


class SkillAPIForm(Form):
    skill_name = StringField('Skill name', validators=[DataRequired()])


class LanguageAPIForm(Form):
    LEVELS = [
        (0, 'Basic'),
        (1, 'Conversational'),
        (2, 'Fluent'),
        (3, 'Native or Bilingual')
    ]
    language_name = StringField('Language name', validators=[DataRequired()])
    language_level = SelectField('Language level', choices=LEVELS, coerce=int)


class EndorseAPIForm(Form):
    text = StringField('Text', validators=[DataRequired()])
    email = StringField('E-mail', validators=[DataRequired(), Email()])


class ImageValidator(object):
    def __init__(self, message=None):
        if not message:
            message = u'You must choose a valid image file.'
        self.message = message

    def __call__(self, form, field):
        if field.has_file():
            if imghdr.what('unused', field.data.read()) is None:
                raise StopValidation(self.message)
            field.data.seek(0)


class PdfImageValidator(object):
    def __init__(self, message=None):
        if not message:
            message = u'You must choose a valid pdf or image file.'
        self.message = message

    def __call__(self, form, field):
        if field.has_file():
            if imghdr.what('unused', field.data.read()) is None:
                field.data.seek(0)
                # image validation fails
                try:  # do pdf validation
                    PyPDF2.PdfFileReader(field.data)
                except PyPDF2.utils.PdfReadError:
                    raise StopValidation(self.message)
            field.data.seek(0)


class FileSizeValidator(object):
    def __init__(self, min, max, min_msg=None, max_msg=None):
        if not min_msg:
            self.min_msg = u'File size is too small.'
        if not max_msg:
            self.max_msg = u'File size is too big.'
        self.max_msg = max_msg
        self.min_msg = min_msg
        self.min = min
        self.max = max

    def __call__(self, form, field):
        if field.has_file():
            size_bytes = len(field.data.read())
            field.data.seek(0)
            if self.min and self.min > size_bytes:
                raise StopValidation(self.min_msg)
            if self.max and size_bytes > self.max:
                raise StopValidation(self.max_msg)


class ValidateOrRaise(object):
    def validate_or_raise(self, message='Please make sure you have specified all the fields properly'):
        if not self.validate():
            raise APIError(message, payload=dict(fields=self.errors))


class ValidateImageForm(Form, ValidateOrRaise):
    photo = FileField('Photo', validators=(DataRequired(), FileAllowed(app.config.get('ALLOWED_DOCUMENT_EXTENSIONS')),
                                           FileSizeValidator(1, 1024 * 1024 * 10), PdfImageValidator(), ))
    step = IntegerField('Step', validators=(DataRequired(), NumberRange(1, 3)))


class VerifyCountrySelector(Form, ValidateOrRaise):
    country_code = SelectField("Country", choices=COUNTRY_CHOICES, validators=(DataRequired(),))


class VerifyIDForm(Form, ValidateOrRaise):
    first_name = StringField("First Name", validators=(DataRequired(),))
    last_name = StringField("Last Name", validators=(DataRequired(),))
    birthdate = DateField("Date of Birth", validators=(DataRequired(),))
    id_issuing_country = SelectField("ID Issuing Country", choices=COUNTRY_CHOICES, validators=(DataRequired(),))
    id_type = StringField("ID Type", validators=(DataRequired(),))
    id_number = StringField("ID Number", validators=(DataRequired(),))
    id_expire_date = DateField("ID Expires on", validators=(DataRequired(),))

    uploads = StringField('Dummy Field for file uploads')

    def validate_uploads(self, field):
        total = UserVerificationPhoto.query.filter(
            UserVerificationPhoto.user_id == current_user.id,
            UserVerificationPhoto.step == 1, UserVerificationPhoto.hidden == False).count()
        if not total:
            raise ValidationError('Must upload at least 1 document')


class VerifyKeycodeForm(Form, ValidateOrRaise):

    uploads = StringField('Dummy Field for file uploads')

    def validate_uploads(self, field):
        total = UserVerificationPhoto.query.filter(
            UserVerificationPhoto.user_id == current_user.id,
            UserVerificationPhoto.step == 2, UserVerificationPhoto.hidden == False).count()
        if not total:
            raise ValidationError('Must upload at least 1 document')


class VerifyAddressForm(Form, ValidateOrRaise):
    address_line_1 = StringField("Address Line 1", validators=(DataRequired(), Length(max=256)))
    address_line_2 = StringField("Address Line 2", validators=(Length(max=256),))

    city = StringField("City", validators=(DataRequired(), Length(max=128)))
    country_state = StringField("State", validators=(DataRequired(), Length(max=128)))
    postal_code = StringField("Postal Code", validators=(DataRequired(), Length(max=128)))

    institution_name = StringField("Institution Name", validators=(DataRequired(), Length(max=128)))
    document_type = StringField("Document Type", validators=(DataRequired(), Length(max=256)))
    document_date_issued = DateField("Document Date Issued", validators=(DataRequired(),))

    uploads = StringField('Dummy Field for file uploads')

    def validate_uploads(self, field):
        total = UserVerificationPhoto.query.filter(
            UserVerificationPhoto.user_id == current_user.id,
            UserVerificationPhoto.step == 3, UserVerificationPhoto.hidden == False).count()
        if not total:
            raise ValidationError('Must upload at least 1 document')
