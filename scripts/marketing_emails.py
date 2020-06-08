import time
from flask import url_for, render_template
from datetime import datetime, timedelta, date
from sqlalchemy import or_
from sqlalchemy.sql.functions import coalesce

from app import app, db, email
from app.models import User, Product


SEND_TIMEOUT = 2.5


class SellerTypes:
    DAY1 = 'DAY1'
    DAY2 = 'DAY2'


def send_sellers():
    users_query = User.query.filter(
        coalesce(User.is_deleted, False) != True,
        coalesce(User.is_disabled, False) != True,
        User.seller_fee_paid == True,
        User.is_verified == True,
        User.registered_on > datetime.now() - timedelta(days=8)
    )

    counts = dict()

    for user in users_query:
        days = (datetime.now() - user.registered_on).days
        sent_emails_dict = user.get_meta_data('marketing_emails') or dict()
        disabled_subscriptions = user.get_meta_data('disabled_subscriptions') or dict()
        sent = None

        if 'new_users' in disabled_subscriptions:
            continue

        if days == 1 and SellerTypes.DAY1 not in sent_emails_dict:
            send_sellers_day1(user)
            counts[SellerTypes.DAY1] = counts.setdefault(SellerTypes.DAY1, 0) + 1

            sent_emails_dict[SellerTypes.DAY1] = 1
            sent = SellerTypes.DAY1
        elif days == 2 and SellerTypes.DAY2 not in sent_emails_dict:
            send_sellers_day2(user)
            counts[SellerTypes.DAY2] = counts.setdefault(SellerTypes.DAY2, 0) + 1

            sent_emails_dict[SellerTypes.DAY2] = 1
            sent = SellerTypes.DAY2

        if sent:
            print "Sent %s to %s" % (sent, user.email)
            user.set_meta_data('marketing_emails', sent_emails_dict)
            db.session.add(user)
            db.session.commit()

            # Do a timeout
            time.sleep(SEND_TIMEOUT)

    print
    print "Statistics:"
    for k in counts:
        print "%10s: %d" % (k, counts[k])


def send_sellers_day1(user):
    subject = 'Complete your profile and become PRO seller'
    args = dict(
        title=subject,
        username=user.username,
        link_add_service=url_for('account.service_create', _external=True),
        link_profile=url_for('user', username=user.username, _external=True),
        link_endorse=url_for('user_endorse', username=user.username, _external=True),
        link_unsubscribe=url_for('unsubscribe_settings', uuid=user.get_uuid(), _external=True)
    )

    email.send_sync_silent(
        subject,
        user.email,
        '',
        render_template('email/marketing/seller_day1.html', **args),
        server='secondary',
        reply=app.config.get('REPLY_TO_EMAIL')
    )


def send_sellers_day2(user):
    subject = 'Get your first orders in next 24 hours'

    utm_args = dict(
        utm_source='newsletter',
        utm_medium='funnelsellers',
        utm_campaign='day2',
        utm_term='buybutton'
    )

    link_buy_feature = None

    service = user.products.filter(
        Product.is_deleted != True,
        Product.published_on != None
    ).first()

    if service:
        link_buy_feature = '%s#?tab=4' % url_for('account.service_edit', unique_id=service.get_custom_id(), _external=True, **utm_args)

    args = dict(
        title=subject,
        username=user.username,
        link_buy_feature=link_buy_feature,
        link_unsubscribe=url_for('unsubscribe_settings', uuid=user.get_uuid(), _external=True)
    )

    email.send_sync_silent(
        subject,
        user.email,
        '',
        render_template('email/marketing/seller_day2.html', **args),
        server='secondary',
        reply=app.config.get('REPLY_TO_EMAIL')
    )
