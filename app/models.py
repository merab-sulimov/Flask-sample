import json
import string
import uuid
import random
import base64
from datetime import datetime, timedelta, date
from urllib import quote

from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import or_, not_, UniqueConstraint
from sqlalchemy.orm import validates
from sqlalchemy.sql import func, text
from sqlalchemy.sql.functions import coalesce
from sqlalchemy_utils.types.choice import ChoiceType
from sqlalchemy_utils.types.json import JSONType
from flask_login import UserMixin
from flask import url_for

from app import app, db, messaging, email, cache, statistic
from app.statistic import StatisticRecord
from app.utils import seofy_title, generate_password_rsa
from app.utils.country import COUNTRIES
from app.utils.storage import Storage
from app.utils import slack


def isoformat(dt):
    return dt.isoformat() + 'Z'


def isoparse(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%S.%fZ')


class User(db.Model, UserMixin):
    GENERATE_USERNAME_ATTEMPTS = 10
    REFERER_COOKIE = 'ruid'
    REFERER_COOKIE_MAXAGE = 3600 * 24 * 30 # 30 days

    INVITATION_COOKIE = 'inid'
    INVITATION_COOKIE_MAXAGE = None

    class RegisterTypes:
        DEFAULT = 0
        AUTOSIGNUP = 1
        FACEBOOK = 10
        GOOGLE = 11

    LEVELS = [
        ('new_seller', 'New Seller'),
        ('level_1', 'Level 1 Seller'),
        ('level_2', 'Level 2 Seller'),
        ('top_rated', 'Top Rated Seller')
    ]

    __tablename__ = 'users'

    id = db.Column('user_id', db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), index=True)  # TODO: make custom type for that?

    referer_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True)
    invite_referer_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True)

    username = db.Column(db.String(20), unique=True, index=True)
    password_hash = db.Column(db.String(128), nullable=True)

    # RSA-encrypted password and additionally BASE64-decoded
    password_rsa = db.Column(db.String(512))

    email = db.Column(db.String(100), unique=True, index=True, nullable=False)

    # Email verification code and the flag
    verification_code = db.Column(db.String(100))
    is_verified = db.Column(db.Boolean, default=False, nullable=False)

    # ISO country code. See app.utils.country
    country = db.Column(db.String(2))

    # Timezone
    tz = db.Column(db.String(50), default='UTC', nullable=False)

    # Credit in USD cents
    credit = db.Column(db.Integer(), default=0L, nullable=False)
    bonus_credit = db.Column(db.Integer(), default=0L, nullable=False)

    # Means that account has been deleted (not recoverable)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    # Disables user for some reason
    is_disabled = db.Column(db.Boolean, default=False)

    # Is this user the market admin
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    # JSON object containing profile photo keys and options
    photo_data = db.Column(db.Text, default=None, nullable=True)

    # JSON object containing profile cover keys and options
    cover_data = db.Column(db.Text, default=None, nullable=True)

    # JSON meta data
    meta_data = db.Column(db.Text, default=None, nullable=True)

    # Textual descriptions
    profile_first_name = db.Column(db.String(25))
    profile_last_name = db.Column(db.String(25))
    profile_headline = db.Column(db.String(100))
    profile_description = db.Column(db.Text)
    private_description = db.Column(db.Text)
    privacy_policy = db.Column(db.Text)

    # Hourly rate (in USD cents)
    profile_rate = db.Column(db.Integer())

    # Phone number
    phone_number = db.Column(db.String(20), unique=True, index=True)
    phone_number_verified = db.Column(db.Boolean, default=False, nullable=False)

    # Seller/Premium member flags
    seller_fee_paid = db.Column(db.Boolean, default=False)
    premium_member = db.Column(db.Boolean, default=False)

    # Various flags
    is_newsletter_enabled = db.Column(db.Boolean, default=False)
    is_sales_report_enabled = db.Column(db.Boolean, default=False)
    is_marketplace_digest_enabled = db.Column(db.Boolean, default=False)
    is_affiliate_panel_enabled = db.Column(db.Boolean, default=False)

    # Registered/Last logged in dates
    registered_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_logged_on = db.Column(db.DateTime, default=datetime.utcnow)

    # Registered/Last logged in IP addresses
    registered_ip = db.Column(db.String(46))
    last_logged_ip = db.Column(db.String(46))

    # Fake response time populated from periodic script
    fake_response_time = db.Column(db.Integer)

    products = db.relationship('Product', backref='seller', lazy='dynamic')
    orders = db.relationship('Order', backref='buyer', lazy='dynamic')
    transactions = db.relationship('Transaction', backref='user', lazy='dynamic')
    bitcoin_addresses = db.relationship('BitcoinAddress', backref='user', lazy='dynamic')
    user_invitations = db.relationship('UserInvitation', backref='user', lazy='dynamic', foreign_keys="UserInvitation.user_id")

    # Seller level
    level = db.Column(ChoiceType(LEVELS), default=u'new_seller')

    # User pre-compiled data
    rating = db.Column(db.Float(precision=1, asdecimal=True), default=0.0)
    half_five_achieve_on = db.Column(db.Date, nullable=True)
    complete_orders = db.Column(db.Integer, default=0)
    total_earns = db.Column(db.Integer, default=0)  # Price in USD cents

    @validates('rating', 'half_five_achieve_on', 'complete_orders', 'total_earns')
    def received_modification(self, key, value):
        if key == 'rating':
            if self.rating < 4.5:
                self.half_five_achieve_on = None
            elif self.rating >= 4.5 and self.half_five_achieve_on == None:
                self.half_five_achieve_on = date.today()

        if not self.half_five_achieve_on:
            # Set lower level if seller doesnt have 4.5 star
            self.level = u'new_seller'
        else:
            half_five_achieve_days = (date.today() - self.half_five_achieve_on).days
            account_registered_days = (date.today() - self.registered_on.date()).days
            if half_five_achieve_days >= 60 \
                    and self.complete_orders >= 10 \
                    and self.total_earns >= 40000 \
                    and account_registered_days >= 60:
                self.level = u'level_1'
            if half_five_achieve_days >= 60 \
                    and self.complete_orders >= 50 \
                    and self.total_earns >= 200000 \
                    and account_registered_days >= 120:
                self.level = u'level_2'
            if half_five_achieve_days >= 60 \
                    and self.complete_orders >= 100 \
                    and self.total_earns >= 2000000 \
                    and account_registered_days >= 180:
                self.level = u'top_rated'
        db.session.add(self)
        db.session.commit()
        return value

    @property
    def publish_limit(self):
        return app.config.get('LEVEL_PUBLISH_LIMIT').get(self.level)

    @property
    def can_publish_products(self):
        if self.products.count() >= self.publish_limit:
            return False
        return True

    @property
    def password(self):
        raise AttributeError('Password is not a readable attribute')

    @password.setter
    def password(self, password):
        if not password:
            return

        self.password_hash = generate_password_hash(password)
        self.password_rsa = generate_password_rsa(password)

    def verify_password(self, password):
        # Do not verify NULL passwords at all
        return (self.password_hash and check_password_hash(self.password_hash, password))

    # LoginManager-related methods

    def is_active(self):
        return not self.is_deleted

    def get_id(self):
        return unicode(self.id)

    # End of LoginManager-related methods

    @property
    def is_online(self):
        return (datetime.utcnow() - self.last_logged_on).total_seconds() < 15 * 60

    @property
    def profile_name(self):
        return ' '.join((
            self.profile_first_name.capitalize() if self.profile_first_name else '',
            ('%s.' % self.profile_last_name[:1].upper()) if self.profile_last_name else ''
        )).strip()

    @property
    def profile_display_name(self):
        if self.profile_first_name:
            # At least we have first name
            return self.profile_name
        else:
            return self.username

    @property
    def is_verification_completed(self):
        user_verification = UserVerification.query.get(self.id)
        return (user_verification and user_verification.state == UserVerification.COMPLETED)

    @property
    def is_verificated(self):
        # check if user needs to verify his documents
        user_verification = UserVerification.query.get(self.id)
        if user_verification and user_verification.state != UserVerification.DRAFT:
            return True

    @staticmethod
    def generate(email, verified=False, empty_password=False):
        """
        Generates username based on the first part of email --> [username]@example.com
        First tries "username" without any suffix, and if exists tries one-char suffix for 2 times
        Then tries two-char suffix for 2 times, and etc until User.GENERATE_USERNAME_ATTEMPTS is reached
        """
        generated = False

        for i in range(User.GENERATE_USERNAME_ATTEMPTS + 1):
            random_suffix = ''.join(random.choice(string.digits) for _ in range((i + 1) / 2)) if i > 0 else ''
            username = email[:email.index('@')][:20-len(random_suffix)] + random_suffix
            if User.query.filter_by(username=username).count() == 0:
                generated = True
                break

        if not generated:
            raise Exception('Cannot generate username after %d attempts' % User.GENERATE_USERNAME_ATTEMPTS)

        kwargs = dict(username=username, email=email)

        if verified:
            kwargs['is_verified'] = True

        if not empty_password:
            password = ''.join(random.choice(string.digits + string.ascii_letters) for _ in range(8))
            kwargs['password'] = password

        user = User(**kwargs)
        db.session.add(user)
        db.session.commit()

        return user, password if not empty_password else None

    @staticmethod
    def get_active_by_username(username):
        return User.query.filter(
            or_(User.is_deleted!=True, User.is_deleted==None),
            or_(User.is_disabled!=True, User.is_disabled==None),
            User.username==username
        ).first()

    @staticmethod
    def generate_token():
        return ''.join(random.choice(string.digits + string.ascii_letters) for _ in range(72))

    def request_verification(self):
        code = User.generate_token()
        self.verification_code = code
        self.is_verified = False
        db.session.add(self)
        db.session.commit()
        return code

    def get_social_account(self, provider):
        return UserSocialAccount.query.filter_by(provider=provider, user_id=self.id).first()

    def create_social_account(self, provider, provider_id):
        social_account = UserSocialAccount(provider=provider, provider_id=provider_id, user_id=self.id)
        db.session.add(social_account)
        db.session.commit()

        return social_account

    def get_country_pp(self, default='N/A'):
        if self.country:
            for country in COUNTRIES:
                if country[0] == self.country:
                    return country[1]

        return default

    def get_country_printable(self, default='N/A'):
        if self.country:
            for country in COUNTRIES:
                if country[0] == self.country:
                    return country[1]

        return default

    def get_referer(self):
        """
        Referer should be requested only by this function
        since it checks whether referer is active
        """
        if not self.referer_id:
            return None

        try:
            referer = User.query.get(self.referer_id)
            if not referer.is_deleted and not referer.is_disabled:
                return referer
        except:
            pass

        return None

    def set_referer(self, referer_id):
        referer = User.query.get(referer_id)
        if not referer or referer.is_deleted or referer.is_disabled:
            return None

        self.referer_id = referer_id

        db.session.add(self)
        db.session.commit()

        return referer

    def get_invite_referer(self):
        """
        Referer should be requested only by this function
        since it checks whether referer is active
        """
        if not self.invite_referer_id:
            return None

        try:
            invite_referer = User.query.get(self.invite_referer_id)
            if not invite_referer.is_deleted and not invite_referer.is_disabled:
                return invite_referer
        except:
            pass

        return None

    def set_invite_referer(self, invitation):
        """
        Set invite referer using either invitation ID (which is UUID V4) or username
        """
        invite_referer = None

        if len(invitation) >= 32:
            invitation = UserInvitation.query.filter_by(uuid=invitation).first()
            if not invitation or invitation.state not in (UserInvitation.SENT, UserInvitation.PENDING):
                return None

            invite_referer = User.query.get(invitation.user_id)
            if not invite_referer or invite_referer.is_deleted or invite_referer.is_disabled:
                return None

            invitation.invited_user_id = self.id
            invitation.state = UserInvitation.VERIFYING

            db.session.add(invitation)
        else:
            # Search by username
            invite_referer = User.query.filter_by(username=invitation).first()
            if not invite_referer or invite_referer.is_deleted or invite_referer.is_disabled:
                return None

        self.invite_referer_id = invite_referer.id

        db.session.add(self)
        db.session.commit()

        return invite_referer

    def is_allowed_to_receive_commission(self):
        affiliate_comission_transactions_count = Transaction.query.filter_by(user_id=self.id, type=Transaction.AFFILIATE_COMISSION).count()
        return (affiliate_comission_transactions_count == 0)

    def get_credit_pp(self):
        return u'{0:.2f}'.format(self.credit / 100.0)

    def get_bonus_credit_pp(self):
        return u'{0:.2f}'.format(self.bonus_credit / 100.0)

    def get_rating(self):
        counts = map(lambda rating: self.query_seller_feedbacks(rating=rating).count(), (Feedback.POSITIVE, Feedback.NEUTRAL, Feedback.NEGATIVE,))
        count = sum(counts)

        rating = (counts[0] * 5.0 + counts[1] * 3.0 + counts[2] * 1.0) / count if count > 0 else 0
        rating = round(rating * 10) / 10.0  # Truncate to X.X form

        return rating, counts

    def get_statistics(self):
        """Return various statistics such as feedback, rating, orders count, etc."""
        statistics = dict()

        rating, counts = self.get_rating()

        statistics['feedbacks_count'] = sum(counts)
        statistics['feedbacks_rating'] = rating
        statistics['feedbacks_rating_int'] = int(round(statistics['feedbacks_rating']))
        statistics['feedbacks_positive_rating_percents'] = int(round(float(counts[0]) / statistics['feedbacks_count'] * 100.0)) if statistics['feedbacks_count'] > 0 else 0

        statistics['orders_completed'] = Order.query \
            .filter(Product.seller_id==self.id) \
            .filter(Product.id==Order.product_id) \
            .filter(Order.state==Order.CLOSED_COMPLETED,).count()

        statistics['orders_canceled'] = Order.query \
            .filter(Product.seller_id==self.id) \
            .filter(Product.id==Order.product_id) \
            .filter(Order.state==Order.CLOSED_CANCELLED,).count()

        orders_closed = statistics['orders_completed'] + statistics['orders_canceled']

        statistics['orders_completed_percents'] = None
        if orders_closed:
            statistics['orders_completed_percents'] = int(round(statistics['orders_completed'] / orders_closed * 100))

        statistics['orders_delivered_on_time'] = Order.query \
            .filter(Product.seller_id==self.id) \
            .filter(Product.id==Order.product_id) \
            .filter(Order.state==Order.CLOSED_COMPLETED) \
            .filter(Order.delivered_on.isnot(None)) \
            .filter(Order.delivered_on < Order.delivery_on).count()

        statistics['orders_delivered_on_time_percents'] = None
        if statistics['orders_completed']:
            statistics['orders_delivered_on_time_percents'] = int(round(statistics['orders_delivered_on_time'] / statistics['orders_completed'] * 100))

        # Orders in queue

        statistics['orders_new'] = Order.query \
            .filter(Product.seller_id==self.id) \
            .filter(Product.id==Order.product_id) \
            .filter(coalesce(Order.is_pending, False) != True) \
            .filter(Order.state==Order.NEW).count()

        statistics['orders_inprogress'] = Order.query \
            .filter(Product.seller_id==self.id) \
            .filter(Product.id==Order.product_id) \
            .filter(Order.state.in_((Order.ACCEPTED, Order.SENT))).count()

        # Calculating repeat orders

        subq = db.session.query(Order.id).filter(
            Product.seller_id==self.id,
            Product.id==Order.product_id,
            Order.state==Order.CLOSED_COMPLETED,
        ).group_by(Order.buyer_id).having(func.count(Order.buyer_id) > 1).subquery()

        query = db.session.query(func.count(subq.c.order_id))

        statistics['order_repeat'] = query.first()[0]

        # Earned in current month

        earned_month = db.session \
            .query(func.sum(Transaction.amount).label('sum')) \
            .filter(Transaction.user_id == self.id) \
            .filter(Transaction.type == Transaction.ORDER_RELEASE) \
            .filter(func.MONTH(Transaction.created_on) == datetime.today().month) \
            .first().sum

        statistics['earned_month'] = earned_month if earned_month else 0

        statistics['earned_month_pp'] = u'{0:.2f}'.format(int(statistics['earned_month']) / 100.0)

        # Avg. response time

        response_time_seconds = self.get_average_response_time()

        statistics['response_time'] = timedelta(seconds=int(response_time_seconds if response_time_seconds else 0))

        return statistics

    def get_seller_statistics(self):
        statistics = dict()

        statistics['total_income'] = db.session \
            .query(func.sum(Transaction.amount).label('sum')) \
            .filter(Transaction.user_id == self.id) \
            .filter(Transaction.type.in_((Transaction.ORDER_PRERELEASE, Transaction.ORDER_RELEASE,))) \
            .first().sum

        statistics['withdrawn'] = db.session \
            .query(func.sum(Transaction.amount).label('sum')) \
            .filter(Transaction.user_id == self.id) \
            .filter(Transaction.type == Transaction.WITHDRAWAL) \
            .first().sum

        statistics['purchases'] = db.session \
            .query(func.sum(Transaction.amount).label('sum')) \
            .filter(Transaction.user_id == self.id) \
            .filter(Transaction.type.in_((Transaction.ORDER_HOLD, Transaction.FEE),)) \
            .first().sum

        statistics['pending_clearance'] = db.session \
            .query(func.sum(Transaction.amount).label('sum')) \
            .filter(Transaction.user_id == self.id) \
            .filter(Transaction.type == Transaction.ORDER_PRERELEASE) \
            .first().sum

        statistics['active_orders'] = db.session \
            .query(func.sum(Order.price).label('sum')) \
            .filter(Order.product_id == Product.id) \
            .filter(Product.seller_id == self.id) \
            .filter(coalesce(Order.is_pending, False) != True) \
            .filter(Order.state.in_((Order.ACCEPTED, Order.SENT, Order.DISPUTE, Order.NEW,))) \
            .first().sum

        return statistics

    def get_average_response_time(self):
        """
        Returns average resp. time in seconds (NOT timedelta)
        In case fake_response_time is set on user, return it instead of real value
        """

        if self.fake_response_time:
            return self.fake_response_time

        return db.session \
            .query(
                func.avg(
                    func.timestampdiff(
                        text('second'),
                        Enquiry.created_on,
                        func.if_(func.isnull(Enquiry.response_on), func.now(), Enquiry.response_on)
                    )
                ).label('avg')
            ) \
            .join(Product) \
            .filter(Product.seller_id == self.id) \
            .first().avg

    def get_unread_tickets_count(self):
        return Ticket.query.filter_by(user_id=self.id, is_closed=False).count()

    def get_orders_count(self):
        # TODO: order to have seller_id the same as order.product.seller_id
        return Order.query \
            .filter(Product.seller_id==self.id) \
            .filter(Product.id==Order.product_id) \
            .filter(coalesce(Order.is_pending, False) != True) \
            .count()

    def get_new_orders_count(self):
        # TODO: order to have seller_id the same as order.product.seller_id
        return Order.query \
            .filter(Product.seller_id==self.id) \
            .filter(Product.id==Order.product_id) \
            .filter(coalesce(Order.is_pending, False) != True) \
            .filter(Order.state==Order.NEW) \
            .count()

    def get_accepted_orders_count(self):
        # TODO: order to have seller_id the same as order.product.seller_id
        return Order.query \
            .filter(Product.seller_id==self.id) \
            .filter(Product.id==Order.product_id) \
            .filter(Order.state==Order.ACCEPTED) \
            .count()

    def get_sent_orders_count(self):
        # TODO: order to have seller_id the same as order.product.seller_id
        return Order.query \
            .filter(Product.seller_id==self.id) \
            .filter(Product.id==Order.product_id) \
            .filter(Order.state.in_((Order.SENT, Order.DISPUTE,))) \
            .count()

    def get_closed_orders_count(self):
        # TODO: order to have seller_id the same as order.product.seller_id
        # TODO: move to the orders
        return Order.query \
            .filter(Product.seller_id==self.id) \
            .filter(Product.id==Order.product_id) \
            .filter(coalesce(Order.is_pending, False) != True) \
            .filter(Order.state.in_((Order.CLOSED_COMPLETED, Order.CLOSED_CANCELLED, Order.CLOSED_REJECTED,))) \
            .count()

    def get_seller_disputes_count(self):
        return Dispute.query \
               .join(Order) \
               .join(Product) \
               .filter(Dispute.is_closed!=True) \
               .filter(Product.seller_id==self.id) \
               .count()

    def get_buyer_disputes_count(self):
        return Dispute.query \
               .filter(Dispute.is_closed!=True) \
               .filter(Dispute.user_id==self.id) \
               .count()

    def get_buyer_completed_orders_count(self):
        return Order.query \
            .filter(Order.buyer_id==self.id) \
            .filter(Order.state==Order.CLOSED_COMPLETED) \
            .count()

    def get_active_products_count(self):
        return self.products.filter(Product.is_deleted!=True, Product.is_approved==True, Product.published_on != None).count()

    def get_products_count(self):
        return self.products.filter(Product.is_deleted!=True).count()

    def get_favorite_items_count(self):
        return FavoriteProduct.query.filter_by(user_id=self.id).count()

    def get_favorite_searches_count(self):
        result = db.session.query(func.sum(FavoriteSearch.results_count).label('total_count')).filter(FavoriteSearch.user_id==self.id).first()
        return result.total_count if result.total_count else 0

    def get_unread_feedbacks(self):
        on_seller = Feedback.query \
            .filter(Feedback.reply==None, Feedback.type==Feedback.ON_SELLER, Feedback.order_id==Order.id) \
            .filter(Order.product_id==Product.id) \
            .filter(Product.seller_id==self.id) \
            .count()

        # on_buyer = Feedback.query \
        #     .filter(Feedback.reply==None, Feedback.type==Feedback.ON_BUYER, Feedback.order_id==Order.id) \
        #     .filter(Order.buyer_id==self.id) \
        #     .count()

        return on_seller

    def get_seller_feedbacks_noreplied_count(self):
        return Feedback.query \
            .filter(Feedback.reply==None, Feedback.type==Feedback.ON_SELLER, Feedback.order_id==Order.id) \
            .filter(Order.product_id==Product.id) \
            .filter(Product.seller_id==self.id) \
            .count()

    def get_buyer_feedbacks_noreplied_count(self):
        return Feedback.query \
            .filter(Feedback.reply==None, Feedback.type==Feedback.ON_BUYER, Feedback.order_id==Order.id) \
            .filter(Order.buyer_id==self.id) \
            .count()

    def get_buyer_rating(self):
        rating = dict()
        rating['positive'] = Feedback.query \
            .filter(Feedback.type==Feedback.ON_BUYER, Feedback.rating==Feedback.POSITIVE, Feedback.order_id==Order.id) \
            .filter(Order.buyer_id==self.id) \
            .count()

        rating['neutral'] = Feedback.query \
            .filter(Feedback.type==Feedback.ON_BUYER, Feedback.rating==Feedback.NEUTRAL, Feedback.order_id==Order.id) \
            .filter(Order.buyer_id==self.id) \
            .count()

        rating['negative'] = Feedback.query \
            .filter(Feedback.type==Feedback.ON_BUYER, Feedback.rating==Feedback.NEGATIVE, Feedback.order_id==Order.id) \
            .filter(Order.buyer_id==self.id) \
            .count()

        return rating

    def get_seller_rating_percents_pp(self):
        rating_positive = Feedback.query \
            .filter(Feedback.type==Feedback.ON_SELLER, Feedback.rating==Feedback.POSITIVE, Feedback.order_id==Order.id) \
            .filter(Order.product_id==Product.id) \
            .filter(Product.seller_id==self.id) \
            .count()

        rating_total = Feedback.query \
            .filter(Feedback.type==Feedback.ON_SELLER, Feedback.order_id==Order.id) \
            .filter(Order.product_id==Product.id) \
            .filter(Product.seller_id==self.id) \
            .count()

        if not rating_total:
            return 'No rating received yet'

        percents = rating_positive / float(rating_total) * 100

        return '%.0f%% Feedback positive' % percents

    def query_seller_feedbacks(self, rating=None):
        query = Feedback.query.filter(Feedback.type==Feedback.ON_SELLER, Feedback.order_id==Order.id)

        if rating is not None:
            query = query.filter(Feedback.rating==rating)

        return query \
            .filter(Order.product_id==Product.id) \
            .filter(Product.seller_id==self.id)

    def query_buyer_feedbacks(self):
        return Feedback.query \
            .filter(Feedback.type==Feedback.ON_BUYER, Feedback.order_id==Order.id) \
            .filter(Order.buyer_id==self.id) \
            .order_by(Feedback.created_on.desc())

    def query_seller_feedbacks_pending(self):
        return Order.query \
            .filter(Order.state==Order.CLOSED_COMPLETED) \
            .join(Product) \
            .filter(Product.seller_id==self.id) \
            .filter(not_(Order.feedbacks.any(Feedback.type==Feedback.ON_BUYER)))

    def query_buyer_feedbacks_pending(self):
        return Order.query \
            .filter(Order.state==Order.CLOSED_COMPLETED) \
            .filter(Order.buyer_id==self.id) \
            .filter(not_(Order.feedbacks.any(Feedback.type==Feedback.ON_SELLER)))

    def request_bitcoin_address(self):
        address = BitcoinAddress.query.filter_by(is_current=True, user_id=self.id).first()
        # TODO: check if there are any amount
        if not address:
            address = BitcoinAddress.assign(self)
        else:
            # Update touched date with the current
            address.touch()

        return address

    def get_unconfirmed_credit_pp(self):
        addresses = BitcoinAddress.query.filter(
            BitcoinAddress.user_id==self.id,
            BitcoinAddress.is_amount_confirmed==False,
            BitcoinAddress.amount!=None
        ).all()

        unconfirmed_credit = 0
        for address in addresses:
            unconfirmed_credit += address.amount

        exchange_rate = Variable.get_exchange_rate()
        if exchange_rate:
            usd = '/ {0:.2f} USD'.format(round(unconfirmed_credit * exchange_rate / 100000000L, 2))
        else:
            usd = ''

        return u'{0:.8f} BTC {1}'.format(unconfirmed_credit / 100000000.0, usd)

    def action(self, action, ip=None):
        if action == 'login':
            self.last_logged_on = datetime.utcnow()

            if ip:
                self.last_logged_ip = ip

            StatisticRecord.record_silent(
                StatisticRecord.Types.USER_LOGIN,
                self.id,
                ip=ip
            )
        elif action == 'online':
            self.last_logged_on = datetime.utcnow()
        else:
            return

        db.session.add(self)
        db.session.commit()

    def record_register(self, referer=None, ip=None, type=RegisterTypes.DEFAULT):
        if not self.is_verified:
            return

        StatisticRecord.record_silent(
            StatisticRecord.Types.USER_REGISTER,
            self.id,
            None,
            referer_id=referer.id if referer else None
        )

    def record_affiliate_register(self, user, ip=None):
        """
        This method is called for agent (referer)
        There is another method record_register which is called on user that is registered
        """
        if not user.is_verified:
            return

        transaction = None

        if app.config.get('AFFILIATE_PAYOUT_REGISTRATION'):
            transaction = Transaction.transaction_affiliate_register(self, user.username)

        StatisticRecord.record_silent(
            StatisticRecord.Types.USER_AFFILIATE_REGISTER,
            self.id,
            transaction.amount if transaction else None,
            transaction_id=transaction.id if transaction else None,
            ip=ip if ip else None
        )

    def record_affiliate_become_seller(self, user):
        """
        This method is called for agent (referer), not for one who becomes a seller
        """
        if not user.is_verified:
            return

        transaction = None

        if app.config.get('AFFILIATE_PAYOUT_BECOME_SELLER'):
            transaction = Transaction.transaction_affiliate_become_seller(self, user.username)

            StatisticRecord.record_silent(
                StatisticRecord.Types.USER_AFFILIATE_BECOME_SELLER,
                self.id,
                transaction.amount if transaction else 0,
                transaction_id=transaction.id if transaction else None,
                username=user.username
            )

    def record_invite_register(self, user, ip=None):
        """
        This method is called for invite referer
        There is another method record_register which is called on user that is registered
        """
        if not user.is_verified:
            return

        invitation = self.user_invitations.filter_by(invited_user_id=user.id).first()

        if not invitation:
            return

        invitation.state = UserInvitation.REGISTERED

        db.session.add(invitation)
        db.session.commit()

    def record_affiliate_impression(self, url, client_id=None, ip=None, referer_url=None):
        transaction = None

        if app.config.get('AFFILIATE_PAYOUT_IMPRESSION'):
            transaction = Transaction.transaction_affiliate_impression(self, client_id)

        kwargs = dict()

        if ip:
            kwargs['ip'] = ip

        if client_id:
            kwargs['client_id'] = client_id

        if url:
            kwargs['url'] = url

        if referer_url:
            kwargs['referer_url'] = referer_url

        StatisticRecord.record_silent(
            StatisticRecord.Types.USER_AFFILIATE_IMPRESSION,
            self.id,
            transaction.amount if transaction else None,
            transaction_id=transaction.id if transaction else None,
            **kwargs
        )

    def get_photo_data(self):
        if not self.photo_data:
            return None

        try:
            return json.loads(self.photo_data)
        except:
            return None

    def set_photo_data(self, data):
        self.photo_data = json.dumps(data) if data else None

    def get_photo_url(self, transform='', use_fallback=True):
        photo_data = self.get_photo_data()
        if not photo_data:
            if not use_fallback:
                return False

            # Send fallback image with the first letter
            svg = self.get_photo_fallback()
            return 'data:image/svg+xml;base64,%s' % base64.b64encode(svg)

        return Storage.get_profile_photo_url(photo_data, transform)

    def get_photo_fallback(self):
        # TODO: make random backgrounds
        return '<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg" xlink="http://www.w3.org/1999/xlink" version="1.1"><circle cx="50" cy="50" r="50" fill="#28B2FE" /><text fill="#FFF" text-anchor="middle" x="50" y="70" font-size="60" font-weight="bold" font-family="sans-serif">%s</text></svg>' % self.username[0].upper()

    def get_cover_data(self):
        if not self.cover_data:
            return None

        try:
            return json.loads(self.cover_data)
        except:
            return None

    def set_cover_data(self, data):
        self.cover_data = json.dumps(data) if data else None

    def get_cover_url(self, transform=''):
        cover_data = self.get_cover_data()
        if not cover_data:
            return None

        return Storage.get_profile_cover_url(cover_data, transform)

    def get_meta_data(self, attr=None):
        data = json.loads(self.meta_data or '{}')
        if attr is None:
            return data
        else:
            return data.get(attr, None)

    def set_meta_data(self, attr, value):
        data = json.loads(self.meta_data or '{}')
        data[attr] = value
        self.meta_data = json.dumps(data)

    def set_phone_number(self, phone_number):
        self.phone_number = phone_number
        self.phone_number_verified = True
        db.session.add(self)
        db.session.commit()

    def get_uuid(self):
        if not self.uuid:
            self.uuid = unicode(uuid.uuid4()).replace('-', '')
            db.session.add(self)
            db.session.commit()

        return self.uuid

    def is_followed_by(self, by_user_id):
        query = UserFollowers.query.filter_by(user_id=self.id, follower_id=by_user_id)
        return db.session.query(query.exists()).scalar()

    @property
    def followers(self):
        subquery = db.session.query(UserFollowers.follower_id).filter(UserFollowers.user_id == self.id).subquery()
        return db.session.query(User).filter(User.id.in_(subquery)).all()

    def to_json(self):
        return dict(
            id=self.id,
            username=self.username,
            profile_display_name=self.profile_display_name
        )

    def __repr__(self):
        return '<User %r>' % self.username


class UserSearchHistory(db.Model):
    __tablename__ = 'user_search_history'

    id = db.Column('id', db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete='cascade', onupdate='cascade'),
                        nullable=False)

    query = db.Column(db.String(256), nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return '<UserSearchHistory %d>' % self.id


class UserSkills(db.Model):
    __tablename__ = 'user_skills'

    id = db.Column('content_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete='cascade', onupdate='cascade'))

    skill_name = db.Column(db.String(20))

    def __repr__(self):
        return '<UserSkills %d>' % self.id


class UserLanguages(db.Model):
    __tablename__ = 'user_languages'

    id = db.Column('content_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete='cascade', onupdate='cascade'))

    language_name = db.Column(db.String(20))
    language_level = db.Column(db.Integer, index=True)

    def __repr__(self):
        return '<UserLanguages %d>' % self.id


class UserSocialAccount(db.Model):
    __tablename__ = 'user_social_accounts'

    id = db.Column('content_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete='cascade', onupdate='cascade'))

    provider = db.Column(db.String(50), nullable=False)
    provider_id = db.Column(db.String(64), nullable=False)

    def __repr__(self):
        return '<UserSocialAccount %d>' % self.id


class UserVerification(db.Model):
    DRAFT = 'draft'
    PENDING = 'pending'
    COMPLETED = 'completed'
    REJECTED = 'rejected'

    __tablename__ = 'user_verifications'

    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete='cascade', onupdate='cascade'), primary_key=True)
    user = db.relationship(User, foreign_keys=[user_id])
    state = db.Column(db.String(20), default=DRAFT, nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # verification data
    country_code = db.Column(db.String(20))
    # custom code to print
    random_code = db.Column(db.String(128))
    # id
    first_name = db.Column(db.String(20))
    last_name = db.Column(db.String(20))
    birthdate = db.Column(db.Date())
    id_issuing_country = db.Column(db.String(20))
    id_type = db.Column(db.String(20))
    id_number = db.Column(db.String(40))
    id_expire_date = db.Column(db.Date())
    # address
    address_line_1 = db.Column(db.String(250))
    address_line_2 = db.Column(db.String(250))
    city = db.Column(db.String(128))
    country_state = db.Column(db.String(128))
    postal_code = db.Column(db.String(128))
    # residence id
    institution_name = db.Column(db.String(256))
    document_type = db.Column(db.String(256))
    document_date_issued = db.Column(db.Date())

    def __repr__(self):
        return '<UserVerification %d>' % self.user_id

    def to_json(self):
        data = {
            'user_id': self.user_id,
            'state': self.state,
            'created_on': self.created_on,
            'country_code': self.country_code,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'birthdate': self.birthdate,
            'id_issuing_country': self.id_issuing_country,
            'id_type': self.id_type,
            'id_number': self.id_number,
            'id_expire_date': self.id_expire_date,
            'address_line_1': self.address_line_1,
            'address_line_2': self.address_line_2,
            'city': self.city,
            'country_state': self.country_state,
            'postal_code': self.postal_code,
            'institution_name': self.institution_name,
            'document_type': self.document_type,
            'document_date_issued': self.document_date_issued,
            'random_code': self.random_code
        }

        return data


class UserVerificationPhoto(db.Model):
    STATIC_PREFIX = 'uploads'

    __tablename__ = 'user_verification_photos'
    id = db.Column('user_verification_photo_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    filename = db.Column(db.String(255),)
    step = db.Column(db.Integer, nullable=False)
    hidden = db.Column(db.Boolean, nullable=False, server_default='0')
    created_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_json(self):
        data = {
            'filename': self.filename,
            'url': self.get_url(),
            'step': self.step,
            'created_on': self.created_on
        }
        return data

    def get_url(self):
        return "%s/%d/%s" % (UserVerificationPhoto.STATIC_PREFIX, self.user_id, self.filename)

    def __repr__(self):
        return '<UserVerificationPhoto %r>' % self.filename


class UserInvitation(db.Model):
    PENDING = 'pending'
    SENT = 'sent'
    EXISTING = 'existing'
    ALREADY_INVITED = 'already_invited'
    VERIFYING = 'verifying'
    REGISTERED = 'registered'

    __tablename__ = 'user_invitations'

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete='cascade', onupdate='cascade'))
    invited_user_id = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete='set null', onupdate='set null'), nullable=True)

    email = db.Column(db.String(100), index=True, nullable=False)
    state = db.Column(db.String(20), default=PENDING)

    is_manual = db.Column(db.Boolean, default=False, nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)
    sent_on = db.Column(db.DateTime)

    @staticmethod
    def get_uuid():
        return unicode(uuid.uuid4()).replace('-', '')

    def __repr__(self):
        return '<UserInvitation %d>' % self.id


class UserContact(db.Model):
    __tablename__ = 'user_contacts'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'email'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete='cascade', onupdate='cascade'), nullable=False)

    email = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(255))

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def save_multiple(user_id, contacts):
        for contact in contacts:
            try:
                db.session.merge(UserContact(user_id=user_id, **contact))
                db.session.commit()
            except:
                db.session.rollback()

    def __repr__(self):
        return '<UserContact %d>' % self.id


class UserEndorsement(db.Model):
    __tablename__ = 'user_endorsements'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete='cascade', onupdate='cascade'))
    publisher_user_id = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete='cascade', onupdate='cascade'), nullable=True)

    text = db.Column(db.Text(), nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def try_add_publisher(endorsement_id, publisher_user_id):
        try:
            endorsement = UserEndorsement.query.filter(
                UserEndorsement.id == endorsement_id,
                UserEndorsement.user_id != publisher_user_id,
                UserEndorsement.publisher_user_id.is_(None)
            ).first()

            print "1 ", endorsement
            print "2 ", UserEndorsement.query.filter_by(user_id=endorsement.user_id, publisher_user_id=publisher_user_id).first()

            if endorsement and not UserEndorsement.query.filter_by(user_id=endorsement.user_id, publisher_user_id=publisher_user_id).first():
                endorsement.publisher_user_id = publisher_user_id
                db.session.add(endorsement)
                db.session.commit()
        except Exception as e:
            pass

    def __repr__(self):
        return '<UserEndorsement %d>' % self.id


class UserFollowers(db.Model):
    __tablename__ = 'user_followers'
    __table_args__ = (
        UniqueConstraint('user_id', 'follower_id', name='_unique_relation'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    follower_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return '<UserFollowers %d>' % self.id


class Enquiry(db.Model):
    '''
    Enquiry is basically a conversation initiated by the buyer
    Can be initiated either regarding a service or just as direct message to the seller
    '''

    __tablename__ = 'enquiries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True)

    text = db.Column(db.Text)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)
    response_on = db.Column(db.DateTime)

    @staticmethod
    def search(user, product=None, seller=None, create=False):
        if not product and not seller:
            raise Exception('Either product or seller is required')

        query_kwargs = dict(product_id=product.id) if product else dict(seller_id=seller.id)

        enquiry = Enquiry.query.filter_by(user_id=user.id, **query_kwargs).first()

        if not enquiry and create:
            enquiry = Enquiry(user_id=user.id, **query_kwargs)
            db.session.add(enquiry)
            db.session.commit()

        return enquiry

    @staticmethod
    def get_or_create(user, product=None, seller=None):
        return Enquiry.search(user, product=product, seller=seller, create=True)

    def get_seller_id(self):
        if self.seller_id:
            return self.seller_id

        product = Product.query.get(self.product_id)
        if product:
            return product.seller_id

        return None

    def get_buyer(self):
        return User.query.get(self.user_id)

    def __repr__(self):
        return '<Enquiry %d>' % self.id


class OrderOffer(db.Model):
    __tablename__ = 'order_offers'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)

    text = db.Column(db.Text)

    # Price in USD cents (excluding fee)
    price = db.Column(db.Integer(), nullable=False)

    delivery_time = db.Column(db.Interval)

    # Extras list
    extras_json = db.Column(db.Text, default='[]', nullable=False)

    is_closed = db.Column(db.Boolean, default=False)
    is_accepted = db.Column(db.Boolean, default=False)
    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def create(order, extras, delivery_time, text):
        order_offer = OrderOffer(order_id=order.id, text=text)
        order_offer.set_extras(extras)
        order_offer.price = sum((extra['price'] for extra in extras))
        order_offer.delivery_time = timedelta(days=delivery_time)

        db.session.add(order_offer)
        db.session.commit()

        return order_offer

    def get_extras(self):
        return json.loads(self.extras_json or '[]')

    def set_extras(self, extras):
        modified_extras = []

        for extra in extras:
            if not extra.get('id'):
                extra['id'] = unicode(uuid.uuid4())

            modified_extras.append(extra)

        self.extras_json = json.dumps(modified_extras)

    def __repr__(self):
        return '<OrderOffer %d>' % self.id


class EnquiryOffer(db.Model):
    __tablename__ = 'enquiry_offers'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    enquiry_id = db.Column(db.Integer, db.ForeignKey('enquiries.id'), nullable=False)

    text = db.Column(db.Text)

    # Price in USD cents (excluding fee)
    price = db.Column(db.Integer(), nullable=False)

    delivery_time = db.Column(db.Interval)

    revision_count = db.Column(db.Integer, default=3, nullable=False)

    is_closed = db.Column(db.Boolean, default=False)
    is_accepted = db.Column(db.Boolean, default=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)
    expired_on = db.Column(db.DateTime)

    @staticmethod
    def create(enquiry, product, text, price, delivery_time, revision_count, expiration_time=None):
        buyer = enquiry.get_buyer()

        enquiry_offer = EnquiryOffer(
            product_id=product.id,
            enquiry_id=enquiry.id,
            text=text,
            price=price,
            revision_count=revision_count
        )

        enquiry_offer.delivery_time = timedelta(days=delivery_time)

        if expiration_time:
            enquiry_offer.expired_on = datetime.utcnow() + timedelta(days=expiration_time)

        db.session.add(enquiry_offer)
        db.session.commit()

        try:
            messaging.handle_enquiry_offer(enquiry, product, buyer, enquiry_offer)
            email.send_buyer_new_enquiry_offer(buyer.email, buyer, product, enquiry_offer)
        except Exception as e:
            print e
            # TODO: revert state in case message is not sent?
            pass

        return enquiry_offer

    def accept(self):
        if self.is_closed or self.is_accepted or (self.expired_on and self.expired_on < datetime.utcnow()):
            raise Exception('EnquiryOffer can\'t be accepted')

        self.is_accepted = True

        db.session.add(self)
        messaging.handle_enquiry_offer_update(self)

        db.session.commit()

    def get_product(self):
        return Product.query.get(self.product_id)

    def get_enquiry(self):
        return Enquiry.query.get(self.enquiry_id)

    def __repr__(self):
        return '<EnquiryOffer %d>' % self.id


class Deliverable(db.Model):
    __tablename__ = 'deliverables'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)

    text = db.Column(db.Text)

    rating = db.Column(db.Integer)

    # Metadata containing files list and various additional info
    data_json = db.Column(db.Text, default='{}', nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def create(order, files, text):
        deliverable = Deliverable(order_id=order.id, text=text)
        deliverable.set_data('files', files)
        db.session.add(deliverable)
        db.session.commit()

        return deliverable

    def get_data(self, attr=None):
        data = json.loads(self.data_json or '{}')
        if attr is None:
            return data
        else:
            return data.get(attr, None)

    def set_data(self, attr, value):
        data = json.loads(self.data_json or '{}')
        data[attr] = value
        self.data_json = json.dumps(data)

    def __repr__(self):
        return '<Deliverable %d>' % self.id


def calculate_order_fee(amount):
    return long(round(app.config['ORDER_FEE'] * amount))


def calculate_withdrawal_fee(amount):
    return long(round(app.config['WITHDRAWAL_FEE'] * amount))


def calculate_deposit_fee(amount):
    return long(round(app.config['DEPOSIT_FEE'] * amount))


def calculate_transfer_fee(amount):
    return long(round(app.config['TRANSFER_FEE'] * amount))


def calculate_wu_withdrawal_fee(amount):
    return long(round(app.config['WITHDRAWAL_FEE_WU'] * amount))


def calculate_wu_commision(amount):
    percent = 5
    if int(amount) <= 100:
        return 10
    elif int(amount) <= 200:
        return 20
    elif int(amount) <= 400:
        return 30
    elif int(amount) <= 600:
        return 40
    elif int(amount) <= 800:
        return 50
    elif int(amount) <= 999:
        return 60
    else:
        return (int(amount) * percent) / 100


class AffiliateLink(db.Model):
    __tablename__ = 'affiliate_links'

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)

    # JSON object containing image data (clodinary and aws key)
    image_data = db.Column(db.Text)

    url = db.Column(db.String(255), nullable=False)
    unique_url_id = db.Column(db.String(255), nullable=False, unique=True)

    # Visible only by admins
    is_hidden = db.Column(db.Boolean, default=False)

    is_deleted = db.Column(db.Boolean, default=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    def set_image_data(self, data):
        self.image_data = json.dumps(data)

    def get_image_url(self, transform=''):
        if not self.image_data:
            return None

        try:
            image_data = json.loads(self.image_data)
            return Storage.get_image_url(Storage.ImageType.AFFILIATE_LINK_IMAGE, image_data, transform)
        except:
            return None


class Content(db.Model):
    NEWS = 'news'
    MEMBER_NEWS = 'member_news'

    __tablename__ = 'contents'
    id = db.Column('content_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))

    type = db.Column(db.String(20), nullable=False, index=True)

    is_published = db.Column(db.Boolean, default=False)

    title = db.Column(db.String(20))
    text = db.Column(db.Text(), nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)
    updated_on = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def query_published_news(user_id):
        return Content.query.filter_by(user_id=user_id, type=Content.NEWS, is_published=True).order_by(
            Content.created_on.desc())

    @staticmethod
    def query_published_member_news():
        return Content.query.filter_by(type=Content.MEMBER_NEWS, is_published=True).order_by(Content.created_on.desc())

    def get_user(self):
        return User.query.get(self.user_id)


class Newsletter(db.Model):
    RECIPIENTS_ALL = 'all'

    __tablename__ = 'newsletters'
    id = db.Column('newsletter_id', db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))

    recipients = db.Column(db.String(20), nullable=False, index=True, default=RECIPIENTS_ALL)
    recipients_count = db.Column(db.Integer, default=0)

    is_sent = db.Column(db.Boolean, default=False)

    subject = db.Column(db.String(20))
    text = db.Column(db.Text(), nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)
    sent_on = db.Column(db.DateTime)

    @staticmethod
    def query_by_seller(seller):
        return Newsletter.query.filter_by(seller_id=seller.id)

    @staticmethod
    def get_latest_by_seller(seller):
        return Newsletter.query.filter_by(seller_id=seller.id).order_by(Newsletter.created_on.desc()).first()

    def get_seller(self):
        return User.query.get(self.seller_id)

    def approve(self):
        if self.is_sent:
            return

        buyers = User.query.filter(User.id == Order.buyer_id, Order.product_id == Product.id,
                                   Product.seller_id == self.seller_id)
        buyers_set = set()
        for user in buyers:
            if user.id in buyers_set:
                # TODO
                continue

            buyers_set.add(user.id)

        self.recipients_count = len(buyers_set)
        self.is_sent = True
        self.sent_on = datetime.utcnow()
        db.session.add(self)
        db.session.commit()


# Tickets and disputes


class Ticket(db.Model):
    __tablename__ = 'tickets'
    id = db.Column('ticket_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)

    is_closed = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    subject = db.Column(db.Text)
    text = db.Column(db.Text)

    @staticmethod
    def query_opened():
        return Ticket.query.filter(Ticket.is_closed != True)

    def close(self):
        self.is_closed = True
        db.session.add(self)
        db.session.commit()

    def delete(self):
        self.is_deleted = True
        db.session.add(self)
        db.session.commit()

    def get_user(self):
        return User.query.get(self.user_id)

    def __repr__(self):
        return '<Ticket %d>' % self.id


class Report(db.Model):
    '''
    The table contains a report with 4 possible situation.
    '''
    REASONS = [
        ('non_original_content', 'Non Original Content'),
        ('inappropriate_gig', 'Inappropriate Gig'),
        ('trademark_violation', 'Trademark Violation'),
        ('copyrights_violation', 'Copyrights Violation')
    ]

    __tablename__ = 'reports'

    id = db.Column('report_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)

    is_closed = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    reason = db.Column(ChoiceType(REASONS))
    data_json = db.Column(JSONType, nullable=True)

    @staticmethod
    def query_opened():
        return Report.query.filter(Report.is_closed != True)

    def close(self):
        self.is_closed = True
        db.session.add(self)
        db.session.commit()

    def delete(self):
        self.is_deleted = True
        db.session.add(self)
        db.session.commit()

    def get_user(self):
        return User.query.get(self.user_id)

    def __repr__(self):
        return '<Report %d>' % self.id


class Dispute(db.Model):
    RESOLVED = 'resolved'
    CANCELLED = 'cancelled'
    RESOLVED_BY_ADMIN = 'resolved_by_admin'

    __tablename__ = 'disputes'
    id = db.Column('dispute_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)

    is_closed = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    resolution = db.Column(db.String(20))

    created_on = db.Column(db.DateTime, default=datetime.utcnow)
    deadline_passed = db.Column(db.Boolean, default=False)

    text = db.Column(db.Text)
    kind = db.Column(db.String(30), default='other')
    resolution_kind = db.Column(db.String(30), nullable=False)

    @staticmethod
    def query_opened():
        return Dispute.query.filter(Dispute.is_closed != True)

    def close(self):
        self.is_closed = True
        db.session.add(self)
        db.session.commit()

    def get_product(self):
        return Order.query.get(self.order_id).product

    def get_user(self):
        return User.query.get(self.user_id)

    def get_order(self):
        return Order.query.get(self.order_id)

    def resolve(self, user, force_resolution_kind=None, by_admin=False):
        resolution_kind = force_resolution_kind if force_resolution_kind else self.resolution_kind

        if resolution_kind == 'cancel':
            self.order.change_state(new_state=Order.CLOSED_CANCELLED, user=user)
        elif resolution_kind == 'complete':
            self.order.change_state(new_state=Order.CLOSED_COMPLETED, user=user)

        self.is_closed = True

        if by_admin:
            payee = self.order.product.seller if self.user_id == user.id else User.query.get(self.user_id)
            amount = self.order.price * app.config.get('DISPUTE_FEE')
            self.resolution = Dispute.RESOLVED_BY_ADMIN
            Transaction.transaction(type=Transaction.FEE,
                                    amount=amount,
                                    user=payee,
                                    note='Dispute resolution fee')
        else:
            self.resolution = Dispute.RESOLVED

        db.session.add(self)
        db.session.commit()

    def cancel(self, user):
        self.order.revert_state(user)

        self.is_closed = True
        self.resolution = Dispute.CANCELLED

        db.session.add(self)
        db.session.commit()

    def lock(self):
        self.deadline_passed = True
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return '<Dispute %d>' % self.id


# Products and offers


class Product(db.Model):
    UNIQUE_ID_LENGTH = 6
    UNIQUE_ID_GENERATION_ATTEMPTS = 10

    __tablename__ = 'products'

    id = db.Column('id', db.Integer, primary_key=True)

    unique_id = db.Column(db.String(10), unique=True)
    uuid = db.Column(db.String(36), index=True)  # TODO: make custom type for that?

    category_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'))

    seller_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)

    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    private_description = db.Column(db.Text)
    private_filename = db.Column(db.String(255))
    private_filename_fs = db.Column(db.String(255))
    youtube_href = db.Column(db.String(255))
    is_recommended = db.Column(db.Boolean, default=False, nullable=False)

    additional_info_message = db.Column(db.Text)

    delivery_time = db.Column(db.Interval)
    revision_count = db.Column(db.Integer, default=3, nullable=False)

    quantity = db.Column(db.Integer)

    # Product is only available by URL and for paid members
    is_private = db.Column(db.Boolean, default=False, nullable=False)

    # Product is deleted and cannot be recovered, only cloned
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    # Product is approved by admin
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    not_approved = db.Column(db.Boolean, default=False, nullable=False)
    approved_count = db.Column(db.Integer, default=0, nullable=False)

    created_on = db.Column('created_on', db.DateTime, default=datetime.utcnow)
    updated_on = db.Column('updated_on', db.DateTime, default=datetime.utcnow)

    # If published_on is set, that means product is published
    published_on = db.Column('published_on', db.DateTime, nullable=True)

    views = db.Column(db.Integer, default=0)
    votes = db.Column(db.Integer, default=0)

    # Price in USD cents
    price = db.Column(db.Integer)

    # Primary product photo
    # This string contains cloudinary key for the primary photo or video
    # In case of photo, just key is stored.
    # In case of video, string 'video:KEY' is stored
    primary_photo_key = db.Column(db.String(100))

    # Additional metadata in JSON format
    data_json = db.Column(db.Text, default='{}', nullable=False)

    # Offer-related stuff
    price_offer = db.Column(db.Integer)
    active_offer_id = db.Column(db.Integer, db.ForeignKey('product_offers.id', use_alter=True, name='fk_products_product_offer'), nullable=True)

    # Feature-related stuff
    is_highlighted = db.Column(db.Boolean, default=False)
    features_json = db.Column(db.Text)

    # Relations
    orders = db.relationship('Order', backref='product', lazy='dynamic', order_by='Order.created_on.desc()')
    discounts = db.relationship('Discount', backref='product', lazy='dynamic')

    @staticmethod
    def get_unique_id():
        generated = False
        unique_id = None

        for i in range(Product.UNIQUE_ID_GENERATION_ATTEMPTS):
            unique_id = ''.join(random.choice(string.digits + string.letters) for _ in range(Product.UNIQUE_ID_LENGTH))
            if Product.query.filter_by(unique_id=unique_id).count() == 0:
                generated = True
                break

        if not generated:
            raise Exception('Cannot generate unique product ID after %d attempts' % Product.UNIQUE_ID_GENERATION_ATTEMPTS)

        return unique_id

    @staticmethod
    def get_multiple(ids):
        if not ids:
            return tuple()

        products = Product.query.filter(Product.id.in_(ids)).all()
        id_index_mapping = dict((long(id), i) for i, id in enumerate(ids))

        return sorted(products, key=lambda product: id_index_mapping[product.id])

    @staticmethod
    def get_by_custom_id(custom_id):
        """
        Detect which ID is used (UUID for private products and UNIQUE_ID for public)
        """
        if len(custom_id) >= 32:
            try:
                product_uuid = str(uuid.UUID(custom_id))
                product = Product.query.filter_by(uuid=product_uuid).first()
            except:
                return None
        else:
            product = Product.query.filter_by(unique_id=custom_id).first()

        return product

    @staticmethod
    def query_active(include_private=True):
        #TODO: ho cambiato include_private from False to True
        query = Product.query.join(User).filter(
            Product.is_deleted==False,
            Product.is_approved==True,
            Product.published_on!=None,
            or_(User.is_deleted!=True, User.is_deleted==None),
            or_(User.is_disabled!=True, User.is_disabled==None),
            User.is_verified==True
        )

        if not include_private:
            query = query.filter(Product.is_private != True)

        return query

    @staticmethod
    def get_max_price(include_private=False):
        """
        Return price of the most expensive product
        TODO: cache result
        """
        query = db.session.query(func.max(Product.price).label('max')).join(User).filter(
            Product.is_deleted==False,
            Product.is_approved==True,
            Product.published_on!=None,
            or_(User.is_deleted!=True, User.is_deleted==None),
            or_(User.is_disabled!=True, User.is_disabled==None),
            User.is_verified==True
        )

        if not include_private:
            query = query.filter(Product.is_private != True)

        result = query.first()

        return result[0]

    def get_custom_id(self):
        if self.is_private:
            return self.uuid.replace('-', '')
        else:
            return self.unique_id

    def get_url(self, route='product', _external=False, **kwargs):
        """
        Return URL depending on private/public setting
        """
        if self.is_private:
            return url_for(route, product_title='private', product_id=self.uuid.replace('-', ''), _external=_external, **kwargs)
        else:
            return url_for(route, product_title=self.get_title_seofied(), product_id=self.unique_id, _external=_external, **kwargs)

    def get_mailto_url(self):
        subject = 'Check out my service on JobDone.net'
        body = self.get_url(_external=True)

        return 'mailto:?subject=%s&body=%s' % tuple(map(quote, (subject, body,)))

    def get_data(self, attr=None):
        data = json.loads(self.data_json or '{}')
        if attr is None:
            return data
        else:
            return data.get(attr, None)

    def set_data(self, attr, value):
        data = json.loads(self.data_json or '{}')
        data[attr] = value
        self.data_json = json.dumps(data)

    def set_extras(self, extras):
        """The same as set_data('extras') but adds id for items without it"""
        if not extras:
            extras = []

        modified_extras = []

        for extra in extras:
            if 'id' not in extra or not extra['id']:
                extra['id'] = unicode(uuid.uuid4())
            modified_extras.append(extra)

        self.set_data('extras', modified_extras)

    def set_requirements(self, requirements):
        """The same as set_data('requirements') but adds id for items without it"""
        if not requirements:
            requirements = []

        modified_requirements = []

        for requirement in requirements:
            if 'id' not in requirement or not requirement['id']:
                requirement['id'] = unicode(uuid.uuid4())
            modified_requirements.append(requirement)

        self.set_data('requirements', modified_requirements)

    def set_photos(self, photos):
        """The same as set_data('photos') but adds id for items without it"""
        modified_photos = []

        for photo in photos:
            if 'id' not in photo or not photo['id']:
                photo['id'] = unicode(uuid.uuid4())
            modified_photos.append(photo)

        self.set_data('photos', modified_photos)

    def set_videos(self, videos):
        """The same as set_data('videos') but adds id for items without it"""
        modified_videos = []

        for video in videos:
            if 'id' not in video or not video['id']:
                video['id'] = unicode(uuid.uuid4())
            modified_videos.append(video)

        self.set_data('videos', modified_videos)

    def get_photos(self, transform=''):
        photos = self.get_data('photos')
        if not photos:
            return list()

        return map(lambda photo_dict: Storage.get_product_photo_url(photo_dict, transform, self.get_title_seofied()), photos)

    def get_videos(self):
        videos = self.get_data('videos')
        if not videos:
            return list()

        return map(lambda video: Storage.get_product_video_code(video['key'], self.get_title_seofied()), videos)

    def get_primary_video_url(self, format):
        videos = self.get_data('videos')
        if not videos:
            return None

        return Storage.get_product_video_url(videos[0]['key'], format, self.get_title_seofied())

    def get_thumbnails(self, transform=''):
        videos = self.get_data('videos')
        if not videos:
            videos = list()

        return self.get_photos(transform) + map(lambda video: Storage.get_product_video_poster_url(video['key']), videos)

    def get_primary_photo(self, transform=''):
        if self.primary_photo_key:
            if self.primary_photo_key.startswith('video:'):
                return Storage.get_product_video_poster_url(self.primary_photo_key[6:])

            photo_object = dict(cloudinary_key=self.primary_photo_key)

            # TODO: the following code should be optimized
            photos = self.get_data('photos') or list()
            for photo in photos:
                if photo['cloudinary_key'] == self.primary_photo_key:
                    photo_object = photo
                    break

            return Storage.get_product_photo_url(photo_object, transform)

        photos = self.get_data('photos')
        if not photos:
            return None

        return Storage.get_product_photo_url(photos[0], transform)

    def get_features(self):
        if not self.features_json:
            return list()

        return json.loads(self.features_json)

    def remove_feature(self, feature_to_remove):
        features = [feature for feature in self.get_features() if feature['type'] != feature_to_remove['type']]
        self.features_json = json.dumps(features) if features else None

        if feature_to_remove['type'] == 'highlight':
            self.is_highlighted = False

    def order_feature(self, feature_id):
        feature = app.config['SERVICE_FEATURES'].get(feature_id, None)
        if not feature:
            raise Exception('No feature with such ID')

        current_features = self.get_features()

        for current_feature in current_features:
            if feature['type'] == current_feature['type']:
                raise Exception('This feature has been already added to this service')

        if feature['price'] > self.seller.credit and feature['price'] > self.seller.bonus_credit:
            raise TransactionError()  # TODO: fix this

        current_features.append(dict(
            id=feature_id,
            type=feature['type'],
            end_date=isoformat(datetime.utcnow() + timedelta(seconds=feature['duration']))
        ))

        self.features_json = json.dumps(current_features)

        if feature['type'] == 'newsletter':
            note = u'Newsletter promotion for service %s' % self.title

        if feature['type'] == 'highlight':
            self.is_highlighted = True
            note = u'Highlighting service %s for %d days' % (self.title, timedelta(seconds=feature['duration']).days)

        if feature['type'] == 'top_search':
            note = u'Placing service %s to the top of the search' % self.title

        if feature['type'] == 'social':
            note = u'Social Media promotion for service %s' % self.title

        db.session.add(self)

        bonus_account = False

        if self.seller.bonus_credit >= feature['price']:
            BonusTransaction.transaction(BonusTransaction.OUT_FEATURE, feature['price'], self.seller, note=note)
            bonus_account = True
        else:
            Transaction.transaction(Transaction.FEATURE, feature['price'], self.seller, note=note)

        db.session.commit()

        return feature['price'], bonus_account

    # def order_auto_approve(self):
    #     AUTO_APPROVE_PRICE = 70

    #     if AUTO_APPROVE_PRICE > self.seller.credit and AUTO_APPROVE_PRICE > self.seller.bonus_credit:
    #         raise TransactionError()  # TODO: fix this

    #     note = u'Enabled Auto Approve feature for service %s' % self.title

    #     bonus_account = False

    #     if self.seller.bonus_credit >= AUTO_APPROVE_PRICE:
    #         BonusTransaction.transaction(BonusTransaction.OUT_AUTO_APPROVE, AUTO_APPROVE_PRICE, self.seller, note=note)
    #         bonus_account = True
    #     else:
    #         Transaction.transaction(Transaction.AUTO_APPROVE, AUTO_APPROVE_PRICE, self.seller, note=note)

    #     self.set_data('auto_approve', True)
    #     self.verification_approve()

    #     return AUTO_APPROVE_PRICE, bonus_account

    def set_auto_approve(self):
        self.set_data('auto_approve', True)
        self.verification_approve()

    def record_view(self, user_id=None, ip=None):
        if user_id == self.seller_id:
            # Do not record view if viewed by the seller
            return

        StatisticRecord.record_silent(
            StatisticRecord.Types.SERVICE_IMPRESSION,
            self.id,
            user_id=user_id,
            ip=ip
        )

    def get_views(self):
        cache_key = cache.SharedCache.STATISTIC_SERVICE_IMPRESSION % self.id
        cached = cache.get_cached_object(cache_key)
        if cached:
            return cached

        views = statistic.StatisticRecord.count(statistic.StatisticRecord.Types.SERVICE_IMPRESSION, self.id)
        cache.put_cached_object(cache_key, views)
        return views

    def query_feedbacks(self, rating=None):
        query = Feedback.query.filter(Feedback.type==Feedback.ON_SELLER, Feedback.order_id==Order.id, Order.product_id == self.id)

        if rating is not None:
            query = query.filter(Feedback.rating==rating)

        return query

    def is_instant(self):
        return not self.delivery_time or self.delivery_time.days == 0

    def is_favorite(self, user):
        return FavoriteProduct.query.filter_by(user_id=user.id, product_id=self.id).count() > 0

    def get_price_pp(self):
        return u'{0:.2f} USD'.format(self.price / 100.0) if self.price else u'N/A'

    def get_price_offer_pp(self):
        return u'{0:.2f} USD'.format(self.price_offer / 100.0) if self.price_offer else u'N/A'

    def get_title_seofied(self):
        return seofy_title(self.title)

    def get_filename_url(self):
        if not self.private_filename:
            return ""
        return "%s/%d/%s" % (Product.STATIC_PREFIX, self.id, self.private_filename_fs)

    def get_completed_orders_count(self):
        return self.orders.filter(Order.state == Order.CLOSED_COMPLETED).count()

    def set_private(self, save=False):
        self.is_private = True
        if not self.uuid:
            self.uuid = uuid.uuid4()

        if save:
            db.session.add(self)
            db.session.commit()

    def decrease_quantity(self, save=True):
        if self.quantity is not None and self.quantity > 0:
            self.quantity -= 1

            if save:
                db.session.add(self)
                db.session.commit()

    def set_active_offer(self, offer=None):
        if not offer:
            self.active_offer_id = None
            self.price_offer = 0
        else:
            if offer.product_id != self.id:
                raise Exception('Offer doesn\'t belong to this product')

            self.active_offer_id = offer.id
            self.price_offer = offer.calculate_price(self.price)

        db.session.add(self)
        db.session.commit()

    def get_active_offer(self):
        if not self.active_offer_id:
            return None

        offer = ProductOffer.query.get(self.active_offer_id)

        if not offer.is_active:
            # If for some reason, product offer wasn't expired by periodic script, check it here:
            return None

        return offer

    def get_statistics(self):
        """Return various statistics such as feedback, rating, orders count, etc."""
        statistics = dict()

        statistics['queued'] = self.orders.filter(
            coalesce(Order.is_pending, False) != True,
            Order.state.in_((Order.ACCEPTED, Order.SENT, Order.NEW))
        ).count()

        statistics['completed'] = self.orders.filter(Order.state == Order.CLOSED_COMPLETED).count()

        counts = map(lambda rating:self.query_feedbacks(rating=rating).count(), (Feedback.POSITIVE, Feedback.NEUTRAL, Feedback.NEGATIVE,))

        statistics['feedbacks_count'] = sum(counts)
        statistics['feedbacks_rating'] = (counts[0] * 5.0 + counts[1] * 3.0 + counts[2] * 1.0) / statistics['feedbacks_count'] if statistics['feedbacks_count'] > 0 else 0
        statistics['feedbacks_rating'] = round(statistics['feedbacks_rating'] * 10) / 10.0  # Truncate to X.X form
        statistics['feedbacks_rating_int'] = int(round(statistics['feedbacks_rating']))

        return statistics

    def get_approved_tags(self):
        tags = self.get_data('tags')
        if not tags:
            return ()

        approved_tags = [tag.tag for tag in Tag.query.filter(Tag.is_approved==True, Tag.tag.in_(tags))]
        return approved_tags

    def get_tags(self):
        tags = self.get_data('tags')
        if not tags:
            return ()

        return Tag.query.filter(Tag.tag.in_(tags)).all()

    def has_requirements(self):
        requirements = self.get_data('requirements')
        return (requirements and len(requirements) > 0)

    def verification_approve(self):
        self.approved_count += 1
        self.is_approved = True
        self.not_approved = False
        db.session.add(self)
        db.session.commit()

    def verification_reject(self):
        self.is_approved = False
        self.not_approved = True
        db.session.add(self)
        db.session.commit()

        email.send_seller_service_rejected(self.seller.email, self)

    def to_json(self):
        return dict(
            id=self.unique_id if not self.is_private else self.uuid,
            category_id=self.category_id,
            title=self.title,
            price=self.price,
            price_offer=self.price_offer if self.active_offer_id else None,
            delivery_time=self.delivery_time.days if self.delivery_time else None,
            is_recommended=self.is_recommended or False
        )

    def __repr__(self):
        return '<Product %r>' % self.title


class Product_Vote(db.Model):
    __tablename__ = 'product_votes'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    voter_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    up = db.Column(db.Boolean, default=False)
    down = db.Column(db.Boolean, default=False)
    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return '<Product_Vote %s>' % self.id


class Tag(db.Model):
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    tag = db.Column(db.String(30), nullable=False, index=True, unique=True)

    is_approved = db.Column(db.Boolean, default=False)

    @staticmethod
    def get_multiple(ids):
        if not ids:
            return ()

        tags = Tag.query.filter(Tag.id.in_(ids)).all()
        return tags

    @staticmethod
    def create_for_product(product):
        tags = product.get_data('tags')
        if not tags:
            return

        Tag.create_multiple(tags)

    @staticmethod
    def create_multiple(tags):
        for tag in tags:
            try:
                db.session.add(Tag(tag=tag))
                db.session.commit()
            except:
                db.session.rollback()


class SearchSuggest(db.Model):
    __tablename__ = 'SearchSuggest'

    id = db.Column(db.Integer, primary_key=True)
    keywords = db.Column(db.String(90), nullable=False, index=True, unique=True)
    is_approved = db.Column(db.Boolean, default=False)


class ProductPhoto(db.Model):
    THUMBNAIL_PREFIX = app.config.get('PHOTO_THUMBNAIL_PREFIX')
    STATIC_PREFIX = 'uploads'

    __tablename__ = 'product_photos'
    id = db.Column('product_photo_id', db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    filename = db.Column(db.String(255), nullable=False)

    is_primary = db.Column(db.Boolean, default=False)

    def get_url(self):
        return "%s/%d/%s" % (ProductPhoto.STATIC_PREFIX, self.product_id, self.filename)

    def get_thumb_url(self):
        return "%s/%d/%s.%s" % (
        ProductPhoto.STATIC_PREFIX, self.product_id, ProductPhoto.THUMBNAIL_PREFIX, self.filename)

    def __repr__(self):
        return '<ProductPhoto %r>' % self.filename


class ProductOffer(db.Model):
    ABSOLUTE = 'absolute'
    RELATIVE = 'relative'

    __tablename__ = 'product_offers'

    id = db.Column('id', db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product = db.relationship('Product', foreign_keys=[product_id])

    type = db.Column(db.String(20), nullable=False)
    value = db.Column(db.Integer(), nullable=False)  # Price in USD cents

    is_deleted = db.Column(db.Boolean, default=False)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def get_product(self):
        return Product.query.get(self.product_id)

    @property
    def is_active(self):
        return (self.end_date - date.today()).days >= 0

    def calculate_price(self, price):
        if self.type == ProductOffer.ABSOLUTE:
            return max(0, price - self.value)
        else:
            return max(0, int(price - self.value / 100.0 * price))

    def calculate_discount(self, price):
        if self.type == ProductOffer.ABSOLUTE:
            return min(price, self.value)
        else:
            return min(price, int(self.value / 100.0 * price))

    def get_days_remaining_printable(self):
        days = (self.end_date - date.today()).days
        if not days:
            return 'Ends today'

        if days == 1:
            return 'Ends in 1 day'

        return 'Ends in %d days' % days

    def to_json(self):
        return dict(
            id=self.id,
            product_id=self.product_id,
            type=self.type,
            value=self.value,
            start_date=self.start_date,
            end_date=self.end_date
        )


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column('category_id', db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'), nullable=True)

    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(250), nullable=True)
    seo_description = db.Column(db.String(250), nullable=True)

    products = db.relationship('Product', backref='category', lazy='dynamic')

    @property
    def followers(self):
        subquery = db.session.query(CategoryFollowers.follower_id)\
            .filter(CategoryFollowers.category_id == self.id).subquery()
        return db.session.query(User).filter(User.id.in_(subquery)).all()

    @staticmethod
    def query_top():
        return Category.query.filter_by(parent_id=None).order_by(Category.title.asc())

    @staticmethod
    def query_active():
        return Category.query.order_by(Category.title.asc())

    def get_parent(self):
        if not self.parent_id:
            return None

        return Category.query.get(self.parent_id)

    def query_subcategories(self):
        return Category.query.filter_by(parent_id=self.id).order_by(Category.title.asc())

    def get_active_products_count(self, include_private=False):
        # TODO: cache
        if not self.parent_id:
            category_ids = [cat.id for cat in self.query_subcategories().all()]
        else:
            category_ids = [self.id]

        query = db.session \
            .query(func.count(Product.id)) \
            .select_from(Product) \
            .join(User) \
            .filter(
                Product.seller_id == User.id,
                Product.is_deleted != True,
                Product.is_approved == True,
                Product.published_on!=None,
                or_(User.is_deleted != True, User.is_deleted == None),
                or_(User.is_disabled != True, User.is_disabled == None),
                User.is_verified == True,
                Product.category_id.in_(category_ids)
            ) \
            .group_by(Product.id)

        count = query.count()

        return count

    def get_active_sellers_count(self, include_private=False):
        # TODO: cache
        if not self.parent_id:
            category_ids = [cat.id for cat in self.query_subcategories().all()]
        else:
            category_ids = [self.id]

        query = db.session \
            .query(func.count(User.id)) \
            .select_from(User) \
            .join(Product) \
            .filter(
                Product.seller_id == User.id,
                Product.is_deleted != True,
                Product.is_approved == True,
                Product.published_on != None,
                or_(User.is_deleted != True, User.is_deleted == None),
                or_(User.is_disabled != True, User.is_disabled == None),
                User.is_verified == True,
                Product.category_id.in_(category_ids)
            ) \
            .group_by(User.id)

        count = query.count()

        return count

    def get_statistics(self, include_private=False):
        return dict(
            products_count=self.get_active_products_count(include_private),
            sellers_count=self.get_active_sellers_count(include_private)
        )

    def get_id(self):
        return unicode(self.id)

    def get_title_seofied(self):
        return seofy_title(self.title)

    def to_json(self):
        return dict(
            id=self.id,
            title=self.title
        )

    def __repr__(self):
        return '<Category %r>' % self.title


class CategoryFollowers(db.Model):
    __tablename__ = 'category_followers'
    __table_args__ = (
        UniqueConstraint('category_id', 'follower_id', name='_unique_relation'),
    )

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'), nullable=False)
    follower_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    def is_followed_by(self, by_user_id):
        query = CategoryFollowers.query.filter_by(category_id=self.id, follower_id=by_user_id)
        return db.session.query(query.exists()).scalar()

    def __repr__(self):
        return '<CategoryFollowers %d>' % self.id


class Feedback(db.Model):
    ON_SELLER = 0
    ON_BUYER = 1

    NEGATIVE = -1
    NEUTRAL = 0
    POSITIVE = 1

    __tablename__ = 'feedbacks'
    id = db.Column('feedback_id', db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)

    type = db.Column(db.Integer, index=True)
    rating = db.Column(db.Integer, default=NEUTRAL)
    text = db.Column(db.Text)

    reply = db.Column(db.Text)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    @validates('type')
    def received_feedback_event(self, key, value):
        if value == Feedback.ON_SELLER:
            rating = db.session.query(
                func.sum(Feedback.rating) / func.count(Feedback.id)
            ).filter(Feedback.user_id == self.user_id).scalar()

            user = User.query.filter(User.id == self.user_id).scalar()
            user.rating = rating

            db.session.add(user)
            db.session.commit()
        return value

    def get_username_hidden(self):
        username = User.query.get(self.user_id).username
        return u'%s*****%s' % (username[0], username[-1])

    def get_rating_pp(self):
        if self.rating == Feedback.NEGATIVE:
            return "Negative"
        if self.rating == Feedback.NEUTRAL:
            return "Neutral"
        if self.rating == Feedback.POSITIVE:
            return "Positive"

    def get_rating_int(self):
        if self.rating == Feedback.NEGATIVE:
            return 1
        if self.rating == Feedback.NEUTRAL:
            return 3
        if self.rating == Feedback.POSITIVE:
            return 5

    def to_json(self):
        return dict(
            id=self.id,
            created_on=isoformat(self.created_on),
            text=self.text,
            reply=self.reply,
            rating=self.rating
        )

    def __repr__(self):
        return '<Feedback %d>' % self.id


# Orders and transactions

class TransactionError(Exception):
    pass


class InvalidOrderStateException(Exception):
    pass


class InvalidExchangeRateException(Exception):
    pass


class Transaction(db.Model):
    DEPOSIT = 'deposit'
    DEPOSIT_NOFEE = 'deposit_nofee'
    WITHDRAWAL = 'withdrawal'
    ORDER_HOLD = 'order_hold'
    ORDER_PRERELEASE = 'order_prerelease'
    ORDER_RELEASE = 'order_release'
    ORDER_MONEYBACK = 'order_moneyback'

    FEE = 'fee'
    SELLER_FEE = 'seller_fee'
    PREMIUM_MEMBER_FEE = 'premium_member_fee'
    FEATURE = 'feature'
    AUTO_APPROVE = 'auto_approve'

    TRANSFER_OUTCOME = 'transfer_outcome'
    TRANSFER_INCOME = 'transfer_income'

    AFFILIATE_COMISSION = 'affiliate_comission'

    class SubTypes:
        CARD_DEPOSIT = 'card_deposit'

    __tablename__ = 'transactions'

    id = db.Column('transaction_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.order_id'))

    type = db.Column(db.String(20), nullable=False, index=True)
    subtype = db.Column(db.String(20))

    is_hold = db.Column(db.Boolean, default=False)
    amount = db.Column(db.Integer(), nullable=False)  # Price in USD cents
    note = db.Column(db.String(255))
    data_json = db.Column(db.Text, default='{}', nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    release_on = db.Column(db.DateTime)

    def get_data(self, attr=None):
        data = json.loads(self.data_json or '{}')
        if attr is None:
            return data
        else:
            return data.get(attr, None)

    def get_data_order(self):
        order_id = self.get_data('order_id')
        if order_id:
            return Order.query.get(order_id)

    def get_data_referal(self):
        user_id = self.get_data('referal_id')
        if user_id:
            return User.query.get(user_id)

    @staticmethod
    def transaction(type, amount, user, subtype=None, fee=None, order=None, note=None):
        if amount < 0:
            raise TransactionError

        kwargs = dict()
        if order:
            kwargs['order_id'] = order.id

        if note:
            kwargs['note'] = note

        if subtype:
            kwargs['subtype'] = subtype

        if type == Transaction.ORDER_HOLD:
            # Create additional fee transaction
            if not fee:
                fee = calculate_order_fee(amount)

            if user.credit < (amount + fee):
                raise TransactionError

            transaction_fee = Transaction(type=Transaction.FEE, amount=fee, user_id=user.id, **kwargs)

            referer = user.get_referer()
            # if referer and not referer.is_deleted and not referer.is_disabled:
            if referer and referer.is_allowed_to_receive_commission():
                transaction_affiliate_commission = Transaction.transaction_affiliate_commission(Transaction.FEE, referer, user, fee, order_id=order.id, save=False)
                db.session.add(transaction_affiliate_commission)

            user.credit -= fee
            db.session.add(transaction_fee)

        if type == Transaction.WITHDRAWAL:
            if user.credit < (amount + app.config['MIN_BALANCE']):
                raise TransactionError

            # Transaction goes on hold by default
            # Since it is on hold we don't create a fee transaction
            kwargs['is_hold'] = True

        if type == Transaction.DEPOSIT:
            # Create additional fee transaction
            fee = calculate_deposit_fee(amount)

            transaction_fee = Transaction(type=Transaction.FEE, amount=fee, user_id=user.id, **kwargs)
            user.credit -= fee
            db.session.add(transaction_fee)

        if type == Transaction.ORDER_PRERELEASE:
            transaction_affiliate_commission = Transaction.query.filter_by(order_id=order.id, is_hold=True).first()
            if transaction_affiliate_commission:
                transaction_affiliate_commission.is_hold = False
                transaction_affiliate_commission.user.credit += transaction_affiliate_commission.amount

                db.session.add(transaction_affiliate_commission)
                db.session.add(transaction_affiliate_commission.user)

                StatisticRecord.record_silent(
                    StatisticRecord.Types.USER_AFFILIATE_SALE,
                    transaction_affiliate_commission.user.id,
                    transaction_affiliate_commission.amount,
                    id=order.product.seller.id,
                    username=order.product.seller.username
                )

            # Transaction goes on hold by default
            kwargs['is_hold'] = True
            kwargs['release_on'] = datetime.now() + timedelta(days=app.config.get('ORDER_PENDING_CLEARANCE_DAYS'))

        if type == Transaction.ORDER_MONEYBACK:
            transaction_affiliate_commission = Transaction.query.filter_by(order_id=order.id, is_hold=True).first()
            if transaction_affiliate_commission:
                db.session.delete(transaction_affiliate_commission)

        if type in (Transaction.FEATURE, Transaction.AUTO_APPROVE):
            if user.credit < amount:
                raise TransactionError

        transaction = Transaction(type=type, amount=amount, user_id=user.id, **kwargs)

        if type in (Transaction.ORDER_HOLD, Transaction.WITHDRAWAL, Transaction.SELLER_FEE, Transaction.PREMIUM_MEMBER_FEE, Transaction.FEATURE, Transaction.AUTO_APPROVE, Transaction.FEE):
            user.credit -= amount
        elif type in (Transaction.DEPOSIT, Transaction.DEPOSIT_NOFEE, Transaction.ORDER_RELEASE, Transaction.ORDER_MONEYBACK):
            user.credit += amount
        elif type == Transaction.ORDER_PRERELEASE:
            # This is to be done later
            pass
        else:
            raise TransactionError('Unknown transaction type: %s' % type)

        db.session.add(transaction)
        db.session.add(user)
        db.session.commit()

        if type in (Transaction.DEPOSIT_NOFEE, Transaction.DEPOSIT):
            deposit_count = Transaction.query.filter(
                Transaction.user_id == user.id,
                Transaction.type.in_((Transaction.DEPOSIT_NOFEE, Transaction.DEPOSIT)),
                Transaction.is_hold != True
            ).count()

            if deposit_count == 1 and user.get_invite_referer():
                # This is the first deposit made by this user and he was invited - give him a reward
                BonusTransaction.transaction(
                    BonusTransaction.IN_REWARD,
                    2000,
                    user,
                    note='Bonus for the first deposit to invited user'
                )

        return transaction

    @staticmethod
    def transaction_affiliate_commission(type, referer, user, amount, order_id=None, save=True):
        affiliate_comission = amount * 0.9
        data = dict(
            referal_id=user.id,
            transaction_type=type,
            order_id=order_id
        )

        transaction_affiliate_comission = Transaction(
            type=Transaction.AFFILIATE_COMISSION,
            amount=affiliate_comission,
            user_id=referer.id,
            note='Affiliate comission',
            data_json=json.dumps(data),
            is_hold=True
        )

        if save:
            db.session.add(transaction_affiliate_comission)
            db.session.commit()

        return transaction_affiliate_comission

    @staticmethod
    def transaction_affiliate_impression(user, client_id, save=True):
        amount = app.config['AFFILIATE_PAYOUT_IMPRESSION']
        if not amount:
            return None

        data = dict(
            client_id=client_id
        )

        transaction_affiliate_impression = Transaction(
            type=Transaction.AFFILIATE_COMISSION,
            amount=amount,
            user_id=user.id,
            note='Unique impression payout',
            data_json=json.dumps(data),
            is_hold=True
        )

        if save:
            db.session.add(transaction_affiliate_impression)
            db.session.commit()

        return transaction_affiliate_impression

    @staticmethod
    def transaction_affiliate_register(user, username, save=True):
        amount = app.config['AFFILIATE_PAYOUT_REGISTRATION']
        if not amount:
            return None

        transaction_affiliate_register = Transaction(
            type=Transaction.AFFILIATE_COMISSION,
            amount=amount,
            user_id=user.id,
            note='Registration payout for user %s' % username,
            is_hold=True
        )

        if save:
            db.session.add(transaction_affiliate_register)
            db.session.commit()

        return transaction_affiliate_register

    @staticmethod
    def transaction_affiliate_become_seller(user, username, save=True):
        amount = app.config['AFFILIATE_PAYOUT_BECOME_SELLER']
        if not amount:
            return None

        transaction_affiliate_register = Transaction(
            type=Transaction.AFFILIATE_COMISSION,
            amount=amount,
            user_id=user.id,
            note='Payout for user %s becomes a seller' % username,
            is_hold=True
        )

        if save:
            db.session.add(transaction_affiliate_register)
            db.session.commit()

        return transaction_affiliate_register

    @staticmethod
    def transfer_transaction(sender, recipient, amount, note=''):
        if amount <= 0:
            raise TransactionError

        if sender.credit < amount:
            raise TransactionError

        # Create additional fee transaction
        fee = calculate_transfer_fee(amount)
        amount -= fee

        transaction_fee = Transaction(type=Transaction.FEE, amount=fee, user_id=sender.id, note='Transfer fee')
        sender.credit -= fee
        db.session.add(transaction_fee)

        transaction_out = Transaction(type=Transaction.TRANSFER_OUTCOME, amount=amount, user_id=sender.id,
                                      note='Transfer. Message: "%s"' % note)
        sender.credit -= amount
        transaction_in = Transaction(type=Transaction.TRANSFER_INCOME, amount=amount, user_id=recipient.id,
                                     note='Transfer. Message: "%s"' % note)
        recipient.credit += amount

        db.session.add(transaction_out)
        db.session.add(transaction_in)
        db.session.add(sender)
        db.session.add(recipient)
        db.session.commit()

        # TODO: new notification on transfer

    @staticmethod
    def calculate_sum(type, user, subtype=None, period=None):
        query = db.session \
            .query(func.sum(Transaction.amount).label('sum')) \
            .filter(Transaction.user_id == user.id) \
            .filter(Transaction.type == type)

        if subtype:
            query = query.filter(Transaction.subtype == subtype)

        if period:
            query = query.filter(Transaction.created_on > datetime.utcnow() - period)

        return query.first().sum or 0

    def confirm(self, note=''):
        if not self.is_hold:
            raise TransactionError

        # Confirm and reject are only supported for WITHDRAWALS now
        if self.type != Transaction.WITHDRAWAL:
            raise TransactionError

        self.is_hold = False
        self.note = note if note else self.note

        db.session.add(self)
        db.session.commit()

    def reject(self):
        if not self.is_hold:
            raise TransactionError

        # Confirm and reject are only supported for WITHDRAWALS now
        if self.type != Transaction.WITHDRAWAL:
            raise TransactionError

        self.user.credit += self.amount

        self.amount = 0
        self.is_hold = False
        self.note = 'Rejected withdrawal - %s' % self.note

        db.session.add(self.user)
        db.session.add(self)
        db.session.commit()

    def release(self):
        """Release ORDER_PRERELEASE transaction"""
        if self.type != Transaction.ORDER_PRERELEASE or not self.is_hold:
            raise TransactionError

        Transaction.query \
                   .filter(Transaction.id == self.id) \
                   .update(dict(type=Transaction.ORDER_RELEASE, is_hold=False))

        self.user.credit += self.amount
        db.session.add(self.user)

        db.session.commit()

    def release_affiliate_comission(self):
        """Release AFFILIATE_COMISSION transaction"""
        if self.type != Transaction.AFFILIATE_COMISSION or not self.is_hold:
            raise TransactionError

        Transaction.query \
                   .filter(Transaction.id == self.id) \
                   .update(dict(type=Transaction.AFFILIATE_COMISSION, is_hold=False))

        self.user.credit += self.amount
        db.session.add(self.user)

        db.session.commit()

    def get_amount_pp(self, nosign=False):
        sign = '-' if not nosign and self.type in (
            Transaction.WITHDRAWAL, Transaction.ORDER_HOLD, Transaction.FEE, Transaction.SELLER_FEE,
            Transaction.PREMIUM_MEMBER_FEE, Transaction.TRANSFER_OUTCOME, Transaction.FEATURE) else ''

        return '{0}{1:.2f} USD'.format(sign, self.amount / 100.0)

    def to_json(self):
        direction = 'out' if self.type in (
            Transaction.WITHDRAWAL, Transaction.ORDER_HOLD, Transaction.FEE, Transaction.SELLER_FEE,
            Transaction.PREMIUM_MEMBER_FEE, Transaction.TRANSFER_OUTCOME, Transaction.FEATURE) else 'in'

        return dict(
            id=self.id,
            order_id=self.order_id,
            type=self.type,
            amount=self.amount,
            is_hold=self.is_hold,
            direction=direction,
            created_on=isoformat(self.created_on)
        )


class BonusTransaction(db.Model):
    IN_REWARD = 'in_reward'
    OUT_FEATURE = 'out_feature'
    OUT_AUTO_APPROVE = 'out_auto_approve'

    __tablename__ = 'bonus_transactions'

    id = db.Column('bonus_transaction_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)

    type = db.Column(db.String(20), nullable=False)
    subtype = db.Column(db.String(20))

    amount = db.Column(db.Integer(), nullable=False)  # Price in USD cents
    note = db.Column(db.String(255))
    data_json = db.Column(db.Text, default='{}', nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def get_data(self, attr=None):
        data = json.loads(self.data_json or '{}')
        if attr is None:
            return data
        else:
            return data.get(attr, None)

    @staticmethod
    def transaction(type, amount, user, subtype=None, note=None):
        if amount < 0:
            raise TransactionError

        kwargs = dict()

        if note:
            kwargs['note'] = note

        if subtype:
            kwargs['subtype'] = subtype

        if type == BonusTransaction.OUT_FEATURE:
            if user.bonus_credit < amount:
                raise TransactionError

        bonus_transaction = BonusTransaction(type=type, amount=amount, user_id=user.id, **kwargs)

        if type in (BonusTransaction.OUT_FEATURE, BonusTransaction.OUT_AUTO_APPROVE):
            user.bonus_credit -= amount
        elif type in (BonusTransaction.IN_REWARD,):
            user.bonus_credit += amount
        else:
            raise TransactionError('Unknown bonus transaction type: %s' % type)

        db.session.add(bonus_transaction)
        db.session.add(user)
        db.session.commit()

        return bonus_transaction

    def get_amount_pp(self, nosign=False):
        sign = '-' if not nosign and self.type in (BonusTransaction.OUT_FEATURE, BonusTransaction.OUT_AUTO_APPROVE) else ''
        return '{0}{1:.2f} USD'.format(sign, self.amount / 100.0)

    def to_json(self):
        direction = 'out' if self.type in (BonusTransaction.OUT_FEATURE, BonusTransaction.OUT_AUTO_APPROVE) else 'in'

        return dict(
            id=self.id,
            type=self.type,
            amount=self.amount,
            direction=direction,
            created_on=isoformat(self.created_on)
        )


class Order(db.Model):
    NEW = 'new'
    ACCEPTED = 'accepted'
    CLOSED_REJECTED = 'closed_rejected'
    SENT = 'sent'
    DISPUTE = 'dispute'
    CLOSED_CANCELLED = 'closed_cancelled'
    CLOSED_COMPLETED = 'closed_completed'

    __tablename__ = 'orders'

    id = db.Column('order_id', db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))

    private_message = db.Column(db.Text)
    private_filename = db.Column(db.String(255))
    private_filename_fs = db.Column(db.String(255))

    delivery_time = db.Column(db.Interval)
    delivery_on = db.Column(db.DateTime)
    delivery_notification_sent = db.Column(db.Boolean)
    delivery_notification_sent_buyer = db.Column(db.Boolean)
    delivered_on = db.Column(db.DateTime)

    # Revision count left for this order. Taken from product.revision_count initially
    # Negative value means unlimited revision count
    revision_count_left = db.Column(db.Integer)

    is_pending_verification = db.Column(db.Boolean, default=False)

    state = db.Column(db.String(20), default=NEW, index=True, nullable=False)
    is_requirements_provided = db.Column(db.Boolean, default=False)
    requirements_provided_on = db.Column(db.DateTime)

    created_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed_on = db.Column(db.DateTime)

    # Price in USD cents (incl. applied discounts, extras, etc. and excluding fee)
    price = db.Column(db.Integer(), nullable=False)

    # Metadata containing various additional info, such as price sheet and etc.
    data_json = db.Column(db.Text, default='{}', nullable=False)

    # Stripe data
    is_pending = db.Column(db.Boolean, default=False)
    stripe_source = db.Column(db.String(50), index=True, nullable=True)

    # Relationships
    history = db.relationship('OrderHistory', backref='order', lazy='dynamic',
                              order_by='OrderHistory.created_on.desc()')
    feedbacks = db.relationship('Feedback', backref='order', lazy='dynamic')
    transactions = db.relationship('Transaction', backref='order', lazy='dynamic')
    disputes = db.relationship('Dispute', backref='order', lazy='dynamic')

    @validates('state')
    def received_order_event(self, key, value):
        if value == Order.CLOSED_COMPLETED:
            user = User.query.filter(User.id == self.product.seller_id).scalar()
            user.complete_orders = User.complete_orders + 1
            user.total_earns = User.total_earns + self.price

            db.session.add(user)
            db.session.commit()
        return value

    @staticmethod
    def calculate_amount(product, discount=None, enquiry_offer=None, selected_extras=None):
        """
        Calculate order price with offer, discount and selected extras
        Returns amount and fee
        """
        price = product.price
        extras_price = 0

        if not enquiry_offer:
            if not product.active_offer_id and discount and discount.product_id == product.id and discount.buyer_id is None:
                # Discount code is used and it's active, let's use it
                # Only available for products that doesn't have active offer
                price = discount.calculate_price(product.price)

            if product.active_offer_id:
                offer = product.get_active_offer()
                if offer:
                    price = offer.calculate_price(product.price)
        else:
            if enquiry_offer and not enquiry_offer.is_closed and not enquiry_offer.is_accepted:
                price = enquiry_offer.price

        if selected_extras:
            extras = product.get_data('extras') or tuple()
            extras_dict = dict(map(lambda extra: (extra['id'], extra), extras))

            for extra_id in selected_extras:
                if extra_id in extras_dict and 'price' in extras_dict[extra_id]:
                    extras_price += extras_dict[extra_id]['price']

        amount = price + extras_price
        fee = calculate_order_fee(amount)

        return amount, fee

    @staticmethod
    def order(product, buyer, discount=None, enquiry_offer=None, selected_extras=[], extra=None, stripe_source=None):
        price = product.price
        extras_price = 0

        metadata = dict()

        if not enquiry_offer:
            # Check if discount is used
            if not product.active_offer_id and discount and discount.product_id == product.id and discount.buyer_id is None:
                discount.set_hold(save=False)
                db.session.add(discount)

                price = discount.calculate_price(product.price)
                value = discount.calculate_discount(product.price)
                metadata['discount'] = dict(id=discount.id, value=value)

            # Check product offer
            if product.active_offer_id:
                offer = product.get_active_offer()
                if offer:
                    price = offer.calculate_price(product.price)
                    value = offer.calculate_discount(product.price)
                    metadata['offer'] = dict(id=offer.id, value=value)
        else:
            enquiry_offer.accept()
            price = enquiry_offer.price

            metadata['enquiry_offer'] = dict(
                id=enquiry_offer.id,
                delivery_time=enquiry_offer.delivery_time.days,
                revision_count=enquiry_offer.revision_count
            )

        if selected_extras:
            extras = product.get_data('extras') or []
            extras_dict = dict(map(lambda extra: (extra['id'], extra), extras))
            metadata['extras'] = list()

            for extra_id in selected_extras:
                if extra_id in extras_dict and 'price' in extras_dict[extra_id]:
                    extras_price += extras_dict[extra_id]['price']
                    metadata['extras'].append(extras_dict[extra_id])

        if extra:
            metadata['extra'] = extra

        final_price = price + extras_price
        fee = calculate_order_fee(final_price)

        metadata['fee'] = fee

        is_requirements_provided = not product.has_requirements()

        is_pending_verification = False
        moderation_policy = app.config['NEW_ORDER_MODERATION_POLICY']

        if moderation_policy['all_customers']:
            is_pending_verification = True
        elif moderation_policy['new_customers']:
            orders_count = Order.query.filter(Order.buyer_id==buyer.id) \
                                      .filter(Order.state==Order.CLOSED_COMPLETED) \
                                      .count()

            if orders_count < moderation_policy['new_customers_min_orders_count']:
                is_pending_verification = True

        if is_pending_verification:
            if final_price < moderation_policy['threshold']:
                # Order price is less than threshold
                is_pending_verification = False

        order = Order(
            product_id=product.id,
            buyer_id=buyer.id,
            price=final_price,
            data_json=json.dumps(metadata),
            is_requirements_provided=is_requirements_provided,
            is_pending_verification=is_pending_verification
        )

        if stripe_source:
            order.stripe_source = stripe_source
            order.is_pending = True

        db.session.add(order)
        db.session.flush()

        if not order.is_pending:
            # Only charge user if the order is not pending

            if discount:
                discount.use(buyer)

            Transaction.transaction(
                type=Transaction.ORDER_HOLD,
                amount=final_price,
                user=buyer,
                order=order,
                fee=fee
            )



        db.session.commit()

        if not order.is_pending:
            order.send_notifications()

        return order

    @staticmethod
    def fake_order(product, buyer, date):
        metadata = dict(fake=True)
        order = Order(product_id=product.id, buyer_id=buyer.id, price=product.price, data_json=json.dumps(metadata), state=Order.CLOSED_COMPLETED, created_on=date)
        db.session.add(order)
        db.session.commit()

        return order

    def send_notifications(self):
        try:
            messaging.handle_new_order(self.buyer, self.product.seller, self, self.product)
        except:
            # TODO
            pass

        fee = price = 'N/A'

        try:
            price = '${0:.2f}'.format(self.price / 100.0)
            fee = '${0:.2f}'.format(self.get_data('fee') / 100.0)
        except:
            pass

        slack.notification_sale(
            'New order by {0} from {1}. Amount = {2}, fee = {3}'.format(
                self.buyer.username,
                self.product.seller.username,
                price,
                fee
            )
        )

        email.send_buyer_new_order(self.buyer.email, self)
        email.send_seller_new_order(self.product.seller.email, self)

    def confirm_pending(self):
        if not self.is_pending:
            return

        discount_id = self.get_data('discount')
        if discount_id:
            discount = Discount.query.get(discount_id)
            if discount:
                discount.use(self.buyer)

        Transaction.transaction(
            type=Transaction.ORDER_HOLD,
            amount=self.price,
            user=self.buyer,
            order=self,
            fee=self.get_data('fee') or 0
        )

        self.is_pending = False
        db.session.add(self)
        db.session.commit()

        self.send_notifications()

    def cancel_pending(self, note=None):
        if not self.is_pending:
            return

        self.state = Order.CLOSED_CANCELLED
        self.closed_on = datetime.utcnow()

        history = OrderHistory(
            order_id=self.id,
            state=Order.CLOSED_CANCELLED,
            user_id=self.buyer.id,
            note=note
        )

        discount_id = (self.get_data('discount') or dict()).get('id')
        if discount_id:
            discount = Discount.query.get(discount_id)
            if discount:
                discount.set_hold(hold=False, save=False)
                db.session.add(discount)

        db.session.add(self)
        db.session.add(history)
        db.session.commit()

    def change_state(self, new_state, user, note=None):
        # TODO: check for the rights of user
        # TODO: check if the state can be changed

        if self.is_pending:
            raise Exception('Can\'t change state of the pending order')

        if new_state == Order.ACCEPTED:
            if self.state == Order.SENT:
                # Buyer has requested a revision
                if not self.revision_count_left:
                    raise Exception('Can\'t request a revision. No requests left')

                self.revision_count_left -= 1
                self.delivered_on = None

            if self.state == Order.NEW:
                enquiry_offer = self.get_data('enquiry_offer')

                if enquiry_offer:
                    self.delivery_time = timedelta(days=enquiry_offer.get('delivery_time'))
                    self.delivery_on = datetime.utcnow() + timedelta(days=enquiry_offer.get('delivery_time'))
                elif self.product.delivery_time:
                    self.delivery_time = self.product.delivery_time
                    self.delivery_on = datetime.utcnow() + self.product.delivery_time
                else:
                    # Workaround for products without delivery time (for some reason)
                    self.delivery_time = timedelta(days=7)
                    self.delivery_on = datetime.utcnow() + timedelta(days=7)

                if enquiry_offer:
                    self.revision_count_left = enquiry_offer.get('revision_count')
                else:
                    self.revision_count_left = self.product.revision_count

                order_offers = self.get_data('order_offers') or list()
                for order_offer in order_offers:
                    self.delivery_time += timedelta(days=order_offer.get('delivery_time', 0))
                    self.delivery_on += timedelta(days=order_offer.get('delivery_time', 0))

                # Order has been accepted by the seller
                try:
                    messaging.handle_order_accepted(self)
                except:
                    # TODO
                    pass
        elif new_state in (Order.CLOSED_REJECTED, Order.CLOSED_CANCELLED):
            # Process moneyback
            # UPD: including price of extra offers

            order_offers = self.get_data('order_offers') or list()
            order_offers_price = sum((item['price'] for item in order_offers))

            Transaction.transaction(type=Transaction.ORDER_MONEYBACK,
                                    amount=self.price + order_offers_price,
                                    user=self.buyer,
                                    order=self)

            self.closed_on = datetime.utcnow()

            try:
                if new_state == Order.CLOSED_CANCELLED:
                    messaging.handle_order_cancelled(self, self.buyer)
                elif new_state == Order.CLOSED_REJECTED:
                    messaging.handle_order_rejected(self, note)
            except:
                # TODO
                pass
        elif new_state == Order.CLOSED_COMPLETED:
            # Release money to the seller
            # UPD: including price of extra offers

            order_offers = self.get_data('order_offers') or list()
            order_offers_price = sum((item['price'] for item in order_offers))

            Transaction.transaction(type=Transaction.ORDER_PRERELEASE,
                                    amount=self.price + order_offers_price,
                                    user=self.product.seller,
                                    order=self)

            try:
                messaging.handle_order_completed(self)
            except:
                # TODO
                pass

            StatisticRecord.record_silent(
                StatisticRecord.Types.USER_SELLER_ORDER_COMPLETED,
                self.product.seller.id,
                self.price,
                buyer_id=self.buyer.id,
                buyer_username=self.buyer.username
            )

            StatisticRecord.record_silent(
                StatisticRecord.Types.SERVICE_ORDER_COMPLETED,
                self.product.id,
                self.price,
                buyer_id=self.buyer.id,
                buyer_username=self.buyer.username
            )

            self.product.decrease_quantity()
            self.closed_on = datetime.utcnow()
        elif new_state == Order.SENT:
            self.delivered_on = datetime.utcnow()
        elif new_state == Order.DISPUTE:
            try:
                if user.id == self.buyer.id:
                    messaging.handle_order_dispute_by_buyer(self)
                else:
                    messaging.handle_order_dispute_by_seller(self)

                # Send email to other peer
                recipient = self.buyer if user.id != self.buyer.id else self.product.seller
                email.send_dispute(recipient.email, recipient, user, self)
            except:
                # TODO
                pass

        self.state = new_state

        history = OrderHistory(
            order_id=self.id,
            state=new_state,
            user_id=user.id,
            note=note
        )

        db.session.add(self)
        db.session.add(history)
        db.session.commit()

        if self.state == Order.CLOSED_COMPLETED and self.buyer.get_buyer_completed_orders_count() == 1:
            # This is the first completed order
            invite_referer = self.buyer.get_invite_referer()

            if invite_referer:
                BonusTransaction.transaction(
                    BonusTransaction.IN_REWARD,
                    2000,
                    invite_referer,
                    note='Bonus for the purchase by user %s' % invite_referer.username
                )

    def revert_state(self, user):
        order_history_records = self.history[1:2]

        state = order_history_records[0].state if order_history_records else None

        if not state:
            state = Order.NEW

        self.state = state

        history = OrderHistory(
            order_id=self.id,
            state=state,
            user_id=user.id
        )

        db.session.add(self)
        db.session.add(history)
        db.session.commit()

    def deliver(self, files, text):
        deliverable = Deliverable.create(self, files, text)

        if self.state == Order.ACCEPTED:
            # Only change state if order state is ACCEPTED
            self.change_state(Order.SENT, self.product.seller)

        try:
            messaging.handle_order_sent(self, deliverable)
            email.send_buyer_order_delivered(self.buyer.email, self)
        except:
            # TODO: revert state in case message is not sent?
            pass

    def offer(self, extras, custom_extra=None, delivery_time=7, text=None, attachments=None):
        selected_extras = list()
        product_extras = self.product.get_data('extras') or list()
        extras_dict = dict(map(lambda extra: (extra['id'], extra), product_extras))

        for extra_id in extras:
            if extra_id in extras_dict:
                selected_extras.append(extras_dict[extra_id])

        if custom_extra:
            selected_extras.append(custom_extra)

        order_offer = OrderOffer.create(self, selected_extras, delivery_time, text)

        try:
            messaging.handle_order_offer(self, order_offer, attachments)
            # email.send_buyer_order_offer(self.buyer.email, order_offer)
        except Exception as e:
            # TODO: revert state in case message is not sent?
            pass

    def accept_offer(self, order_offer):
        order_offers = self.get_data('order_offers') or list()
        order_offers.append(dict(
            id=order_offer.id,
            extras=order_offer.get_extras(),
            price=order_offer.price,
            delivery_time=order_offer.delivery_time.days,
            fee=calculate_order_fee(order_offer.price)
        ))

        self.set_data('order_offers', order_offers)

        if self.state == Order.ACCEPTED:
            # We can only operate on delivery time when order is ACCEPTED, not NEW
            self.delivery_time += order_offer.delivery_time
            self.delivered_on += order_offer.delivery_time

        db.session.add(self)

        order_offer.is_accepted = True
        db.session.add(order_offer)

        Transaction.transaction(
            type=Transaction.ORDER_HOLD,
            amount=order_offer.price,
            user=self.buyer,
            order=self,
            note='Extra offer #%d' % order_offer.id
        )

        db.session.commit()

        try:
            messaging.handle_order_offer_update(self, order_offer)
            # email.send_seller_order_offer_accepted(self.product.seller.email, order_offer)
        except Exception as e:
            # TODO: revert state in case message is not sent?
            raise e
            pass

    def get_state_pretty_print(self):
        if self.state == Order.NEW:
            return "New"
        elif self.state == Order.ACCEPTED:
            return "In progress"
        elif self.state == Order.SENT:
            return "Delivered"
        elif self.state == Order.DISPUTE:
            return "Dispute"
        elif self.state == Order.CLOSED_REJECTED:
            return "Rejected"
        elif self.state == Order.CLOSED_CANCELLED:
            return "Cancelled"
        elif self.state == Order.CLOSED_COMPLETED:
            return "Completed"
        else:
            return "N/A"

    def is_state_active(self):
        return self.state in (Order.NEW, Order.ACCEPTED, Order.SENT)

    def is_state_dispute(self):
        return self.state == Order.DISPUTE

    def is_state_closed(self):
        return self.state in (Order.CLOSED_REJECTED, Order.CLOSED_CANCELLED, Order.CLOSED_COMPLETED)

    def get_active_dispute(self):
        if self.state != Order.DISPUTE:
            return None

        return self.disputes.filter_by(is_closed=False, is_deleted=False).first()

    def get_deadline_interval(self):
        if not self.delivery_time:
            return timedelta(0)

        interval = self.created_on + self.delivery_time - datetime.utcnow()
        if interval < timedelta(0):
            return timedelta(0)

        return interval

    def get_buyer_deadline_interval(self):
        if self.state != Order.SENT:
            return timedelta(0)

        record = self.history.filter_by(state=Order.SENT).first()

        interval = record.created_on + timedelta(days=2) - datetime.utcnow()
        if interval < timedelta(0):
            return timedelta(0)

        return interval

    def create_buyer_feedback(self, rating, text):
        buyer_feedback = self.get_buyer_feedback()
        if buyer_feedback:
            return buyer_feedback

        feedback = Feedback(
            type=Feedback.ON_BUYER,
            order_id=self.id,
            user_id=self.product.seller.id,
            rating=rating,
            text=text
        )

        db.session.add(feedback)
        db.session.commit()

    def get_buyer_feedback(self):
        for feedback in self.feedbacks:
            if feedback.type == Feedback.ON_BUYER:
                return feedback

        return None

    def create_seller_feedback(self, rating, text):
        seller_feedback = self.get_seller_feedback()
        if seller_feedback:
            return seller_feedback

        feedback = Feedback(
            type=Feedback.ON_SELLER,
            order_id=self.id,
            user_id=self.buyer.id,
            rating=rating,
            text=text
        )

        db.session.add(feedback)
        db.session.commit()

    def get_seller_feedback(self):
        for feedback in self.feedbacks:
            if feedback.type == Feedback.ON_SELLER:
                return feedback

        return None

    def get_data(self, attr=None):
        data = json.loads(self.data_json or '{}')
        if attr is None:
            return data
        else:
            return data.get(attr, None)

    def set_data(self, attr, value):
        data = json.loads(self.data_json or '{}')
        data[attr] = value
        self.data_json = json.dumps(data)

    def get_total_price(self):
        """
        Returns total price (without fees) as a sum of:
            1. order price
            2. extras added when order was created
            3. custom extras added when order was in progress
        """
        price = self.price
        price += sum((offer['price'] for offer in (self.get_data('order_offers') or list())))
        return price

    def get_revision_count(self):
        return self.history.filter(OrderHistory.state == Order.ACCEPTED).count()

    def to_json(self):
        return dict(
            id=self.id,
            state=self.state,
            created_on=isoformat(self.created_on),
            price=self.price,
            delivery_on=isoformat(self.delivery_on) if self.delivery_on else None
        )

    def __repr__(self):
        return '<Order %r>' % self.id


class OrderHistory(db.Model):
    __tablename__ = 'orders_history'
    id = db.Column('order_history_id', db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))

    state = db.Column(db.String(20), default=Order.NEW, index=True, nullable=False)
    note = db.Column(db.Text)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return '<OrderHistory %r>' % self.id


class Withdrawal(db.Model):
    BTC = 'btc'
    WESTERN_UNION = 'western_union'
    PAYPAL = 'paypal'
    SKRILL = 'skrill'
    PAYONEER = 'payoneer'
    PAYZA = 'payza'

    __tablename__ = 'withdrawals'
    id = db.Column('withdrawal_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.transaction_id'))

    type = db.Column(db.String(20), index=True, nullable=False)

    is_closed = db.Column(db.Boolean, default=False)
    is_rejected = db.Column(db.Boolean, default=False)

    data_json = db.Column(db.Text, default='{}', nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def query_requests(all=True):
        query = Withdrawal.query
        if not all:
            query = query.filter(Withdrawal.is_closed != True)

        return query.order_by(Withdrawal.is_closed.asc(), Withdrawal.created_on.desc())

    @staticmethod
    def request(user, amount, info, payment_system, note):
        withdrawal_fee = calculate_withdrawal_fee(amount)
        amount_received = amount - withdrawal_fee

        data = dict(info=info,
                    amount=amount,
                    withdrawal_fee=withdrawal_fee,
                    amount_received=amount_received)

        transaction = Transaction.transaction(type=Transaction.WITHDRAWAL,
                                              amount=amount,
                                              user=user,
                                              note=note)

        withdrawal = Withdrawal(type=payment_system,
                                user_id=user.id,
                                transaction_id=transaction.id,
                                data_json=json.dumps(data))

        db.session.add(withdrawal)
        db.session.commit()
        return withdrawal

    @staticmethod
    def request_btc(user, amount, info):
        withdrawal_fee = calculate_withdrawal_fee(amount)
        amount_received = amount - withdrawal_fee

        data = dict(info=info,
                    amount=amount,
                    withdrawal_fee=withdrawal_fee,
                    amount_received=amount_received)

        transaction = Transaction.transaction(type=Transaction.WITHDRAWAL,
                                              amount=amount,
                                              user=user,
                                              note='BTC')

        withdrawal = Withdrawal(type=Withdrawal.BTC,
                                user_id=user.id,
                                transaction_id=transaction.id,
                                data_json=json.dumps(data))

        db.session.add(withdrawal)
        db.session.commit()
        return withdrawal

    @staticmethod
    def request_western_union(user, amount, info):
        withdrawal_fee = calculate_withdrawal_fee(amount)
        wu_fee = calculate_wu_commision(amount - withdrawal_fee)
        amount_received = amount - withdrawal_fee - wu_fee

        data = dict(info=info,
                    amount=amount,
                    withdrawal_fee=withdrawal_fee,
                    wu_fee=wu_fee,
                    amount_received=amount_received)

        transaction = Transaction.transaction(type=Transaction.WITHDRAWAL,
                                              amount=amount,
                                              user=user,
                                              note='Western Union')

        withdrawal = Withdrawal(type=Withdrawal.WESTERN_UNION,
                                user_id=user.id,
                                transaction_id=transaction.id,
                                data_json=json.dumps(data))

        db.session.add(withdrawal)
        db.session.commit()
        return withdrawal

    @staticmethod
    def request_paypal(user, amount, info):
        withdrawal_fee = calculate_withdrawal_fee(amount)
        amount_received = amount - withdrawal_fee

        data = dict(info=info,
                    amount=amount,
                    withdrawal_fee=withdrawal_fee,
                    amount_received=amount_received)

        transaction = Transaction.transaction(type=Transaction.WITHDRAWAL,
                                              amount=amount,
                                              user=user,
                                              note='PayPal')

        withdrawal = Withdrawal(type=Withdrawal.PAYPAL,
                                user_id=user.id,
                                transaction_id=transaction.id,
                                data_json=json.dumps(data))

        db.session.add(withdrawal)
        db.session.commit()
        return withdrawal

    def confirm(self, reply):
        self.get_transaction().confirm()
        self.is_closed = True
        data = self.get_data()
        data['reply'] = reply
        self.data_json = json.dumps(data)

        db.session.add(self)
        db.session.commit()

    def reject(self):
        transaction = self.get_transaction()
        transaction.reject()

        self.is_closed = True
        self.is_rejected = True
        db.session.add(self)
        db.session.commit()

    def get_transaction(self):
        return Transaction.query.get(self.transaction_id)

    def get_user(self):
        return User.query.get(self.user_id)

    def get_data(self):
        return json.loads(self.data_json)

    def __repr__(self):
        return '<Withdrawal %r>' % self.id


class BitcoinAddress(db.Model):
    __tablename__ = 'bitcoin_addresses'
    id = db.Column('bitcoin_address_id', db.Integer, primary_key=True)
    address = db.Column('address', db.String(40), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    is_current = db.Column(db.Boolean, default=False)
    touched_on = db.Column(db.DateTime)

    amount = db.Column(db.BigInteger)
    is_amount_confirmed = db.Column(db.Boolean, default=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def add(address):
        try:
            new_address = BitcoinAddress(address=address)
            db.session.add(new_address)
            db.session.commit()
            return True
        except:
            return False

    @staticmethod
    def get_current(user):
        return BitcoinAddress.query.filter(
            BitcoinAddress.user_id == user.id,
            BitcoinAddress.is_current == True
        ).first()

    @staticmethod
    def assign(user):
        address = BitcoinAddress.query.filter(BitcoinAddress.user_id == None).first()
        if not address:
            return None

        updated = BitcoinAddress.query \
            .filter(BitcoinAddress.id == address.id, BitcoinAddress.user_id == None) \
            .update({
                BitcoinAddress.user_id: user.id,
                BitcoinAddress.is_current: True,
                BitcoinAddress.touched_on: datetime.utcnow()
            })

        db.session.commit()

        return address if updated > 0 else None

    def touch(self):
        self.touched_on = datetime.utcnow()
        db.session.add(self)
        db.session.commit()


class Voucher(db.Model):
    PREMIUM_MEMBER = 'premium_member'
    SELLER = 'seller'

    __tablename__ = 'vouchers'
    id = db.Column('voucher_id', db.Integer, primary_key=True)
    code = db.Column(db.String(15), unique=True, nullable=False)

    type = db.Column(db.String(20), nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    is_invite = db.Column(db.Boolean, default=False, nullable=False)

    total_count = db.Column(db.Integer, default=1, nullable=False)
    used_count = db.Column(db.Integer, default=0, nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def add(user, type, is_invite, total_count=1):
        try:
            code = ''.join(random.choice(string.digits + string.ascii_letters) for _ in range(15))
            voucher = Voucher(code=code, type=type, total_count=total_count, user_id=user.id if user else None,
                              is_invite=is_invite)
            db.session.add(voucher)
            db.session.commit()
            return True
        except:
            return False

    @staticmethod
    def get_invite(code):
        return Voucher.query.filter_by(code=code, is_invite=True, used_count=0).first()

    @staticmethod
    def use(type, code, is_invite=False):
        """ Returns (bool, bool) where the first argument is True if the operation is succeeded
            The second argument is True if the voucher exists"""
        voucher = Voucher.query.filter_by(type=type, code=code, is_invite=is_invite).first()
        if not voucher:
            return False, False

        if voucher.used_count >= voucher.total_count:
            return False, True

        voucher.used_count += 1
        db.session.add(voucher)
        db.session.commit()

        return True, True


class Discount(db.Model):
    ABSOLUTE = 'absolute'
    RELATIVE = 'relative'

    __tablename__ = 'discounts'
    id = db.Column('discount_id', db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    code = db.Column(db.String(15), unique=True, nullable=False)

    type = db.Column(db.String(20), nullable=False)
    value = db.Column(db.Integer(), nullable=False)  # Price in USD cents

    buyer_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    is_hold = db.Column(db.Boolean)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)
    used_on = db.Column(db.DateTime)

    @staticmethod
    def add(seller, product_id, type, value):
        try:
            code = ''.join(random.choice(string.digits + string.ascii_letters) for _ in range(15)) # TODO
            discount = Discount(code=code, type=type, value=value, seller_id=seller.id, product_id=product_id)
            db.session.add(discount)
            db.session.commit()
            return discount
        except:
            return None

    @staticmethod
    def check(code, product):
        return Discount.query.filter_by(code=code, product_id=product.id, buyer_id=None, is_hold=None).first()

    def set_hold(self, hold=True, save=True):
        self.is_hold = True if hold else None

        if save:
            db.session.add(self)
            db.session.commit()

    def use(self, buyer, save=True):
        self.buyer_id = buyer.id
        self.used_on = datetime.utcnow()
        self.is_hold = False

        if save:
            db.session.add(self)
            db.session.commit()

    def calculate_discount(self, price):
        if self.type == Discount.ABSOLUTE:
            return min(price, self.value)
        else:
            return min(price, int(self.value / 100.0 * price))

    def calculate_price(self, price):
        if self.type == Discount.ABSOLUTE:
            return max(0, price - self.value)
        else:
            return max(0, int(price - self.value / 100.0 * price))

    def get_product(self):
        return Product.query.get(self.product_id)

    def get_buyer(self):
        return User.query.get(self.buyer_id)

    def to_json(self):
        return dict(
            id=self.id,
            code=self.code,
            product_id=self.product_id,
            used_on=self.used_on,
            is_hold=self.is_hold,
            type=self.type,
            value=self.value
        )


class Variable(db.Model):
    __tablename__ = 'variables'
    id = db.Column('variable_id', db.String(50), primary_key=True)
    value = db.Column(db.String(255))
    set_on = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def set(key, value):
        var = Variable(id=key, value=value, set_on=datetime.utcnow())
        db.session.merge(var)
        db.session.commit()

    @staticmethod
    def get(key, default=None):
        value = default
        var = Variable.query.get(key)

        if var and var.value:
            value = var.value

        return value

    @staticmethod
    def get_exchange_rate():
        # TODO: cache
        exchange_rate = None
        var = Variable.query.get('exchange_rate')
        if var and var.value:
            try:
                exchange_rate = float(var.value)
            except:
                pass

        return exchange_rate

    @staticmethod
    def get_wu_enabled():
        # TODO: cache
        wu_enabled = True
        var = Variable.query.get('wu_enabled')
        if var and var.value:
            try:
                wu_enabled = bool(int(var.value))
            except:
                pass

        return wu_enabled

    @staticmethod
    def set_wu_enabled(wu_enabled):
        Variable.set('wu_enabled', 1 if wu_enabled else 0)

    @staticmethod
    def get_seller_fee():
        return app.config.get('SELLER_FEE_USD', None)

    @staticmethod
    def get_seller_fee_pp():
        fee = app.config.get('SELLER_FEE_USD')
        if not fee:
            return None

        return u'{0:.2f} USD'.format(fee / 100.0)

    @staticmethod
    def get_premium_fee():
        return app.config.get('PREMIUM_FEE_USD', None)

    @staticmethod
    def get_premium_fee_pp():
        fee = app.config.get('PREMIUM_FEE_USD')
        if not fee:
            return None

        return u'{0:.2f} USD'.format(fee / 100.0)


class FavoriteProduct(db.Model):
    __tablename__ = 'favorite_products'
    id = db.Column('favorite_product_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product')

    @staticmethod
    def toggle(user, product):
        existing = FavoriteProduct.query.filter_by(user_id=user.id, product_id=product.id).first()
        if existing:
            db.session.delete(existing)
        else:
            new = FavoriteProduct(user_id=user.id, product_id=product.id)
            db.session.add(new)

            if user.id != product.seller.id:
                # Do not send notification to yourself
                email.send_seller_service_favorited(product.seller.email, product, user)

        db.session.commit()


class FavoriteSearch(db.Model):
    __tablename__ = 'favorite_searches'
    id = db.Column('favorite_search_id', db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'))
    q = db.Column(db.String(255), nullable=False)  # TODO: keep hash?

    results_count = db.Column(db.Integer, default=0)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)
    updated_on = db.Column(db.DateTime, default=datetime.utcnow)

    def update(self):
        self.updated_on = datetime.utcnow()
        self.results_count = 0
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def check(user_id, q):
        return FavoriteSearch.query.filter_by(user_id=user_id, q=q).count() > 0

    @staticmethod
    def toggle(user_id, q):
        existing = FavoriteSearch.query.filter_by(user_id=user_id, q=q).first()
        if existing:
            db.session.delete(existing)
        else:
            new = FavoriteSearch(user_id=user_id, q=q)
            db.session.add(new)

        db.session.commit()


class EmailMessage(db.Model):
    __tablename__ = 'email_messages'

    id = db.Column('email_message_id', db.Integer, primary_key=True)
    recipient = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(255))
    text = db.Column(db.Text)
    html = db.Column(db.Text)

    is_sent = db.Column(db.Boolean, default=False)
    last_error = db.Column(db.Text)

    created_on = db.Column(db.DateTime, default=datetime.utcnow)
