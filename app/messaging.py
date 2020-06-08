import requests

from app import app

CONNECTION_TIMEOUT = 5


class NotificationTypes:
    SELLER_NEW_ORDER = 'seller_new_order'
    BUYER_ORDER_ACCEPTED = 'buyer_order_accepted'
    BUYER_ORDER_REVISION = 'buyer_order_revision'
    BUYER_ORDER_COMPLETED = 'buyer_order_completed'
    BUYER_ORDER_REJECTED = 'buyer_order_rejected'
    BUYER_ORDER_SENT = 'buyer_order_sent'
    BUYER_ORDER_DISPUTE = 'buyer_order_dispute'
    BUYER_ORDER_OFFER = 'buyer_order_offer'
    BUYER_ENQUIRY_OFFER = 'buyer_enquiry_offer'
    SELLER_ORDER_COMPLETED = 'seller_order_completed'
    SELLER_ORDER_CANCELLED = 'seller_order_cancelled'
    SELLER_ORDER_DISPUTE = 'seller_order_dispute'
    NEW_MESSAGE = 'new_message'


class MessageTypes:
    NEW_ORDER = 'new_order'
    ORDER_ACCEPTED = 'order_accepted'
    ORDER_SENT = 'order_sent'
    ORDER_REVISION = 'order_revision'
    ORDER_REJECTED = 'order_rejected'
    ORDER_CANCELLED = 'order_cancelled'
    ORDER_COMPLETED = 'order_completed'
    ORDER_DISPUTE = 'order_dispute'
    ORDER_OFFER = 'order_offer'
    ENQUIRY_OFFER = 'enquiry_offer'


def isoformat(dt):
    return dt.isoformat() + 'Z'


def auth(user, auth_data):
    data = dict(userID=user.id)
    body = dict(cid=auth_data['cid'], token=auth_data['token'], data=data)

    do_request('/api/private/connection/auth', body)


def new_enquiry(enquiry, buyer, seller, text, service=None, attachments=None):
    meta = dict(
        buyer=dict(id=buyer.id, username=buyer.username),
        seller=dict(id=seller.id, username=seller.username)
    )

    if service:
        meta['service'] = dict(id=service.id, title=service.title)

    message_body = dict(text=text)
    message_meta = dict(room=meta)

    if attachments:
        message_meta['message'] = dict(attachments=attachments)

    body = [
        dict(users=[buyer.id, seller.id], enquiryID=enquiry.id, userID=buyer.id, body=message_body, meta=message_meta)
    ]

    do_request('/api/private/message/enquiry', body)


def handle_new_order(buyer, seller, order, service):
    meta = dict(
        order=dict(id=order.id, price=order.price),
        service=dict(id=service.id, title=service.title),
        buyer=dict(id=order.buyer.id, username=order.buyer.username),
        seller=dict(id=order.product.seller.id, username=order.product.seller.username)
    )

    body = dict(type=NotificationTypes.SELLER_NEW_ORDER, userID=seller.id, meta=meta)

    do_request('/api/private/notification', body)

    body = [
        dict(type=MessageTypes.NEW_ORDER, users=[buyer.id, seller.id], orderID=order.id, userID=order.buyer.id,
             meta=dict(room=meta))
    ]

    do_request('/api/private/message/order', body)


def handle_order_accepted(order):
    meta = dict(
        order=dict(id=order.id, price=order.price),
        service=dict(id=order.product.id, title=order.product.title),
        seller=dict(id=order.product.seller.id, username=order.product.seller.username),
        buyer=dict(id=order.buyer.id, username=order.buyer.username)
    )

    body = dict(type=NotificationTypes.BUYER_ORDER_ACCEPTED, userID=order.buyer_id, meta=meta)

    do_request('/api/private/notification', body)

    body = [
        dict(type=MessageTypes.ORDER_ACCEPTED, orderID=order.id, userID=order.product.seller.id)
    ]

    do_request('/api/private/message/order', body)


def handle_order_revision(order, description, attachments):
    meta = dict(
        order=dict(id=order.id, price=order.price),
        service=dict(id=order.product.id, title=order.product.title),
        seller=dict(id=order.product.seller.id, username=order.product.seller.username),
        buyer=dict(id=order.buyer.id, username=order.buyer.username),
    )

    body = dict(type=NotificationTypes.BUYER_ORDER_REVISION,
                userID=order.product.seller.id,
                meta=meta)

    do_request('/api/private/notification', body)

    body = [
        dict(
            type=MessageTypes.ORDER_REVISION,
            orderID=order.id,
            userID=order.product.seller.id,
            meta=dict(
                message=dict(
                    text=description,
                    attachments=attachments
                )
            )
        )
    ]

    do_request('/api/private/message/order', body)


def handle_order_rejected(order, note=None):
    meta = dict(
        order=dict(id=order.id, price=order.price),
        service=dict(id=order.product.id, title=order.product.title),
        seller=dict(id=order.product.seller.id, username=order.product.seller.username),
        buyer=dict(id=order.buyer.id, username=order.buyer.username)
    )

    body = dict(type=NotificationTypes.BUYER_ORDER_REJECTED, userID=order.buyer_id, meta=meta)

    do_request('/api/private/notification', body)

    body = [
        dict(type=MessageTypes.ORDER_REJECTED, orderID=order.id, userID=order.product.seller.id)
    ]

    if note:
        # Attach message which seller left
        body[0]['text'] = note

    do_request('/api/private/message/order', body)


def handle_order_cancelled(order, initiator):
    meta = dict(
        order=dict(id=order.id, price=order.price),
        service=dict(id=order.product.id, title=order.product.title),
        seller=dict(id=order.product.seller.id, username=order.product.seller.username),
        buyer=dict(id=order.buyer.id, username=order.buyer.username),
        initiator=dict(id=initiator.id, username=initiator.username)
    )

    body = dict(type=NotificationTypes.SELLER_ORDER_CANCELLED, userID=order.product.seller.id, meta=meta)

    do_request('/api/private/notification', body)

    body = [
        dict(type=MessageTypes.ORDER_CANCELLED, orderID=order.id, userID=initiator.id,
             meta=dict(message=dict(initiator=meta['initiator'])))
    ]

    do_request('/api/private/message/order', body)


def handle_order_sent(order, deliverable):
    meta = dict(
        order=dict(id=order.id, price=order.price),
        service=dict(id=order.product.id, title=order.product.title),
        seller=dict(id=order.product.seller.id, username=order.product.seller.username),
        buyer=dict(id=order.buyer.id, username=order.buyer.username),
        deliverable=dict(id=deliverable.id)
    )

    body = [
        dict(type=NotificationTypes.BUYER_ORDER_SENT, userID=order.buyer_id, meta=meta),
    ]

    do_request('/api/private/notification', body)

    message_meta = dict(deliverable=dict(id=deliverable.id, text=deliverable.text, files=deliverable.get_data('files')))

    body = [
        dict(type=MessageTypes.ORDER_SENT, orderID=order.id, userID=order.product.seller.id,
             meta=dict(message=message_meta))
    ]

    do_request('/api/private/message/order', body)


def handle_enquiry_offer(enquiry, service, buyer, enquiry_offer):
    meta = dict(
        service=dict(id=service.id, title=service.title),
        seller=dict(id=service.seller.id, username=service.seller.username),
        buyer=dict(id=buyer.id, username=buyer.username),
        enquiry_offer=dict(id=enquiry_offer.id),
        enquiry=dict(id=enquiry.id)
    )

    body = [
        dict(type=NotificationTypes.BUYER_ENQUIRY_OFFER, userID=buyer.id, meta=meta),
    ]

    do_request('/api/private/notification', body)

    message_meta = dict(
        enquiry_offer=dict(
            id=enquiry_offer.id,
            price=enquiry_offer.price,
            delivery_time=enquiry_offer.delivery_time.days,
            revision_count=enquiry_offer.revision_count,
            expired_on=isoformat(enquiry_offer.expired_on) if enquiry_offer.expired_on else None,
            _service_title=service.title,
            _service_id=service.get_custom_id()
        )
    )

    body = [
        dict(
            type=MessageTypes.ENQUIRY_OFFER,
            enquiryID=enquiry.id,
            userID=service.seller.id,
            body=dict(text=enquiry_offer.text),
            meta=dict(message=message_meta)
        )
    ]

    do_request('/api/private/message/enquiry', body)


def handle_order_offer(order, order_offer, attachments):
    meta = dict(
        order=dict(id=order.id, price=order.price),
        service=dict(id=order.product.id, title=order.product.title),
        seller=dict(id=order.product.seller.id, username=order.product.seller.username),
        buyer=dict(id=order.buyer.id, username=order.buyer.username),
        order_offer=dict(id=order_offer.id)
    )

    body = [
        dict(type=NotificationTypes.BUYER_ORDER_OFFER, userID=order.buyer_id, meta=meta),
    ]

    do_request('/api/private/notification', body)

    message_meta = dict(
        order_offer=dict(
            id=order_offer.id,
            text=order_offer.text,
            price=order_offer.price,
            extras=order_offer.get_extras(),
            delivery_time=order_offer.delivery_time.days
        ),
        attachments=attachments
    )

    body = [
        dict(
            type=MessageTypes.ORDER_OFFER,
            orderID=order.id,
            userID=order.product.seller.id,
            meta=dict(message=message_meta)
        )
    ]

    do_request('/api/private/message/order', body)


def handle_order_dispute_by_buyer(order):
    meta = dict(
        order=dict(id=order.id, price=order.price),
        service=dict(id=order.product.id, title=order.product.title),
        seller=dict(id=order.product.seller.id, username=order.product.seller.username),
        buyer=dict(id=order.buyer.id, username=order.buyer.username)
    )

    body = [
        dict(type=NotificationTypes.SELLER_ORDER_DISPUTE, userID=order.product.seller.id, meta=meta),
    ]

    do_request('/api/private/notification', body)

    body = [
        dict(type=MessageTypes.ORDER_DISPUTE, orderID=order.id, userID=order.buyer.id)
    ]

    do_request('/api/private/message/order', body)


def handle_order_dispute_by_seller(order):
    meta = dict(
        order=dict(id=order.id, price=order.price),
        service=dict(id=order.product.id, title=order.product.title),
        seller=dict(id=order.product.seller.id, username=order.product.seller.username),
        buyer=dict(id=order.buyer.id, username=order.buyer.username)
    )

    body = [
        dict(type=NotificationTypes.BUYER_ORDER_DISPUTE, userID=order.buyer.id, meta=meta),
    ]

    do_request('/api/private/notification', body)

    body = [
        dict(type=MessageTypes.ORDER_DISPUTE, orderID=order.id, userID=order.product.seller.id)
    ]

    do_request('/api/private/message/order', body)


def handle_order_completed(order):
    meta = dict(
        order=dict(id=order.id, price=order.price),
        service=dict(id=order.product.id, title=order.product.title),
        seller=dict(id=order.product.seller.id, username=order.product.seller.username),
        buyer=dict(id=order.buyer.id, username=order.buyer.username)
    )

    body = [
        dict(type=NotificationTypes.BUYER_ORDER_COMPLETED, userID=order.buyer_id, meta=meta),
        dict(type=NotificationTypes.SELLER_ORDER_COMPLETED, userID=order.product.seller.id, meta=meta)
    ]

    do_request('/api/private/notification', body)

    body = [
        dict(type=MessageTypes.ORDER_COMPLETED, orderID=order.id, userID=order.buyer.id)
    ]

    do_request('/api/private/message/order', body)


def handle_order_deliverable_vote(order, deliverable):
    body = dict(
        orderID=order.id,
        deliverableID=deliverable.id,
        rating=deliverable.rating
    )

    do_request('/api/private/order/deliverable_vote', body)


def handle_order_offer_update(order, order_offer):
    body = dict(
        orderID=order.id,
        orderOfferID=order_offer.id,
        is_closed=order_offer.is_closed,
        is_accepted=order_offer.is_accepted
    )

    print do_request('/api/private/order/offer_update', body)


def handle_enquiry_offer_update(enquiry_offer):
    body = dict(
        enquiryID=enquiry_offer.enquiry_id,
        enquiryOfferID=enquiry_offer.id,
        is_closed=enquiry_offer.is_closed,
        is_accepted=enquiry_offer.is_accepted
    )

    print do_request('/api/private/enquiry/offer_update', body)


def check_unread_messages():
    """
    This is internal function which will retrieve users which have unread messages send 1+ hour ago
    Used by the periodic script
    """

    result = do_request('/api/private/participants/unread_messages', dict())

    if 'participants' not in result or type(result['participants']) != list:
        return list()

    return result['participants']


def do_request(url, body):
    r = requests.post('{0}{1}'.format(app.config.get('MESSAGING_SERVER_URI'), url), json=body, timeout=5)
    return r.json()
