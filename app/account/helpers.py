from flask import g, url_for
from datetime import timedelta

from app import app
from app.models import Category, calculate_order_fee
from app.messaging import NotificationTypes


def prepare_application_data():
    application_data = dict()

    ## Routes

    application_data['urls'] = dict(
        buyer_order=url_for('account.buyer_order', order_id='ARG0'),
        seller_order=url_for('account.seller_order', order_id='ARG0'),
        order=url_for('account.order', order_id='ARG0'),
        order_buyer_attachment=url_for('account.api_buyer_attachments_download', attachment_id='ARG0', filename='ARG1'),
        order_seller_attachment=url_for('account.api_seller_attachments_download', attachment_id='ARG0', filename='ARG1'),
        inbox='%s#?type=ARG0&id=ARG1' % url_for('account.inbox'),
        affiliate_link_share=url_for('affiliate_link_share', unique_url_id='ARG0', platform='ARG1'),
    )

    ## Config

    application_data['config'] = dict(
        messaging=dict(
            server=app.config.get('MESSAGING_SERVER_URI') + '/ws',
            notificationTypes={ k: getattr(NotificationTypes, k) for k in vars(NotificationTypes) if not k.startswith('__') and not callable(getattr(NotificationTypes, k)) }
        )
    )

    if not app.config['DEVELOPMENT'] and not app.config['LOCAL_DEVELOPMENT']:
        sentry_dsn_client = app.config.get('SENTRY_DSN_CLIENT')
        if sentry_dsn_client:
            application_data['config']['sentry'] = dict(dsn=sentry_dsn_client)

    ## User info

    user_prepared = g.user.to_json() if g.user.is_authenticated else None
    application_data['user'] = user_prepared

    return application_data


def prepare_category_tree():
    categories_all = Category.query_active().all()
    categories_top = list()
    categories_top_dict = dict()

    for category in categories_all:
        if category.parent_id is None:
            categories_top.append(dict(id=category.id, title=category.title))
            continue

        categories_top_dict.setdefault(category.parent_id, []).append(dict(
            id=category.id,
            title=category.title
        ))

    for category in categories_top:
        category['subcategories'] = categories_top_dict.get(category['id'], [])
        
    return categories_top


def prepare_order_summary(order, include_fee=False):
    summary = list()
    summary.append(dict(
        title='I will %s' % order.product.title,
        quantity=1,
        duration=order.delivery_time if order.delivery_time else order.product.delivery_time,
        price=order.price
    ))

    extras = order.get_data('extras') or []
    extras_price = 0
    for extra in extras:
        summary.append(dict(title=extra['text'], price=extra['price'], quantity=1))
        extras_price += extra['price']

    if extras_price:
        # Correct item price
        summary[0]['price'] -= extras_price

    fee = 0

    order_offers = order.get_data('order_offers') or []
    order_offers_price = 0
    for order_offer in order_offers:
        summary.append(dict(
            title=", ".join([extra['text'] for extra in (order_offer['extras'] or [])]),
            price=order_offer['price'],
            quantity=1,
            duration=timedelta(days=order_offer['delivery_time'])
        ))

        order_offers_price += order_offer['price']

        if include_fee:
            fee += order_offer['fee']

    if include_fee:
        fee += (order.get_data('fee') or calculate_order_fee(order.price))
        summary.append(dict(title='Processing fee', price=fee))

    total = order.price + order_offers_price + fee

    return summary, total
