import re
from flask import json, request, url_for, session, g, redirect, flash
from flask_login import login_user
from sqlalchemy import or_
from datetime import datetime, timedelta

from app import cache, email
from app.decorators import xhr_required
from app.helpers import APIError
from app.models import db, User, UserEndorsement
from app.utils import generate_password_rsa
from . import auth
from .forms import LoginForm, RegisterForm, RecoveryForm, RecoveryCompleteForm


@auth.route('/api/auth/login', methods=['POST'])
@xhr_required
def api_login():
    # Count login attempts
    login_attempts = session.get('login_attempts', 0)
    login_attempts += 1
    captcha_required = True if login_attempts >= 5 else False
    session['login_attempts'] = login_attempts

    form = LoginForm(csrf_enabled=False)
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None and re.match(r'[^@]+@[^@]+\.[^@]+', form.username.data):
            user = User.query.filter_by(email=form.username.data).first()

        if user is not None and user.verify_password(form.password.data):
            if user.is_deleted or user.is_disabled:
                raise APIError('This account was disabled. If you feel this was done in error, please contact our support team.')

            if not user.is_verified:
                #TODO: place option to send again verification code in email.
                raise APIError('Please verify your email address before start using market')

            session['login_attempts'] = 0

            login_user(user)
            user.action('login', ip=g.ip)

            # Update RSA password if it's not set
            if not user.password_rsa:
                user.password_rsa = generate_password_rsa(form.password.data)
                db.session.add(user)
                db.session.commit()

            # Save UserEndorsement after registration/login
            if 'auth_endorsement_id' in session:
                UserEndorsement.try_add_publisher(session['auth_endorsement_id'], user.id)
                del session['auth_endorsement_id']

            return json.jsonify(dict(success=True))

        raise APIError('Wrong username or password')
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@auth.route('/api/auth/signup', methods=['POST'])
@xhr_required
def api_signup():
    registered_user_by_ip = User.query.filter(User.registered_ip == g.ip,
                                              User.registered_on >= (datetime.today() - timedelta(days=2))).count()
    if registered_user_by_ip > 2:
        flash('Limit reached. Try again later.')
        return redirect(url_for('index'))

    form = RegisterForm(csrf_enabled=False)
    if form.validate_on_submit():
        user = User(username=form.username.data,
                    password=form.password.data,
                    email=form.email.data.strip(),
                    country=form.country.data,
                    registered_ip=g.ip)

        if form.page.data and form.page.data == 'affiliate':
            user.is_affiliate_panel_enabled = True

        db.session.add(user)
        db.session.commit()

        referer_set = False

        # if form.invite.data:
        #     voucher = Voucher.get_invite(form.invite.data)
        #     if voucher:
        #         success, _ = Voucher.use(voucher.type, voucher.code, is_invite=True)
        #         if success:
        #             user.seller_fee_paid = True
        #             db.session.add(user)
        #             db.session.commit()
        #             session['seller_fee_voucher'] = True
        #             referer_set = user.set_referer(voucher.user_id)

        if User.INVITATION_COOKIE in request.cookies:
            # We have a cookie with invite ID or username, which has higher priority over aff. cookie
            user.set_invite_referer(request.cookies.get(User.INVITATION_COOKIE))
        elif not referer_set and User.REFERER_COOKIE in request.cookies:
            # We have a cookie with referer ID
            user.set_referer(request.cookies.get(User.REFERER_COOKIE))

        code = user.request_verification()
        url = url_for('auth.register_verify', code=code, email=user.email, _external=True)

        email.send_welcome(user.email, url)

        return json.jsonify(dict(success=True))
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@auth.route('/api/auth/recovery', methods=['POST'])
@xhr_required
def api_recovery():
    form = RecoveryForm(csrf_enabled=False)
    if form.validate_on_submit():
        user = User.query.filter(or_(User.username==form.username.data, User.email==form.username.data)).first()

        if not user:
            raise APIError('We are unable to find user with this username/email')

        if user.is_deleted or user.is_disabled or not user.is_verified:
            #TODO: place option to send again verification code in email.
            raise APIError('Your user has been disabled, please contact a support')

        token = User.generate_token()
        cache.add_token(token, cache.TokenType.PASSWORD_RECOVERY, user.id)

        url = url_for('index', mode='recovery', token=token, _external=True)

        email.send_password_recovery(user.email, user.username, url)

        return json.jsonify(dict(success=True))
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@auth.route('/api/auth/recovery/complete', methods=['POST'])
@xhr_required
def api_recovery_complete():
    form = RecoveryCompleteForm(csrf_enabled=False)
    if form.validate_on_submit():
        user_id = cache.search_token(form.token.data, cache.TokenType.PASSWORD_RECOVERY)

        if not user_id:
            raise APIError('The link is not valid anymore')

        user = User.query.get(user_id)

        if not user:
            raise APIError('The link is not valid anymore')

        if user.is_deleted or user.is_disabled or not user.is_verified:
            raise APIError('Your user has been disabled, please contact a support')

        user.password = form.password.data
        # db.session.add(user)
        db.session.commit()

        return json.jsonify(dict(success=True))
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@auth.route('/api/auth/country')
@xhr_required
def api_country():
    from app.utils.country import detect, COUNTRIES
    country = detect(request.remote_addr)
    
    return json.jsonify(dict(country=country, countries=COUNTRIES))
