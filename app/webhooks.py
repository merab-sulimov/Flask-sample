import os
import stripe
from flask import request, json, abort

from app import app
from app.models import Order, Transaction
from utils.storage import Storage


@app.route('/webhooks/video/convert', methods=['POST'])
def webhooks_video_convert():
    incoming = request.get_json()

    for asset in incoming:
        if 'url' in asset:
            url = asset['url']
            break
    else:
        # URL not found, ignore this call
        return json.jsonify(dict())

    key = os.path.splitext(url.split('/')[-1])[0]

    storage = Storage()
    storage.upload_product_video_callback(key)

    return json.jsonify(dict())


@app.route('/webhooks/stripe', methods=['POST'])
def webhooks_stripe():
    payload = request.data
    sig_header = request.headers.get('stripe-signature')
    event = None

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, app.config['STRIPE_WEBHOOK_SECRET_KEY'])
    except Exception as e:
        abort(400)

    if event['type'] in ('source.canceled', 'source.failed',):
        order = Order.query.filter_by(stripe_source=event['data']['object']['id']).first()
        if not order or not order.is_pending:
            abort(403)

        order.cancel_pending(note='Payment failed and order couldn\'t be processed')
        return json.jsonify(dict())

    if event['type'] == 'source.chargeable':
        order = Order.query.filter_by(stripe_source=event['data']['object']['id']).first()
        if not order or not order.is_pending:
            return json.jsonify(dict())

        order_fee = order.get_data('fee') or 0

        charge = stripe.Charge.create(
            amount=order.price + order_fee,
            currency='usd',
            description=order.product.title,
            source=event['data']['object']['id']
        )

        if charge['status'] == 'failed':
            order.cancel_pending(note='Payment failed and order couldn\'t be processed')
            return json.jsonify(dict())

        if charge['status'] == 'succeeded':
            Transaction.transaction(
                type=Transaction.DEPOSIT_NOFEE,
                amount=order.price + order_fee,
                user=order.buyer,
                note='Payment by credit card for product "%s" (%s)' % (order.product.title, order.product.get_custom_id())
            )

            order.confirm_pending()
            return json.jsonify(dict())

    return json.jsonify(dict())
