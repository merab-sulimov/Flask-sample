import StringIO
from flask import request, redirect, url_for, session, send_file, make_response, g, render_template
from flask_login import login_user, logout_user, current_user
from UniversalAnalytics import Tracker
from rauth import OAuth2Service
import json

from app import app
from app.utils.captcha import create_captcha
from app.models import User, UserEndorsement
from app import db
from . import auth
from app.utils import slack, country
from app.utils.storage import Storage


class OAuthSignIn(object):
    providers = None

    def __init__(self, provider_name):
        self.provider_name = provider_name
        credentials = app.config['OAUTH_CREDENTIALS'][provider_name]
        self.consumer_id = credentials['id']
        self.consumer_secret = credentials['secret']

    def authorize(self):
        pass

    def callback(self):
        pass

    def get_callback_url(self):
        return url_for('auth.oauth_callback', provider=self.provider_name, _external=True)

    @classmethod
    def get_provider(self, provider_name):
        if self.providers is None:
            self.providers = {}
            for provider_class in self.__subclasses__():
                provider = provider_class()
                self.providers[provider.provider_name] = provider
        return self.providers[provider_name]


class FacebookSignIn(OAuthSignIn):
    def __init__(self):
        super(FacebookSignIn, self).__init__('facebook')
        self.service = OAuth2Service(
            name='facebook',
            client_id=self.consumer_id,
            client_secret=self.consumer_secret,
            authorize_url='https://graph.facebook.com/oauth/authorize',
            access_token_url='https://graph.facebook.com/oauth/access_token',
            base_url='https://graph.facebook.com/'
        )

    def authorize(self):
        return redirect(self.service.get_authorize_url(
            scope='email',
            response_type='code',
            redirect_uri=self.get_callback_url())
        )

    def callback(self):
        if 'code' not in request.args:
            raise

        try:
            oauth_session = self.service.get_auth_session(data={
                'code': request.args['code'],
                'grant_type': 'authorization_code',
                'redirect_uri': self.get_callback_url()
            }, decoder=json.loads)
        except Exception, e:
            # TODO: report error to Sentry
            raise e

        me = oauth_session.get('me?fields=first_name,last_name,email,picture.width(160).height(160),location.fields(location.fields(country_code))').json()

        picture = None
        country_code = None

        try:
            picture = me['picture']['data']['url']
            country_code = me['location']['location']['country_code']
        except:
            pass

        return (
            'facebook',
            me['id'],
            me.get('email'),
            picture,
            country_code,
            (me.get('first_name', ''), me.get('last_name', ''))
        )


class GoogleSignIn(OAuthSignIn):
    def __init__(self):
        super(GoogleSignIn, self).__init__('google')
        self.service = OAuth2Service(
            name='google',
            client_id=self.consumer_id,
            client_secret=self.consumer_secret,
            authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
            access_token_url='https://www.googleapis.com/oauth2/v3/token',
            base_url='https://www.googleapis.com/oauth2/v1'
        )

    def authorize(self):
        return redirect(self.service.get_authorize_url(
            scope='https://www.googleapis.com/auth/userinfo.email',
            response_type='code',
            redirect_uri=self.get_callback_url())
        )

    def callback(self):
        if 'code' not in request.args:
            raise

        data = {
            'code': request.args['code'],
            'grant_type': 'authorization_code',
            'redirect_uri': self.get_callback_url()
        }

        response = self.service.get_raw_access_token(data=data).json()
        oauth_session = self.service.get_session(response['access_token'])
        userinfo = oauth_session.get('https://www.googleapis.com/oauth2/v1/userinfo').json()

        try:
            name = (userinfo.get('given_name', ''), userinfo.get('family_name', ''))
        except:
            name = ('', '')

        return (
            'google',
            userinfo.get('id'),
            userinfo.get('email'),
            userinfo.get('picture', None),
            None,  # G+ doesn't provide country
            name
        )


class LinkedinSignIn(OAuthSignIn):
    def __init__(self):
        super(LinkedinSignIn, self).__init__('linkedin')
        self.service = OAuth2Service(
            name='linkedin',
            client_id=self.consumer_id,
            client_secret=self.consumer_secret,
            authorize_url='https://www.linkedin.com/oauth/v2/authorization',
            access_token_url='https://www.linkedin.com/oauth/v2/accessToken',
            base_url='https://api.linkedin.com/v1/'
        )

    def authorize(self):
        return redirect(self.service.get_authorize_url(
            scope='r_basicprofile,r_emailaddress',
            response_type='code',
            redirect_uri=self.get_callback_url())
        )

    def callback(self):
        if 'code' not in request.args:
            raise

        data = {
            'code': request.args['code'],
            'grant_type': 'authorization_code',
            'redirect_uri': self.get_callback_url()
        }

        response = self.service.get_raw_access_token(data=data).json()
        oauth_session = self.service.get_session(response['access_token'])
        userinfo = oauth_session.get('people/~:(id,firstName,lastName,picture-url,email-address,location:(country:(code)))?format=json').json()

        try:
            country_code = userinfo['location']['country']['code']
        except:
            country_code = None

        return (
            'linkedin',
            userinfo.get('id'),
            userinfo.get('emailAddress'),
            userinfo.get('pictureUrl', None),
            country_code,
            (userinfo.get('firstName', ''), userinfo.get('lastName', ''))
        )


@auth.route('/login/oauth/callback/<provider>')
def oauth_callback(provider):
    # if current_user.is_authenticated:
        # return redirect(url_for('account.index'))

    oauth = OAuthSignIn.get_provider(provider)

    try:
        provider, provider_id, email, picture_url, country_code, name = oauth.callback()
        email = email.strip()
    except Exception as e:
        if 'oauth_mode' in session and session['oauth_mode'] == 'link_popup':
            # For popup, render error message right on this page
            return render_template('new/oauth/link_callback.html', provider=provider, oauth_error=401)
        else:
            # For standard auth route redirect to login route with error code
            return redirect(url_for('index', mode='login', code=401))

    if current_user.is_authenticated and 'oauth_mode' in session:
        if 'oauth_mode' in session and session['oauth_mode'] == 'link_popup':
            # Link account in a popup window
            del session['oauth_mode']

            if current_user.email != email:
                return render_template('new/oauth/link_callback.html', provider=provider, oauth_error=400)

            social_account = current_user.get_social_account(provider)
            if not social_account:
                current_user.create_social_account(provider, provider_id)

            return render_template('new/oauth/link_callback.html', provider=provider)

    if not provider or not provider_id or not email:
        return redirect(url_for('index', mode='login', code=401))

    user = User.query.filter_by(email=email).first()
    if not user:
        user, _ = User.generate(email, verified=True, empty_password=True)
        if picture_url:
            storage = Storage()
            try:
                aws_key, cloudinary_key = storage.upload_profile_photo_from_url(picture_url, user.id, user.username)
                user.set_photo_data(dict(aws_key=aws_key, cloudinary_key=cloudinary_key))
                db.session.add(user)
                db.session.commit()
            except Exception, e:
                pass

        if country_code and country.resolve(country_code):
            user.country = country_code.upper()
            db.session.add(user)
            db.session.commit()

        if any(name):
            user.profile_first_name = name[0]
            user.profile_last_name = name[1]
            db.session.add(user)
            db.session.commit()

        if 'oauth_page' in session and session['oauth_page'] == 'affiliate':
            user.is_affiliate_panel_enabled = True
            db.session.add(user)
            db.session.commit()

        register_type = getattr(User.RegisterTypes, provider.upper()) \
            if hasattr(User.RegisterTypes, provider.upper()) \
            else User.RegisterTypes.DEFAULT

        invite_referer = referer = None

        if User.INVITATION_COOKIE in request.cookies:
            # We have a cookie with invite ID or username, which has higher priority over aff. cookie
            invite_referer = user.set_invite_referer(request.cookies.get(User.INVITATION_COOKIE))
        elif User.REFERER_COOKIE in request.cookies:
            # We have a cookie with referer ID
            referer = user.set_referer(request.cookies.get(User.REFERER_COOKIE))

        user.record_register(ip=g.ip, referer=referer, type=register_type)

        if invite_referer:
            invite_referer.record_invite_register(user, ip=g.ip)
        elif referer:
            referer.record_affiliate_register(user, ip=g.ip)

        slack.notification('New user signed up with {0}. Username: {1}'.format(provider, user.username))

        # send event to Google Analytics
        tracker = Tracker.create('UA-86740209-1')
        tracker.send('event', 'NewMember', provider, user.email) # facebook / gmail / email
        del tracker

    social_account = user.get_social_account(provider)
    if not social_account:
        user.create_social_account(provider, provider_id)

    # Save UserEndorsement after registration/login
    if 'auth_endorsement_id' in session:
        UserEndorsement.try_add_publisher(session['auth_endorsement_id'], user.id)
        del session['auth_endorsement_id']

    user.action('login', ip=g.ip)

    login_user(user, True)

    if 'oauth_next' in session:
        return redirect(session['oauth_next'])
    
    return redirect(url_for('account.index'))


@auth.route('/login/oauth/<provider>')
def oauth_authorize(provider):
    # if current_user.is_authenticated:
        # return redirect(url_for('account.index'))

    if 'next' in request.args:
        # Save 'next' route in the session
        session['oauth_next'] = request.args['next']

    if 'page' in request.args:
        # Save 'page' option in the session
        session['oauth_page'] = request.args['page']

    if 'mode' in request.args and current_user.is_authenticated:
        session['oauth_mode'] = request.args['mode']

    oauth = OAuthSignIn.get_provider(provider)
    return oauth.authorize()


@auth.route('/login', methods=['GET'])
def login():
    kwargs = dict()

    if request.args.get('code'):
        kwargs['code'] = request.args.get('code')

    if request.args.get('next'):
        kwargs['next'] = request.args.get('next')

    return redirect(url_for('index', mode='login', **kwargs))


@auth.route('/register', methods=['GET'])
def register():
    return redirect(url_for('index', mode='signup'))


@auth.route('/register/verify', methods=['GET', 'POST'])
def register_verify():
    code, email = request.args.get('code'), request.args.get('email')
    if not code or not email:
        return redirect(url_for('auth.login', code=400))

    user = User.query.filter_by(is_verified=False, verification_code=code, email=email).first()
    if not user:
        return redirect(url_for('auth.login', code=400))

    user.is_verified = True
    user.verification_code = None
    db.session.add(user)
    db.session.commit()

    invite_referer = user.get_invite_referer()
    if invite_referer:
        invite_referer.record_invite_register(user, ip=g.ip)
    else:
        referer = user.get_referer()
        if referer:
            referer.record_affiliate_register(user, ip=g.ip)

    # Save UserEndorsement after registration/login
    if 'auth_endorsement_id' in session:
        UserEndorsement.try_add_publisher(session['auth_endorsement_id'], user.id)
        del session['auth_endorsement_id']

    # NOTIFICATION
    slack.notification('New user registered : {username}'.format(username=user.username))

    # send event to Google Analytics
    tracker = Tracker.create('UA-86740209-1')
    tracker.send('event', 'NewMember', 'email', '{email}'.format(email=email)) # facebook / gmail / email
    del tracker

    return redirect(url_for('auth.login', code=200))


@auth.route('/logout.html')
def logout():
    logout_user()
    return redirect(url_for('index'))


@auth.route('/captcha.jpg')
def captcha():
    chars, img, img_type = create_captcha()
    session['captcha'] = chars
    img_io = StringIO.StringIO()
    img.save(img_io, 'JPEG', quality=70)
    img_io.seek(0)

    resp = make_response(send_file(img_io, mimetype='image/jpeg'))
    resp.cache_control.no_cache = True
    return resp
