from flask_wtf import Form
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import StringField, FloatField, TextAreaField, BooleanField, PasswordField, IntegerField, SelectField
from wtforms.validators import DataRequired, Length, Email, NumberRange, ValidationError, EqualTo, URL

from app import app
from app.models import Category, AffiliateLink


class PasswordChangeForm(Form):
    password = PasswordField('New password', validators=[
        DataRequired(),
        EqualTo('password2', message='Passwords must match.')])
    password2 = PasswordField('Confirm password', validators=[DataRequired()])


class EmailChangeForm(Form):
    email = StringField('New e-mail', validators=[DataRequired(), Email()])


class DepositUserForm(Form):
    amount = FloatField('Amount (USD)', validators=[
        DataRequired(),
        NumberRange(0, 10000)
    ])


class NewsForm(Form):
    title = StringField('Title (optional)')
    text = TextAreaField('Text', validators=[DataRequired()])
    is_published = BooleanField('Published?', default=True)


class NewVoucherForm(Form):
    type = SelectField('Freebie', validators=[DataRequired()], choices=(('premium_member', 'Premium member'), ('seller', 'Free seller')))

    total_count = IntegerField('Max. voucher usage', default=1, validators=[
        DataRequired(),
        NumberRange(1)
    ])


class NewAffiliateLinkForm(Form):
    title = StringField('Title', validators=[DataRequired()])
    description = TextAreaField('Description')

    image = FileField('Image', validators=[FileRequired(), FileAllowed(app.config.get('ALLOWED_PHOTO_EXTENSIONS'))])

    url = StringField('Target URL', validators=[DataRequired(), URL()])
    unique_url_id = StringField('Unique URL ID', validators=[DataRequired()])

    def validate_unique_url_id(self, field):
        if AffiliateLink.query.filter_by(unique_url_id=field.data).first():
            raise ValidationError('Link with specified ID (%s) already exists' % field.data)


class ServiceUpdateAPIForm(Form):
    title = StringField('Title', validators=[DataRequired()])
    category_id = IntegerField('Category')
    description = TextAreaField('Description', validators=[DataRequired()])

    def validate_category_id(self, field):
        if not field.data:
            return

        category = Category.query.get(field.data)
        if not category or category.parent_id is None:
            raise ValidationError('Wrong category specified')
