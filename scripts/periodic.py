from flask import url_for
from datetime import datetime, timedelta, date
from sqlalchemy import or_
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import bindparam
from sqlalchemy.orm import joinedload

from app import app, db, search, messaging, email, cache
from app.utils import slack
from app.models import User, Variable, BitcoinAddress, Transaction, Order, OrderHistory, Category, Product, Dispute, \
    FavoriteSearch, ProductOffer, UserInvitation, isoparse, EnquiryOffer


def check_enquiry_offers_expiration():
    print "Checking Enquire Offers Expiration"

    updated = db.session.query(EnquiryOffer) \
        .filter(EnquiryOffer.expired_on < datetime.utcnow(),
                EnquiryOffer.is_closed == False,
                EnquiryOffer.is_accepted == False) \
        .update({EnquiryOffer.is_closed: True})

    print 'Updated %s items' % updated


def check_orders():
    print "Checking NEW orders with failed accept deadline"

    deadline = app.config['ORDER_ACCEPT_DEADLINE']

    print "Order accept deadline is set to %d seconds" % deadline

    orders = Order.query.filter(
        Order.state == Order.NEW,
        Order.created_on < datetime.utcnow() - timedelta(seconds=deadline)
    ).all()

    for order in orders:
        print "Accept deadline is passed for order #%d" % order.id
        # order.change_state(Order.CLOSED_CANCELLED, order.buyer)
        # TODO: send email?

    print "Checking ACCEPTED orders with almost failed deadline (1 day)"

    orders = Order.query.filter(
        Order.state == Order.ACCEPTED,
        Order.delivery_on < datetime.utcnow() + timedelta(days=1),
        Order.delivery_time > timedelta(days=1),
        or_(Order.delivery_notification_sent.is_(None), Order.delivery_notification_sent == False)
    ).all()

    for order in orders:
        print "Delivery deadline is about to fail for order #%d" % order.id
        email.send_seller_deadline_notification(order.product.seller.email, order)

        try:
            order.delivery_notification_sent = True
            db.session.add(order)
            db.session.commit()
        except:
            pass

    print "Checking ACCEPTED orders with failed deadline"

    orders = Order.query.filter(
        Order.state == Order.ACCEPTED,
        Order.delivery_on < datetime.utcnow(),
        or_(Order.delivery_notification_sent_buyer.is_(None), Order.delivery_notification_sent_buyer == False)
    ).all()

    for order in orders:
        print "Delivery deadline is passed for order #%d" % order.id
        email.send_buyer_deadline(order.buyer.email, order)
        
        try:
            order.delivery_notification_sent_buyer = True
            db.session.add(order)
            db.session.commit()
        except:
            pass

    print "Checking SENT orders with failed review deadline"

    deadline = app.config['ORDER_SENT_DEADLINE']

    orders = Order.query.filter(
        Order.state == Order.SENT,
        Order.delivered_on.isnot(None),
        Order.delivered_on < datetime.utcnow() - timedelta(seconds=deadline)
    ).all()

    for order in orders:
        print "Sent deadline is passed for order #%d" % order.id
        
        try:
            order.change_state(Order.CLOSED_COMPLETED, order.buyer)
        except:
            pass


def check_offers():
    print "Setting active offers on products"
    offers = ProductOffer.query.filter(ProductOffer.start_date <= date.today()) \
                               .filter(ProductOffer.end_date >= date.today()) \
                               .filter(Product.id == ProductOffer.product_id) \
                               .filter(Product.active_offer_id == None)

    for offer in offers:
        product = offer.get_product()
        product.set_active_offer(offer)
        search.add_product_to_index(product)

    products = Product.query.filter(Product.active_offer_id != None) \
                            .filter(ProductOffer.id == Product.active_offer_id) \
                            .filter(ProductOffer.end_date < date.today())

    for product in products:
        product.set_active_offer(None)
        search.add_product_to_index(product)


def check_pending_transactions():
    print "Checking transactions that passed clearance period"

    transactions = Transaction.query \
                              .filter(Transaction.type == Transaction.ORDER_PRERELEASE) \
                              .filter(Transaction.is_hold == True) \
                              .filter(Transaction.release_on < datetime.utcnow())
        
    for transaction in transactions:
        try:
            transaction.release()
            print "Released transaction #%d for user #%d" % (transaction.id, transaction.user_id)
        except:
            pass


def update_exchange_rate():
    from scripts import blockchain

    try:
        rate = blockchain.request_exchange_rate()
        print "Received last exchange rate: %.2f" % rate

    except:
        # TODO: report this incident
        print "Unable to get last exchange rate"

        rate = None
        var = Variable.query.get('exchange_rate')

        if var:
            delta = datetime.utcnow() - var.set_on
            if delta.seconds < app.config['EXCHANGE_RATE_EXPIRATION']:
                # Previous rate has not yet expired
                rate = var.value

    # Set exchange rate to None if the site couldn't get the exchange rate
    Variable.set('exchange_rate', unicode(rate) if rate else None)

    if rate is None:
        raise Exception('Unable to update exchange rate')


def check_addresses():
    rate = Variable.get_exchange_rate()
    if not rate:
        print 'Exchange rate is not available. Exiting'
        return

    print 'Checking how many free addresses are available...'

    count = BitcoinAddress.query.filter(BitcoinAddress.user_id==None).count()

    if count < 10:
        alert = 'There are only %d unassigned BTC addresses left' % count
        if not slack.notification(alert, icon=slack.Icons.DANGER):
            email.send_alert(alert)

    from scripts import blockchain

    addresses = BitcoinAddress.query.filter(
        BitcoinAddress.is_amount_confirmed == False,
        BitcoinAddress.user_id != None,
        BitcoinAddress.touched_on > datetime.utcnow() - timedelta(days=5)
    ).all()

    for address in addresses:
        print 'Checking %s...' % address.address,
        try:
            confirmed_balance, unconfirmed_balance = blockchain.address_balance(address.address)

            if confirmed_balance < unconfirmed_balance:
                address.amount = unconfirmed_balance
                address.is_current = False
                address.is_amount_confirmed = False
                db.session.add(address)
                db.session.commit()

            elif confirmed_balance > 0 and confirmed_balance == unconfirmed_balance:
                # We have a confirmation
                address.amount = confirmed_balance
                address.is_amount_confirmed = True
                address.is_current = False
                db.session.add(address)

                amount_usd = int(rate * confirmed_balance * 100)

                Transaction.transaction(type=Transaction.DEPOSIT, amount=amount_usd, user=address.user)
                db.session.commit()

            print "OK. Balance: %.8f, unconfirmed: %.8f" % (confirmed_balance / 100000000.0, unconfirmed_balance / 100000000.0)
        except Exception:
            # TODO: report this incident
            print "ERROR"
            continue


def generate_sitemap():
    import os
    from flask import render_template

    categories = Category.query_active()
    products = Product.query_active().order_by(Product.created_on.desc())
    users = User.query

    xml = render_template('sitemap.xml', categories=categories, products=products, users=users)

    dest_filename = os.path.join(app.config['STATIC_FOLDER'], 'sitemap.xml')
    dest = open(dest_filename, 'w+')
    dest.write(xml)
    dest.close()
    print "Sitemap has been saved to {0}".format(dest_filename)


def update_favorite_searches():
    for favorite_search in FavoriteSearch.query.all():
        count = search.count_search_products(q=favorite_search.q, since=favorite_search.updated_on)
        favorite_search.results_count = count
        db.session.add(favorite_search)
        db.session.commit()


def check_unread_messages():
    participants = messaging.check_unread_messages()

    for participant in participants:
        sender = User.query.get(participant['sender_id'])
        recipient = User.query.get(participant['recipient_id'])

        if not sender or not recipient or sender == recipient:
            continue

        link = None

        if participant['type'] == 'enquiry':
            link = url_for('account.inbox', type=participant['type'], id=participant['entity_id'], _external=True)
        elif participant['type'] == 'order':
            link = url_for('account.order', order_id=participant['entity_id'], _external=True)

        email.send_new_message(recipient, sender, participant['count'], link)


def check_invites():
    invitations_query = UserInvitation.query \
        .filter(UserInvitation.state == UserInvitation.PENDING) \
        .options(joinedload('user').load_only('username'))
    
    while True:
        invitation = invitations_query.first()
        if not invitation:
            break

        email.send_invitation(invitation.email, invitation.user, invitation.uuid)

        invitation.state = UserInvitation.SENT
        invitation.sent_on = datetime.utcnow()
        db.session.add(invitation)
        db.session.commit()


def fake_update_users_time():
    VARIABLE_NAME = 'fake_users_time_updated'

    if cache.search_token(VARIABLE_NAME, cache.TokenType.VARIABLE, destroy_token=False):
        # Do not run task this time, wait for timer to expire
        print 'Waiting for 48h timer to expire to run this task again'
        # return
        pass

    User.query \
        .filter(User.last_logged_on < datetime.utcnow() - timedelta(seconds=3600*3)) \
        .update(dict(
            last_logged_on=func.from_unixtime(
                func.unix_timestamp() - func.floor(0 + (func.rand() * 3600*72))
            )
        ), synchronize_session=False)

    User.query \
        .update(dict(
            fake_response_time=func.floor(60 + (func.rand() * 3600*3))
        ), synchronize_session=False)

    db.session.commit()

    cache.add_token(VARIABLE_NAME, cache.TokenType.VARIABLE, 1, expire=3600*48)


def check_product_features():
    products = Product.query.filter(
        Product.is_deleted!=True,
        Product.features_json!=None
    ).all()

    for product in products:
        features_modified = 0
        try:
            for feature in product.get_features():
                if isoparse(feature['end_date']) <= datetime.utcnow():
                    product.remove_feature(feature)
                    search.add_product_to_index(product)
                    features_modified += 1

            if features_modified:
                db.session.add(product)
                db.session.commit()
        except:
            pass
