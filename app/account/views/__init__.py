import random
import string
import time
import calendar
import iso8601
import stripe
from flask import url_for, redirect, render_template, g, json, request, session, abort, make_response, flash
from flask_login import login_required, logout_user
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func
from datetime import datetime, timedelta
from twilio.rest import Client
from UniversalAnalytics import Tracker

from app import app, sentry, email, statistic, cache
from app.decorators import xhr_required, seller_required
from app.utils.storage import Storage, ImagePresets
from app.utils.tz import get_utc_datetime
from app.models import db, User, UserSocialAccount, Order, Transaction, Variable, FavoriteProduct, FavoriteSearch, \
    Feedback, Product, Voucher, Withdrawal, BitcoinAddress, AffiliateLink, isoparse
from app.helpers import APIError
from app.utils import tz
from .. import account
from ..forms import SettingsUpdateAPIForm, ProfileUpdateAPIForm, ProfilePhotoAPIForm, EmailSettingsForm, \
    PasswordChangeAPIForm, TransferFundsAPIForm, EmptyForm, PhoneNumberVerifyAPIForm, WithdrawBTCAPIForm, \
    WithdrawPayPalAPIForm, ProfileCoverAPIForm, DepositCardAPIForm, WithdrawPayZaAPIForm, WithdrawPayoneerAPIForm, \
    WithdrawSkrillAPIForm
from ..helpers import prepare_application_data


@account.route('/dashboard')
@login_required
def index():
    todos = []

    if not g.user.profile_description or not g.user.photo_data:
        todos.append(dict(type='profile_incomplete'))

    if not g.user.password_hash:
        todos.append(dict(type='empty_password'))

    # Query for orders with requirements
    orders_pending_requirements = Order.query \
                                       .filter(Order.state == Order.NEW) \
                                       .filter(Order.is_requirements_provided == False) \
                                       .filter(Order.buyer_id == g.user.id) \
                                       .order_by(Order.created_on.asc())

    for order in orders_pending_requirements:
        todos.append(dict(type='order_pending_requirements', order_id=order.id))

    # Query for orders with pending feedback

    orders_pending_feedback = Order.query \
                                   .filter(Order.state == Order.CLOSED_COMPLETED) \
                                   .filter(Order.buyer_id == g.user.id) \
                                   .join(Feedback) \
                                   .filter(Feedback.type == Feedback.ON_SELLER) \
                                   .group_by(Order) \
                                   .having(func.count(Feedback.id) == 0) \
                                   .order_by(Order.closed_on.asc())

    for order in orders_pending_feedback:
        todos.append(dict(type='order_pending_feedback', order_id=order.id))

    orders_pending_feedback = Order.query \
                                   .filter(Order.state == Order.CLOSED_COMPLETED) \
                                   .filter(Order.product_id == Product.id) \
                                   .filter(Product.seller_id == g.user.id) \
                                   .join(Feedback) \
                                   .filter(Feedback.type == Feedback.ON_BUYER) \
                                   .group_by(Order) \
                                   .having(func.count(Feedback.id) == 0) \
                                   .order_by(Order.closed_on.asc())

    for order in orders_pending_feedback:
        todos.append(dict(type='order_pending_feedback', order_id=order.id))

    #if not g.user.premium_member:
    #    todos.append(dict(type='become_premium'))

    if not g.user.seller_fee_paid:
        todos.append(dict(type='become_seller'))
    else:
        services_count = g.user.products.count()
        if services_count < 3:
            todos.append(dict(type='add_service', count=services_count))

        todos.append(dict(type='get_endorsed'))

    application_data = prepare_application_data()
    application_data['extra'] = dict(todos=todos)

    seller_statistics = g.user.get_statistics() if g.user.seller_fee_paid else None

    current_month = datetime.utcnow().strftime('%B')

    return render_template(
        'new/account/dashboard.html',
        application_data=application_data,
        seller_statistics=seller_statistics,
        current_month=current_month
    )


@account.route('/invite')
@login_required
def invite():
    application_data = prepare_application_data()

    return render_template(
        'new/account/invite.html',
        application_data=application_data
    )


@account.route('/endorse')
@login_required
@seller_required
def endorse():
    application_data = prepare_application_data()

    return render_template(
        'new/account/endorse.html',
        application_data=application_data
    )


@account.route('/account/orders/<order_id>')
@login_required
def order(order_id):
    if not order_id.isdigit():
        abort(404)

    order = Order.query.get_or_404(order_id)
    if order.product.seller_id == g.user.id:
        return redirect(url_for('account.seller_order', order_id=order_id))

    # Admin views order page as a buyer
    if order.buyer_id == g.user.id or g.user.is_admin:
        return redirect(url_for('account.buyer_order', order_id=order_id))

    abort(403)


@account.route('/account/favorites')
@login_required
def favorites():
    return render_template('new/account/favorites.html', application_data=prepare_application_data())


@account.route('/account/inbox')
@login_required
def inbox():
    application_data = prepare_application_data()

    application_data['extra'] = dict()

    if g.user.seller_fee_paid and g.user.get_active_products_count() > 0:
        application_data['extra']['has_active_products'] = True

    return render_template('new/account/inbox.html', application_data=application_data)


@account.route('/account/settings')
@login_required
def settings():
    application_data = prepare_application_data()

    current_timezone = g.user.tz if g.user.tz else 'UTC'
    timezones = tz.get_list()

    application_data['extra'] = dict(
        tz=current_timezone,
        profile_first_name=g.user.profile_first_name if g.user.profile_first_name else '',
        profile_last_name=g.user.profile_last_name if g.user.profile_last_name else '',
        empty_password=(not g.user.password_hash),
        is_affiliate_panel_enabled=int(bool(g.user.is_affiliate_panel_enabled)),
        tab='main'
    )

    delete_reasons = app.config['USER_DELETE_REASONS']

    return render_template(
        'new/account/settings.html',
        application_data=application_data,
        timezones=timezones,
        current_timezone=current_timezone,
        delete_reasons=delete_reasons
    )


@account.route('/account/settings/notifications', methods=['GET', 'POST'])
@login_required
def settings_notifications():
    form = EmailSettingsForm(is_newsletter_enabled=g.user.is_newsletter_enabled,
                             is_sales_report_enabled=g.user.is_sales_report_enabled,
                             is_marketplace_digest_enabled=g.user.is_marketplace_digest_enabled)

    if form.validate_on_submit():
        g.user.is_newsletter_enabled = form.is_newsletter_enabled.data
        g.user.is_sales_report_enabled = form.is_sales_report_enabled.data
        g.user.is_marketplace_digest_enabled = form.is_marketplace_digest_enabled.data
        db.session.add(g.user)
        db.session.commit()

        #flash('Newsletter options have been updated', 'success')
        return redirect(url_for('account.settings_notifications'))

    return render_template('new/account/settings-notifications.html', form=form)


@account.route('/account/settings/financials', methods=['GET', 'POST'])
@login_required
def settings_financials():
    return render_template('new/account/settings-financials.html')


@account.route('/account/settings/verification', methods=['GET', 'POST'])
@login_required
def settings_verification():
    from app.utils.country import COUNTRIES

    application_data = prepare_application_data()

    application_data['extra'] = dict(
        tab='verification',
        stripe_key=app.config['STRIPE_PUBLISHABLE_KEY'],
    )

    return render_template(
        'new/account/settings-verification.html',
        application_data=application_data,
        countries=COUNTRIES
    )


@account.route('/account/balance')
@login_required
def balance():
    application_data = prepare_application_data()

    btc_exchange_rate = Variable.get_exchange_rate()

    application_data['extra'] = dict(
        stripe_key=app.config['STRIPE_PUBLISHABLE_KEY'],
        user_email=g.user.email
    )

    return render_template(
        'new/account/balance.html',
        application_data=application_data,
        btc_exchange_rate=btc_exchange_rate
    )


@account.route('/account/earnings')
@login_required
@seller_required
def earnings():
    application_data = prepare_application_data()

    seller_statistics = g.user.get_seller_statistics()

    combo_months = calendar.month_name[1:]
    combo_years = reversed([year for year in range(g.user.registered_on.year, datetime.utcnow().year + 1)])

    return render_template('new/account/earnings.html',
                           application_data=application_data,
                           seller_statistics=seller_statistics,
                           combo_months=combo_months,
                           combo_years=combo_years)


@account.route('/account/affiliate')
@login_required
def affiliate():
    application_data = prepare_application_data()

    referrals_count = db.session.query(func.count(User.id).label('count')) \
                                .filter(User.referer_id == g.user.id) \
                                .first().count

    referrals_payout = db.session \
            .query(func.sum(Transaction.amount).label('sum')) \
            .filter(Transaction.user_id == g.user.id) \
            .filter(Transaction.type == Transaction.AFFILIATE_COMISSION) \
            .first().sum

    referrals_payout = referrals_payout if referrals_payout else 0
    referrals_payout_pp = u'{0:.2f}'.format(int(referrals_payout) / 100.0)

    return render_template(
        'new/account/affiliate.html',
        application_data=application_data,
        referrals_count=referrals_count if referrals_count else 0,
        referrals_payout_pp=referrals_payout_pp
    )


@account.route('/account/premium', methods=['GET', 'POST'])
@login_required
def become_premium():
    if g.user.premium_member:
        return redirect(url_for('account.index'))

    premium_fee = Variable.get_premium_fee()
    premium_fee_pp = '{0:.2f}'.format(premium_fee / 100.0)
    can_pay = (g.user.credit >= premium_fee)

    form = EmptyForm()

    if request.form.get('use_coupon'):
        coupon = request.form.get('coupon')

        success, exists = Voucher.use(type=Voucher.PREMIUM_MEMBER, code=coupon)
        if success:
            g.user.premium_member = True
            db.session.add(g.user)
            db.session.commit()

            flash('You have successfuly become premium member. Congratulations!', 'success')

            # send event to Google Analytics
            # TODO: Need execute this event from browser side, is more better for traking.
            tracker = Tracker.create('UA-86740209-1')
            tracker.send('event', 'BecomePremium', "Vousher", g.user.username)
            del tracker

            return redirect(url_for('account.index'))
        else:
            if exists:
                coupon_error = 'Coupon code has been already used'
            else:
                coupon_error = 'Coupon code not found'

        application_data=prepare_application_data()
        application_data['extra'] = dict(use_coupon=True)

        return render_template('new/account/become-premium.html', form=form, can_pay=can_pay, premium_fee=premium_fee, premium_fee_pp=premium_fee_pp, coupon_error=coupon_error, application_data=application_data)

    if can_pay and form.validate_on_submit():
        Transaction.transaction(type=Transaction.PREMIUM_MEMBER_FEE,
                                amount=premium_fee,
                                user=g.user,
                                note='One-time premium membership fee')

        g.user.premium_member = True
        db.session.add(g.user)
        db.session.commit()

        tracker = Tracker.create('UA-86740209-1')
        tracker.send('event', 'BecomePremium', "Payment", g.user.username)
        del tracker

        flash('You have successfuly become premium member. Congratulations!', 'success')

        return redirect(url_for('account.index'))

    return render_template('new/account/become-premium.html', form=form, can_pay=can_pay, premium_fee=premium_fee, premium_fee_pp=premium_fee_pp, application_data=prepare_application_data())


@account.route('/api/account/profile', methods=['PUT'], defaults={'username': None})
@account.route('/api/account/<username>/profile', methods=['PUT'])
@login_required
@xhr_required
def api_profile_change(username):
    if username:
        if not g.user.is_admin:
            print 'Admin allowed only'
            abort(404)

        user = User.get_active_by_username(username)
        if not user:
            print 'User not found'
            abort(404)
    else:
        user = g.user

    form = ProfileUpdateAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        user.profile_description = form.profile_description.data
        user.profile_headline = form.profile_headline.data

        db.session.add(user)
        db.session.commit()

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/settings', methods=['PUT'])
@login_required
@xhr_required
def api_settings_change():
    form = SettingsUpdateAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        if (form.profile_first_name.data and not form.profile_last_name.data) or (form.profile_last_name.data and not form.profile_first_name.data):
            raise APIError('Please specify both first and last name')

        if form.profile_first_name.data:
            g.user.profile_first_name = form.profile_first_name.data
            g.user.profile_last_name = form.profile_last_name.data

        g.user.tz = form.tz.data
        g.user.is_affiliate_panel_enabled = bool(form.is_affiliate_panel_enabled.data)

        db.session.add(g.user)
        db.session.commit()

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/settings/password', methods=['POST'])
@login_required
@xhr_required
def api_settings_password_change():
    form = PasswordChangeAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        g.user.password = form.password.data

        email.send_password_changed(g.user.email, g.user.username)

        db.session.add(g.user)
        db.session.commit()

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/settings/phone_number', methods=['POST'])
@login_required
@xhr_required
def api_settings_phone_number():
    if g.user.phone_number and g.user.phone_number_verified:
        abort(403)

    form = PhoneNumberVerifyAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        if not form.code.data:
            if 'phone_number_code_ts' in session:
                if int(time.time()) - session['phone_number_code_ts'] < 120:
                    abort(429)

            if User.query.filter(User.phone_number == form.phone_number.data, User.id != g.user.id).count():
                abort(409)

            session['phone_number_code'] = ''.join(random.choice(string.digits) for _ in range(6))
            session['phone_number_code_ts'] = int(time.time())
            session['phone_number_code_attempts'] = 0
            session['phone_number'] = form.phone_number.data

            try:
                client = Client(app.config['TWILIO_SID'], app.config['TWILIO_TOKEN'])
                client.api.messages.create(to='+%s' % form.phone_number.data,
                                           from_=app.config['TWILIO_PHONE_NUMBER'],
                                           body='Your jobdone.net security code is %s' % session['phone_number_code'])
            except Exception:
                sentry.captureException()
                print "Unable to send message via Twilio. Dumping security code:", session['phone_number_code']
                abort(500)

            return json.jsonify(dict())
        else:
            if not 'phone_number' in session or not 'phone_number_code' in session or not 'phone_number_code_attempts' in session:
                abort(500)

            session['phone_number_code_attempts'] += 1

            if session['phone_number_code_attempts'] > 5:
                abort(500)

            if session['phone_number_code'] != form.code.data:
                abort(400)

            g.user.set_phone_number(session['phone_number'])

            return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/settings/delete', methods=['POST'])
@login_required
@xhr_required
def api_settings_delete():
    incoming_verify = request.args.get('verify')

    if g.user.credit >= 100:
        # Allow deletion with balance less than $1.00
        raise APIError('You have some funds in your account. Please withdraw them before you can close your account')

    if incoming_verify:
        # Just check whether user can destroy his account
        return json.jsonify(dict())

    incoming = request.get_json()
    incoming_reason = incoming.get('reason')
    incoming_notes = incoming.get('notes')
    incoming_password = incoming.get('password')

    if not incoming_reason or not incoming_notes or not incoming_password:
        raise APIError('Please fill in required fields')

    if not g.user.verify_password(incoming_password):
        raise APIError('Incorrect password')

    g.user.set_meta_data('delete_reason', incoming_reason)
    g.user.set_meta_data('delete_notes', incoming_notes)

    g.user.is_deleted = True
    db.session.add(g.user)
    db.session.commit()

    email.send_account_disabled(g.user.email, g.user.username)

    # send event to Google Analytics
    # TODO: Need execute this event from browser side, is more better for traking.
    tracker = Tracker.create('UA-86740209-1')
    tracker.send('event', 'DisableAccount', g.user.username, g.user.email)  # facebook / gmail / email
    del tracker

    logout_user()

    return json.jsonify(dict())


@account.route('/api/account/settings/photo', methods=['POST'])
@login_required
def api_settings_photo_upload():
    form = ProfilePhotoAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        storage = Storage()
        photo_data = g.user.get_photo_data()
        if type(photo_data) == dict and photo_data:
            storage.delete_profile_photo(**photo_data)
            g.user.set_photo_data(None)
            db.session.add(g.user)
            db.session.commit()

        aws_key, cloudinary_key = storage.upload_profile_photo(form.photo.data, str(g.user.id), str(g.user.id))
        g.user.set_photo_data(dict(aws_key=aws_key, cloudinary_key=cloudinary_key))

        db.session.add(g.user)
        db.session.commit()

        return json.jsonify(dict(_photo_url=g.user.get_photo_url(ImagePresets.USER_PRIMARY)))
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/settings/cover', methods=['POST'])
@login_required
def api_settings_cover_upload():
    form = ProfileCoverAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        storage = Storage()
        cover_data = g.user.get_photo_data()
        if type(cover_data) == dict and cover_data:
            storage.delete_profile_cover(**cover_data)
            g.user.set_cover_data(None)
            db.session.add(g.user)
            db.session.commit()

        aws_key, cloudinary_key = storage.upload_profile_cover(form.cover.data, str(g.user.id), str(g.user.id))
        g.user.set_cover_data(dict(aws_key=aws_key, cloudinary_key=cloudinary_key))

        db.session.add(g.user)
        db.session.commit()

        return json.jsonify(dict(_photo_url=g.user.get_cover_url('w_1000,h_160,c_fill,g_center,q_95')))
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/settings/verification/calculate_score', methods=['POST'])
@login_required
@xhr_required
def api_settings_verification_calculate_score():
    connected_accounts = UserSocialAccount.query.filter_by(user_id=g.user.id).all()
    connected_accounts_set = set(map(lambda account: account.provider, connected_accounts))

    card_verified = False

    customer_id = g.user.get_meta_data('stripe_customer')

    if customer_id:
        customer = stripe.Customer.retrieve(customer_id)
        if customer:
            for item in customer['sources']['data']:
                if item['type'] == 'card' and item['status'] == 'chargeable':
                    card_verified = True

    items = list()

    items.append(dict(id='phone_number', value=10, verified=bool(g.user.phone_number_verified)))
    
    items.append(dict(id='facebook', value=10, verified=('facebook' in connected_accounts_set)))
    items.append(dict(id='google', value=10, verified=('google' in connected_accounts_set)))
    items.append(dict(id='linkedin', value=10, verified=('linkedin' in connected_accounts_set)))

    items.append(dict(id='documents', value=30, verified=False))
    items.append(dict(id='card', value=30, verified=card_verified))

    return json.jsonify(dict(
        total=sum((item['value'] for item in items if item['verified'])),
        items=items
    ))


@account.route('/api/account/balance/transactions')
@login_required
@xhr_required
def api_balance_transactions():
    incoming_limit = request.args.get('limit', 10, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)
    incoming_type = request.args.get('type', 'all')

    transactions_query = Transaction.query \
                                    .filter(Transaction.type != Transaction.ORDER_PRERELEASE) \
                                    .filter_by(user_id=g.user.id)

    if incoming_type == 'purchases':
        transactions_query = transactions_query.filter(Transaction.type.in_((Transaction.ORDER_HOLD, Transaction.ORDER_MONEYBACK, Transaction.FEE)))
    elif incoming_type == 'withdrawals':
        transactions_query = transactions_query.filter(Transaction.type == Transaction.WITHDRAWAL)

    transactions_count = transactions_query.count()
    transactions_query = transactions_query.order_by(Transaction.created_on.desc()).limit(incoming_limit).offset(incoming_offset)

    transactions_prepared = list()

    for transaction in transactions_query.all():
        transaction_prepared = transaction.to_json()
        transaction_prepared['_meta'] = transaction.get_data()
        transaction_prepared['note'] = transaction.note if transaction.type == Transaction.WITHDRAWAL else None
        transactions_prepared.append(transaction_prepared)

    return json.jsonify(
        data=transactions_prepared,
        meta=dict(
            total=transactions_count
        )
    )


@account.route('/api/account/balance/earnings')
@login_required
@seller_required
@xhr_required
def api_balance_earnings():
    incoming_limit = request.args.get('limit', 10, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)
    incoming_year = request.args.get('year', 0, type=int)
    incoming_month = request.args.get('month', 0, type=int)

    transactions_query = Transaction.query \
                                    .filter(Transaction.type.in_((Transaction.ORDER_PRERELEASE,Transaction.ORDER_RELEASE,))) \
                                    .filter_by(user_id=g.user.id)

    if incoming_year:
        transactions_query = transactions_query.filter(func.YEAR(Transaction.created_on) == incoming_year)
        if incoming_month:
            transactions_query = transactions_query.filter(func.MONTH(Transaction.created_on) == incoming_month)

    transactions_count = transactions_query.count()
    transactions_query = transactions_query.order_by(Transaction.created_on.desc()).limit(incoming_limit).offset(incoming_offset)

    transactions_prepared = list()

    for transaction in transactions_query.all():
        transaction_prepared = transaction.to_json()
        transaction_prepared['release_on'] = transaction.release_on
        if transaction.type == Transaction.ORDER_PRERELEASE and transaction.release_on:
            days = max(1, (transaction.release_on - datetime.utcnow()).days)
            transaction_prepared['_release_on_passed_percents'] = round(100 - (float(days) / app.config.get('ORDER_PENDING_CLEARANCE_DAYS')) * 100)

        transactions_prepared.append(transaction_prepared)

    return json.jsonify(
        data=transactions_prepared,
        meta=dict(
            total=transactions_count
        )
    )


@account.route('/api/account/balance/deposit/btc', methods=['POST'])
@login_required
@xhr_required
def api_balance_deposit_btc():
    address = BitcoinAddress.get_current(g.user)
    if not address:
        address = BitcoinAddress.assign(g.user)

    if not address:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))

    return json.jsonify(
        dict(address=address.address)
    )


@account.route('/api/account/balance/deposit/card/cards')
@login_required
@xhr_required
def api_balance_deposit_card_cards():
    customer_id = g.user.get_meta_data('stripe_customer')

    if not customer_id:
        return json.jsonify(list())

    customer = stripe.Customer.retrieve(customer_id)

    if not customer:
        return json.jsonify(list())

    result = list()

    for card in customer['sources']['data']:
        if not card['type'] == 'card':
            continue

        result.append(dict(
            id=card['id'],
            name='%s ****%s' % (card['card']['brand'], card['card']['last4'])
        ))

    return json.jsonify(result)


@account.route('/api/account/balance/deposit/card', methods=['POST'])
@login_required
@xhr_required
def api_balance_deposit_card():
    form = DepositCardAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        auth_card = request.args.get('auth')
        amount = 0

        if not auth_card:
            try:
                amount = long(form.amount.data * 100)
                if amount < 70:
                    raise
            except:
                raise APIError('Minimal amount is 0.70 USD')

        weekly_sum = Transaction.calculate_sum(
            Transaction.DEPOSIT_NOFEE,
            g.user,
            subtype=Transaction.SubTypes.CARD_DEPOSIT,
            period=timedelta(days=7)
        )

        if not auth_card and weekly_sum + amount > 2500:
            raise APIError('Unfortunately, you have reached your weekly limit of 25 USD')

        source_id = form.stripeSource.data
        customer_id = g.user.get_meta_data('stripe_customer')
        customer = None

        if form.stripeSource.data:
            # Using new card
            source = stripe.Source.retrieve(source_id)

            # Save new card in case we are doing authentication or user selected option to remember card
            if source['usage'] == 'reusable' and (auth_card or form.remember.data):
                if customer_id:
                    try:
                        customer = stripe.Customer.retrieve(customer_id)
                        if customer['sources'] and customer['sources']['data']:
                            source_card = source['card']
                            for item in customer['sources']['data']:
                                card = item.get('card')
                                if card and card['fingerprint'] == source_card['fingerprint'] and card['exp_month'] == source_card['exp_month'] and card['exp_year'] == source_card['exp_year']:
                                    break
                            else:
                                customer.sources.create(source=source['id'])
                    except:
                        # TODO: log into Sentry
                        pass

                if not customer:
                    try:
                        customer = stripe.Customer.create(
                            email=g.user.email,
                            source=source['id']
                        )
                        g.user.set_meta_data('stripe_customer', customer['id'])
                        db.session.add(g.user)
                        db.session.commit()
                    except:
                        # TODO: log into Sentry
                        pass
        elif form.existing.data:
            # Using existing card
            customer = stripe.Customer.retrieve(customer_id)
        else:
            # Wrong option
            raise APIError('No card selected')

        if auth_card:
            # Just return and do not create a transaction and a charge
            return json.jsonify(dict())

        description = 'Depositing funds to JobDone account by %s' % g.user.username

        charge = stripe.Charge.create(
            amount=amount,
            currency='usd',
            description=description,
            source=source_id,
            customer=customer['id'] if customer else None
        )

        if charge['status'] == 'failed':
            raise APIError('Payment failed', 500)

        if charge['status'] == 'succeeded':
            Transaction.transaction(
                type=Transaction.DEPOSIT_NOFEE,
                subtype=Transaction.SubTypes.CARD_DEPOSIT,
                amount=amount,
                user=g.user,
                note='Depositing funds to account via credit card'
            )

            return json.jsonify(dict())

        raise APIError('Payment failed', 500)

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/balance/transfer', methods=['POST'])
@login_required
@xhr_required
def api_balance_transfer():
    form = TransferFundsAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        amount = int(form.amount.data * 100)
        recipient = User.get_active_by_username(form.recipient.data)
        if not recipient:
            abort(404)

        Transaction.transfer_transaction(sender=g.user,
                                         recipient=recipient,
                                         amount=amount,
                                         note=form.note.data)


        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/balance/withdraw/btc', methods=['POST'])
@login_required
@xhr_required
def api_balance_withdraw_btc():
    form = WithdrawBTCAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        amount = long(form.amount.data * 100000000L)

        info = dict(address=form.address.data)

        Withdrawal.request_btc(user=g.user,
                               amount=amount,
                               info=info)

        # send event to Google Analytics
        # TODO: Need execute this event from browser side, is more better for traking.
        tracker = Tracker.create('UA-86740209-1')
        tracker.send('event', 'Withdraw', "bitcoin", g.user.username)
        del tracker

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/balance/withdraw/paypal', methods=['POST'])
@login_required
@xhr_required
def api_balance_withdraw_paypal():
    form = WithdrawPayPalAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        amount = long(form.amount.data * 100)

        info = dict(address=form.address.data)

        Withdrawal.request_paypal(user=g.user,
                                  amount=amount,
                                  info=info)

        # send event to Google Analytics
        # TODO: Need execute this event from browser side, is more better for traking.
        tracker = Tracker.create('UA-86740209-1')
        tracker.send('event', 'Withdraw', "paypal", g.user.username)
        del tracker

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/balance/withdraw/skrill', methods=['POST'])
@login_required
@xhr_required
def api_balance_withdraw_skrill():
    form = WithdrawSkrillAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        amount = long(form.amount.data * 100)

        info = dict(address=form.address.data)

        Withdrawal.request(user=g.user,
                           amount=amount,
                           info=info,
                           payment_system=Withdrawal.SKRILL,
                           note='Skill')

        # send event to Google Analytics
        # TODO: Need execute this event from browser side, is more better for traking.
        tracker = Tracker.create('UA-86740209-1')
        tracker.send('event', 'Withdraw', "skrill", g.user.username)
        del tracker

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/balance/withdraw/payoneer', methods=['POST'])
@login_required
@xhr_required
def api_balance_withdraw_payoneer():
    form = WithdrawPayoneerAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        amount = long(form.amount.data * 100)

        info = dict(address=form.address.data)

        Withdrawal.request(user=g.user,
                           amount=amount,
                           info=info,
                           payment_system=Withdrawal.PAYONEER,
                           note='Payoneer')

        # send event to Google Analytics
        # TODO: Need execute this event from browser side, is more better for traking.
        tracker = Tracker.create('UA-86740209-1')
        tracker.send('event', 'Withdraw', "payoneer", g.user.username)
        del tracker

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/balance/withdraw/payza', methods=['POST'])
@login_required
@xhr_required
def api_balance_withdraw_payza():
    form = WithdrawPayZaAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        amount = long(form.amount.data * 100)

        info = dict(address=form.address.data)

        Withdrawal.request(user=g.user,
                           amount=amount,
                           info=info,
                           payment_system=Withdrawal.PAYZA,
                           note='PayZa')

        # send event to Google Analytics
        # TODO: Need execute this event from browser side, is more better for traking.
        tracker = Tracker.create('UA-86740209-1')
        tracker.send('event', 'Withdraw', "payza", g.user.username)
        del tracker

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/affiliates')
@login_required
@xhr_required
def api_affiliates():
    incoming_limit = request.args.get('limit', 10, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)

    users_query = User.query \
                      .filter_by(referer_id=g.user.id) \
                      .order_by(User.registered_on.desc())

    users_count = users_query.count()
    users_query = users_query.limit(incoming_limit).offset(incoming_offset)

    users_prepared = list()

    for user in users_query.all():
        user_prepared = dict(
            id=user.id,
            username=user.username,
            registered_on=user.registered_on,
            _url=url_for('user', username=user.username),
            _photo_url=user.get_photo_url('c_fill,h_50,w_50,c_thumb,g_face')
        )
        users_prepared.append(user_prepared)

    return json.jsonify(
        data=users_prepared,
        meta=dict(
            total=users_count
        )
    )


@account.route('/api/account/affiliates/links')
@login_required
@xhr_required
def api_affiliates_links():
    incoming_limit = request.args.get('limit', 10, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)

    links_query = AffiliateLink.query \
                               .filter(AffiliateLink.is_deleted != True) \
    
    if not g.user.is_admin:
        links_query = links_query.filter(AffiliateLink.is_hidden != True) \

    links_query = links_query.order_by(AffiliateLink.created_on.desc())

    links_count = links_query.count()
    links_query = links_query.limit(incoming_limit).offset(incoming_offset)

    links_prepared = list()

    for link in links_query.all():
        link_prepared = dict(
            id=link.id,
            title=link.title,
            unique_url_id=link.unique_url_id,
            description=link.description,
            url=url_for('affiliate_link', unique_url_id=link.unique_url_id, agent=g.user.username, _external=True),
            _image_url=link.get_image_url('h_200,w_200,c_thumb,g_center')
        )
        links_prepared.append(link_prepared)

    return json.jsonify(
        data=links_prepared,
        meta=dict(
            total=links_count
        )
    )


@account.route('/api/account/affiliate_statistic')
@login_required
@xhr_required
def api_affiliate_statistic():
    date_range_local, date_range_utc = (None, None,), (None, None,)
    try:
        # TODO: cache report
        date_range_local = iso8601.parse_date(request.args.get('from')), iso8601.parse_date(request.args.get('to'))
        date_range_utc = map(get_utc_datetime, date_range_local)

        if (date_range_utc[1] - date_range_utc[0]).days > 31:
            raise

        # date_range = tuple(dt.date() for dt in date_range)
    except Exception, e:
        print e
        raise APIError('Max. allowed range is 31 days')

    cache_key = cache.SharedCache.AFFILIATE_STATISTIC % (g.user.id, date_range_utc[0].date().isoformat(), date_range_utc[1].date().isoformat())
    cached = cache.get_cached_object(cache_key)

    if not cached:
        data, meta = dict(), dict()

        impression_count_per_day, impression_count = statistic.StatisticRecord.count_per_day(
            statistic.StatisticRecord.Types.USER_AFFILIATE_IMPRESSION,
            g.user.id,
            date_range_local
        )

        impression_amount = statistic.StatisticRecord.sum(
            statistic.StatisticRecord.Types.USER_AFFILIATE_IMPRESSION,
            g.user.id,
            date_range_utc=date_range_utc
        )

        register_count_per_day, register_count = statistic.StatisticRecord.count_per_day(
            statistic.StatisticRecord.Types.USER_AFFILIATE_REGISTER,
            g.user.id,
            date_range_local
        )

        register_amount = statistic.StatisticRecord.sum(
            statistic.StatisticRecord.Types.USER_AFFILIATE_REGISTER,
            g.user.id,
            date_range_utc=date_range_utc
        )

        sale_count_per_day, sale_count = statistic.StatisticRecord.count_per_day(
            statistic.StatisticRecord.Types.USER_AFFILIATE_SALE,
            g.user.id,
            date_range_local
        )

        sale_amount = statistic.StatisticRecord.sum(
            statistic.StatisticRecord.Types.USER_AFFILIATE_SALE,
            g.user.id,
            date_range_utc=date_range_utc
        )

        # For Become Seller we don't need graph data (yet)
        become_seller_count = statistic.StatisticRecord.count(
            statistic.StatisticRecord.Types.USER_AFFILIATE_BECOME_SELLER,
            g.user.id,
            date_range_utc=date_range_utc
        )

        become_seller_amount = statistic.StatisticRecord.sum(
            statistic.StatisticRecord.Types.USER_AFFILIATE_BECOME_SELLER,
            g.user.id,
            date_range_utc=date_range_utc
        )

        amount = impression_amount + register_amount + become_seller_amount + sale_amount

        meta['impression'] = dict(value=impression_count)
        meta['register'] = dict(value=register_count)
        meta['become_seller'] = dict(value=become_seller_count)
        meta['sale'] = dict(value=sale_count)

        meta['amount'] = dict(value=float('{0:.2f}'.format(amount / 100.0)))

        data['impression'] = map(lambda day: day['count'], impression_count_per_day)
        data['register'] = map(lambda day: day['count'], register_count_per_day)
        data['sale'] = map(lambda day: day['count'], sale_count_per_day)

        cached = dict(data=data, meta=meta)
        cache.put_cached_object(cache_key, cached)

    return json.jsonify(cached)


@account.route('/api/account/favorites')
@login_required
@xhr_required
def api_favorites():
    incoming_limit = request.args.get('limit', 10, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)

    favorites_query = FavoriteProduct.query.filter_by(user_id=g.user.id).order_by(FavoriteProduct.created_on.desc())

    favorites_count = favorites_query.count()
    favorites_query = favorites_query.limit(incoming_limit).offset(incoming_offset).options(joinedload('product').load_only('title', 'primary_photo_key'))

    favorites_prepared = list()

    for favorite in favorites_query.all():
        favorite_prepared = favorite.product.to_json()

        favorite_prepared['_url'] = url_for('product', product_id=favorite.product.unique_id, product_title=favorite.product.get_title_seofied())
        favorite_prepared['_primary_photo_url'] = favorite.product.get_primary_photo('c_fill,h_156,w_263')
        favorite_prepared['_seller'] = favorite.product.seller.username

        favorites_prepared.append(favorite_prepared)

    return json.jsonify(
        data=favorites_prepared,
        meta=dict(
            total=favorites_count
        )
    )


@account.route('/api/account/favorites/searches')
@login_required
@xhr_required
def api_favorites_searches():
    incoming_limit = request.args.get('limit', 10, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)

    favorites_query = FavoriteSearch.query.filter_by(user_id=g.user.id).order_by(FavoriteSearch.created_on.desc())

    favorites_count = favorites_query.count()
    favorites_query = favorites_query.limit(incoming_limit).offset(incoming_offset)

    favorites_prepared = list()

    for favorite in favorites_query.all():
        favorite_prepared = dict()

        favorite_prepared['q'] = favorite.q
        favorite_prepared['results_count'] = favorite.results_count
        favorite_prepared['_url'] = url_for('index', query=favorite.q)

        favorites_prepared.append(favorite_prepared)

    return json.jsonify(
        data=favorites_prepared,
        meta=dict(
            total=favorites_count
        )
    )


@app.route('/account/user/photo/<username>')
@login_required
def user_photo(username):
    user = User.get_active_by_username(username)
    if not user:
        return app.send_static_file('images/1x1.png')

    photo_url = user.get_photo_url(ImagePresets.USER_PRIMARY, use_fallback=False)

    if photo_url:
        return redirect(photo_url)

    response = make_response(user.get_photo_fallback())
    response.content_type = 'image/svg+xml'

    return response


@app.route('/account/service/photo/<custom_id>')
@login_required
def service_photo(custom_id):
    service = Product.get_by_custom_id(custom_id)

    if not service and custom_id.isdigit():
        # TODO: in future, allow only custom ID to be used in this route
        service = Product.query.get(custom_id)

    if not service or service.is_deleted:
        return app.send_static_file('images/1x1.png')

    photo_url = service.get_primary_photo('h_100,w_100,c_thumb,g_center')

    if photo_url:
        return redirect(photo_url)

    return app.send_static_file('images/1x1.png')


@account.route('/account/promote-yourself.html')
@login_required
def promote_yourself():
    application_data = prepare_application_data()

    return render_template(
        'new/account/promote-yourself.html',
        application_data=application_data
    )
