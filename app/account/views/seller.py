from flask import url_for, redirect, render_template, json, request, g, abort
from flask_login import login_required
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func
from sqlalchemy.sql.functions import coalesce
from datetime import date, datetime, timedelta

from app import db, search, app, messaging
from app.decorators import xhr_required, seller_required
from app.models import User, Order, OrderOffer, Product, Discount, ProductOffer, Feedback, Tag, Dispute, Deliverable, Enquiry, EnquiryOffer, calculate_order_fee, isoformat
from app.helpers import APIError, timedelta_pretty_print
from app.utils.storage import Storage
from app.utils.tz import get_local_datetime
from .. import account
from ..forms import NewDiscountAPIForm, NewOfferAPIForm, EditOfferAPIForm, CustomOfferAPIForm, ServiceOfferAPIForm, DisputeAPIForm, DeliverAPIForm
from ..helpers import prepare_application_data, prepare_order_summary


SERVICES_TYPE_MAPPING = {
    'active': (Product.is_approved == True, Product.published_on != None),
    'drafts': (Product.is_approved != True, Product.published_on == None), # TODO: extra flag for not approved
    'pending': (Product.is_approved != True, Product.published_on != None, Product.not_approved != True),
    'not_approved': (Product.is_approved != True, Product.published_on != None, Product.not_approved == True), # TODO: extra flag for not approved
    'not_published': (Product.is_approved == True, Product.published_on == None),
    'deleted': (Product.is_deleted == True,),
}

ORDERS_STATE_MAPPING = {
    'new': (Order.NEW,),
    'active': (Order.ACCEPTED, Order.SENT,),
    'needs_action': (Order.DISPUTE,),
    'needs_review': (Order.CLOSED_COMPLETED,),
    'completed': (Order.CLOSED_COMPLETED,),
    'cancelled': (Order.CLOSED_CANCELLED, Order.CLOSED_REJECTED,)
}


@account.route('/account/seller')
@login_required
@seller_required
def seller():
    tab_counts = dict()
    for tab, states in ORDERS_STATE_MAPPING.iteritems():
        query = Order.query \
                     .join(Product) \
                     .filter(Order.state.in_(states)) \
                     .filter(coalesce(Order.is_pending, False) != True) \
                     .filter(Product.seller_id == g.user.id)

        if tab == 'needs_review':
            query = query.outerjoin(Feedback, and_(Feedback.order_id == Order.id, Feedback.type == Feedback.ON_BUYER)) \
                         .group_by(Order) \
                         .having(func.count(Feedback.id) == 0)

        tab_counts[tab] = query.count()

    return render_template('new/account/seller.html', application_data=prepare_application_data(), tab_counts=tab_counts)


@account.route('/account/seller/services')
@login_required
@seller_required
def services():
    tab_counts = dict()
    for tab, query in SERVICES_TYPE_MAPPING.iteritems():
        services_query = Product.query.filter(Product.seller_id == g.user.id)

        if tab != 'deleted':
            services_query = services_query.filter(Product.is_deleted != True)

        services_query = services_query.filter(*query)

        tab_counts[tab] = services_query.count()

    return render_template('new/account/seller-services.html', application_data=prepare_application_data(), tab_counts=tab_counts)


@account.route('/account/seller/orders/<order_id>/verification')
@login_required
def seller_order_verification(order_id):
    if not order_id.isdigit():
        abort(404)
    
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    if not order.is_pending_verification:
        return redirect(url_for('account.seller_order', order_id=order_id))
    
    summary, total = prepare_order_summary(order)

    application_data = prepare_application_data()
    
    order_prepared = order.to_json()

    order_buyer_prepared = order.buyer.to_json()
    order_buyer_prepared['_photo_url'] = order.buyer.get_photo_url('h_80,w_80,c_thumb,g_face')

    order_seller_prepared = order.product.seller.to_json()
    order_seller_prepared['_photo_url'] = order.product.seller.get_photo_url('h_80,w_80,c_thumb,g_face')

    application_data['extra'] = dict(
        mode='seller',
        order=order_prepared,
        service=order.product.to_json(),
        buyer=order_buyer_prepared,
        seller=order_seller_prepared
    )

    return render_template('new/account/order-verification.html',
        application_data=application_data,
        mode='seller',
        summary=summary,
        total=total,
        order=order
    )


# @account.route('/account/seller/orders/<order_id>/review')
# @login_required
# def seller_order_review(order_id):
#     if not order_id.isdigit():
#         abort(404)
    
#     order = Order.query.get_or_404(order_id)
#     if order.product.seller_id != g.user.id:
#         abort(403)

#     if order.state != Order.CLOSED_COMPLETED or order.get_buyer_feedback():
#         # Order is not CLOSED_COMPLETED or already has a feedback
#         return redirect(url_for('account.seller_order', order_id=order_id))

#     application_data = prepare_application_data()
    
#     order_prepared = order.to_json()

#     order_buyer_prepared = order.buyer.to_json()
#     order_buyer_prepared['_photo_url'] = order.buyer.get_photo_url('h_80,w_80,c_thumb,g_face')

#     order_seller_prepared = order.product.seller.to_json()
#     order_seller_prepared['_photo_url'] = order.product.seller.get_photo_url('h_80,w_80,c_thumb,g_face')

#     application_data['extra'] = dict(
#         mode='seller',
#         order=order_prepared,
#         service=order.product.to_json(),
#         buyer=order_buyer_prepared,
#         seller=order_seller_prepared
#     )

#     return render_template('new/account/order-review.html',
#         application_data=application_data,
#         mode='seller',
#         order=order
#     )


@account.route('/account/seller/orders/<order_id>/resolution')
@login_required
def seller_order_resolution(order_id):
    if not order_id.isdigit():
        abort(404)

    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    if order.state not in (Order.NEW, Order.ACCEPTED, Order.SENT):
        return redirect(url_for('account.buyer_order', order_id=order_id))

    application_data = prepare_application_data()

    order_prepared = order.to_json()
    order_prepared['_state_pretty_print'] = order.get_state_pretty_print()

    order_buyer_prepared = order.buyer.to_json()
    order_buyer_prepared['_photo_url'] = order.buyer.get_photo_url('h_80,w_80,c_thumb,g_face')

    order_seller_prepared = order.product.seller.to_json()
    order_seller_prepared['_photo_url'] = order.product.seller.get_photo_url('h_80,w_80,c_thumb,g_face')

    application_data['extra'] = dict(
        mode='seller',
        order=order_prepared,
        service=order.product.to_json(),
        buyer=order_buyer_prepared,
        seller=order_seller_prepared
    )

    return render_template('new/account/order-dispute.html',
        application_data=application_data,
        mode='seller',
        order=order
    )


@account.route('/account/seller/orders/<order_id>')
@login_required
@seller_required
def seller_order(order_id):
    if not order_id.isdigit():
        abort(404)
    
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    if order.is_pending:
        abort(404)

    if order.is_pending_verification:
        return redirect(url_for('account.seller_order_verification', order_id=order_id))

    summary, total = prepare_order_summary(order)

    application_data = prepare_application_data()

    order_prepared = order.to_json()
    order_prepared['_state_pretty_print'] = order.get_state_pretty_print()
    order_prepared['is_requirements_provided'] = order.is_requirements_provided

    order_dispute = order.get_active_dispute()
    order_prepared['_dispute_text'] = order_dispute.text if order_dispute and order_dispute.text else None
    order_prepared['_dispute_user_id'] = order_dispute.user_id if order_dispute else None
    order_prepared['_dispute_created_on'] = isoformat(order_dispute.created_on) if order_dispute else None
    order_prepared['_dispute_resolution_kind'] = order_dispute.resolution_kind if order_dispute else None

    order_requirements = order.get_data('requirements')
    product_requirements = order.product.get_data('requirements')

    if order.is_requirements_provided and order.requirements_provided_on:
        order_accept_deadline = order.requirements_provided_on + timedelta(seconds=app.config['ORDER_ACCEPT_DEADLINE'])
        order_prepared['requirements_provided_on'] = order.requirements_provided_on
    else:
        order_accept_deadline = order.created_on + timedelta(seconds=app.config['ORDER_ACCEPT_DEADLINE'])

    order_prepared['_accept_deadline'] = order_accept_deadline
    order_prepared['_accept_deadline_passed'] = order_accept_deadline < datetime.utcnow()

    order_feedback = order.get_buyer_feedback()
    order_prepared['_feedback'] = order_feedback.to_json() if order_feedback else None

    order_prepared['_revision_count'] = order.get_revision_count()

    order_prepared['_delivery_deadline_passed'] = order.delivery_on < datetime.utcnow() if order.delivery_on else False

    if order.state == Order.SENT and order.delivered_on:
        delta = order.delivered_on + timedelta(seconds=app.config['ORDER_SENT_DEADLINE']) - datetime.utcnow()
        order_prepared['_sent_deadline_display'] = timedelta_pretty_print(delta) if delta.total_seconds() > 3600 else '1 hour'

    order_prepared['_total_price'] = order.get_total_price()

    order_buyer_prepared = order.buyer.to_json()
    order_buyer_prepared['_photo_url'] = order.buyer.get_photo_url('h_100,w_100,c_thumb,g_face')
    order_buyer_prepared['is_online'] = order.buyer.is_online
    order_buyer_prepared['last_logged_on'] = isoformat(order.buyer.last_logged_on)
    order_buyer_prepared['local_time'] = get_local_datetime(datetime.now(), order.buyer.tz).strftime('%I:%M %p')

    order_seller_prepared = order.product.seller.to_json()
    order_seller_prepared['_photo_url'] = order.product.seller.get_photo_url('h_100,w_100,c_thumb,g_face')
    order_seller_prepared['is_online'] = order.product.seller.is_online
    order_seller_prepared['last_logged_on'] = isoformat(order.product.seller.last_logged_on)
    order_seller_prepared['local_time'] = get_local_datetime(datetime.now(), order.product.seller.tz).strftime('%I:%M %p')

    product_extras = order.product.get_data('extras') or []

    application_data['extra'] = dict(
        order=order_prepared,
        service=order.product.to_json(),
        buyer=order_buyer_prepared,
        seller=order_seller_prepared,
        order_requirements=order_requirements,
        product_requirements=product_requirements,
        product_extras=product_extras,
        mode='seller'
    )

    return render_template('new/account/seller-order.html', 
        application_data=application_data,
        order=order,
        summary=summary,
        total=total,
        mode='seller'
    )


@account.route('/account/seller/discounts')
@login_required
@seller_required
def discounts():
    application_data = prepare_application_data()

    tab_counts = dict()

    tab_counts['codes'] = Discount.query \
                                  .filter(Discount.seller_id==g.user.id) \
                                  .filter(Discount.buyer_id==None) \
                                  .count()

    tab_counts['offers'] = ProductOffer.query \
                                       .filter(ProductOffer.is_deleted!=True, ProductOffer.product_id==Product.id) \
                                       .filter(Product.seller_id==g.user.id) \
                                       .count()

    return render_template('new/account/seller-discounts.html', application_data=application_data, tab_counts=tab_counts)


@account.route('/api/account/seller/services')
@login_required
@xhr_required
@seller_required
def api_services():
    incoming_query = request.args.get('query')
    incoming_limit = request.args.get('limit', 5, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)
    incoming_type = request.args.get('type', 'active')

    service_type_condition = SERVICES_TYPE_MAPPING.get(incoming_type)
    if not service_type_condition:
        raise APIError('Service type is required')

    services_query = Product.query.filter(Product.seller_id == g.user.id)

    if incoming_type != 'deleted':
        services_query = services_query.filter(Product.is_deleted != True)

    services_query = services_query.filter(*service_type_condition).order_by(Product.created_on.desc())

    services_count = services_query.count()
    services_query = services_query.limit(incoming_limit).offset(incoming_offset)

    services_prepared = list()

    for service in services_query.all():
        service_prepared = service.to_json()
        service_prepared['views'] = service.get_views()
        service_prepared['is_deleted'] = service.is_deleted
        service_prepared['published_on'] = isoformat(service.published_on) if service.published_on else None
        service_prepared['_is_paused'] = False if service.published_on else True
        service_prepared['_primary_photo_url'] = service.get_primary_photo(transform='w_64,h_52')
        service_prepared['_edit_url'] = url_for('account.service_edit', unique_id=service.unique_id)
        service_prepared['_url'] = url_for('product', product_title=service.get_title_seofied(), product_id=service.unique_id, _external=True)
        service_prepared['_orders_count'] = service.orders.filter(Order.state.in_((Order.ACCEPTED, Order.SENT, Order.NEW, Order.CLOSED_COMPLETED, Order.DISPUTE))).count()
        services_prepared.append(service_prepared)

    return json.jsonify(
        data=services_prepared,
        meta=dict(
            total=services_count
        )
    )


@account.route('/api/account/seller/search/services')
@login_required
@xhr_required
@seller_required
def api_search_services():
    incoming_query = request.args.get('query')
    incoming_include_thumbnails = request.args.get('include_thumbnail')

    services_query = Product.query_active().filter(Product.seller_id == g.user.id)

    if incoming_query:
        services_query = services_query.filter(Product.title.ilike('%%%s%%' % incoming_query))

    services_query = services_query.order_by(Product.published_on.desc())

    def prepare_service(service):
        prepared_service = service.to_json()

        if incoming_include_thumbnails:
            prepared_service['_thumbnail_url'] = service.get_primary_photo('c_pad,g_center,w_200,h_200')

        return prepared_service

    return json.jsonify(
        map(prepare_service, services_query.all())
    )


@account.route('/api/account/seller/search/tags')
@login_required
@xhr_required
@seller_required
def api_search_tags():
    incoming_query = request.args.get('query')

    tags_query = Tag.query \
                  .filter(Tag.is_approved == True) \
                  .filter(Tag.tag.ilike('%%%s%%' % incoming_query)) \
                  .order_by(Tag.id.asc())

    return json.jsonify(
        [tag.tag for tag in tags_query.all()]
    )


@account.route('/api/account/seller/orders')
@login_required
@xhr_required
@seller_required
def api_seller_orders():
    incoming_query = request.args.get('query')
    incoming_limit = request.args.get('limit', 5, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)
    incoming_type = request.args.get('type', 'active')

    states = ORDERS_STATE_MAPPING.get(incoming_type)
    if not states:
        raise APIError('Order type is required')

    orders_query = Order.query.join(Product) \
                  .filter(Order.state.in_(states)) \
                  .filter(coalesce(Order.is_pending, False) != True) \
                  .filter(Product.seller_id == g.user.id) \
                  .order_by(Order.created_on.desc())

    if incoming_type == 'needs_review':
        orders_query = orders_query.outerjoin(Feedback, and_(Feedback.order_id == Order.id, Feedback.type == Feedback.ON_BUYER)) \
                                   .group_by(Order) \
                                   .having(func.count(Feedback.id) == 0)

    orders_count = orders_query.count()

    orders_query = orders_query \
        .limit(incoming_limit) \
        .offset(incoming_offset) \
        .options(joinedload('product').load_only('title', 'primary_photo_key')) \
        .options(joinedload('buyer').load_only('username', 'photo_data'))

    orders = orders_query.all()
    orders_prepared = list()

    for order in orders:
        order_prepared = order.to_json()
        order_prepared['is_requirements_provided'] = order.is_requirements_provided
        order_prepared['_url'] = url_for('account.seller_order', order_id=order.id)
        order_prepared['_product_title'] = order.product.title
        order_prepared['_buyer_username'] = order.buyer.username
        order_prepared['_buyer_photo_url'] = order.buyer.get_photo_url('h_52,w_52,c_thumb,g_face')
        orders_prepared.append(order_prepared)

    return json.jsonify(
        data=orders_prepared,
        meta=dict(
            total=orders_count
        )
    )


@account.route('/api/account/seller/orders/<int:order_id>')
@login_required
@xhr_required
@seller_required
def api_seller_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    order_prepared = order.to_json()
    order_prepared['_state_pretty_print'] = order.get_state_pretty_print()
    order_prepared['is_requirements_provided'] = order.is_requirements_provided

    order_dispute = order.get_active_dispute()
    order_prepared['_dispute_text'] = order_dispute.text if order_dispute and order_dispute.text else None
    order_prepared['_dispute_user_id'] = order_dispute.user_id if order_dispute else None
    order_prepared['_dispute_created_on'] = isoformat(order_dispute.created_on) if order_dispute else None
    order_prepared['_dispute_resolution_kind'] = order_dispute.resolution_kind if order_dispute else None

    order_prepared['_revision_count'] = order.get_revision_count()

    order_prepared['_delivery_deadline_passed'] = order.delivery_on < datetime.utcnow() if order.delivery_on else False

    if order.state == Order.SENT and order.delivered_on:
        delta = order.delivered_on + timedelta(seconds=app.config['ORDER_SENT_DEADLINE']) - datetime.utcnow()
        order_prepared['_sent_deadline_display'] = timedelta_pretty_print(delta) if delta.total_seconds() > 3600 else '1 hour'

    order_prepared['_total_price'] = order.get_total_price()

    return json.jsonify(order_prepared)


@account.route('/api/account/seller/orders/<int:order_id>/accept', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_order_accept(order_id):
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    if order.state != Order.NEW or not order.is_requirements_provided or order.is_pending_verification:
        abort(400)

    order.change_state(Order.ACCEPTED, g.user)

    # Return prepared order object
    return api_seller_order(order_id)


@account.route('/api/account/seller/orders/<int:order_id>/reject', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_order_reject(order_id):
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    if order.state != Order.NEW or order.is_pending_verification:
        abort(400)

    incoming = request.get_json()
    reason = incoming.get('reason')

    order.change_state(Order.CLOSED_REJECTED, g.user, reason)

    # Return prepared order object
    return api_seller_order(order_id)


@account.route('/api/account/seller/orders/<int:order_id>/deliver', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_order_deliver(order_id):
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    if order.state not in (Order.ACCEPTED, Order.SENT):
        abort(400)
    
    form = DeliverAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        order.deliver(form.files.data, form.text.data)

        # Return prepared order object
        return api_seller_order(order_id)
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/seller/orders/<int:order_id>/offer', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_order_offer(order_id):
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    if order.state not in (Order.NEW, Order.ACCEPTED):
        abort(400)
    
    form = CustomOfferAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        order.offer(
            form.extras.data,
            form.custom_extras.data[0] if form.custom_extras.data else None,
            form.delivery_time.data,
            form.message.data,
            form.message_attachments.data
        )

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/seller/orders/<int:order_id>/offer/<int:order_offer_id>/cancel', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_order_offer_cancel(order_id, order_offer_id):
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    order_offer = OrderOffer.query.get_or_404(order_offer_id)
    if order_offer.order_id != order_id or order_offer.is_closed or order_offer.is_accepted:
        abort(403)

    order_offer.is_closed = True
    db.session.add(order_offer)
    messaging.handle_order_offer_update(order, order_offer)

    # We have to make sure that we notified messaging server before saving into database
    db.session.commit()

    # Return prepared order object
    return json.jsonify(dict())


@account.route('/api/account/seller/services/<unique_id>/offer', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_service_offer(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)
    
    form = ServiceOfferAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        enquiry = Enquiry.query.get(form.enquiry_id.data)
        if not enquiry or enquiry.get_seller_id() != g.user.id:
            raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))

        product = Product.get_by_custom_id(form.service_id.data)
        if not product or product.seller_id != g.user.id or product.is_deleted:
            raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))

        buyer = User.query.get(enquiry.user_id)

        EnquiryOffer.create(
            enquiry,
            product,
            form.message.data,
            form.price.data,
            form.delivery_time.data,
            form.revision_count.data,
            expiration_time=form.expiration_time.data
        )

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/seller/offers/<int:enquiry_offer_id>/cancel', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_offer_cancel(enquiry_offer_id):
    enquiry_offer = EnquiryOffer.query.get_or_404(enquiry_offer_id)
    if enquiry_offer.get_product().seller_id != g.user.id or enquiry_offer.is_closed or enquiry_offer.is_accepted:
        abort(403)

    enquiry_offer.is_closed = True
    db.session.add(enquiry_offer)
    messaging.handle_enquiry_offer_update(enquiry_offer)

    # We have to make sure that we notified messaging server before saving into database
    db.session.commit()

    # Return prepared order object
    return json.jsonify(dict())


@account.route('/api/account/seller/discounts')
@login_required
@xhr_required
@seller_required
def api_seller_discounts():
    incoming_limit = request.args.get('limit', 10, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)

    discounts_query = Discount.query \
        .filter_by(seller_id=g.user.id) \
        .order_by(Discount.created_on.desc())

    discounts_count = discounts_query.count()

    discounts_query = discounts_query \
        .limit(incoming_limit) \
        .offset(incoming_offset) \
        .options(joinedload('product').load_only('title', 'primary_photo_key'))

    discounts = discounts_query.all()
    discounts_prepared = list()

    for discount in discounts:
        discount_prepared = discount.to_json()
        discount_prepared['_product_title'] = discount.product.title
        discount_prepared['_product_primary_photo_url'] = discount.product.get_primary_photo(transform='w_64,h_52')
        discounts_prepared.append(discount_prepared)

    return json.jsonify(
        data=discounts_prepared,
        meta=dict(
            total=discounts_count
        )
    )


@account.route('/api/account/seller/offers')
@login_required
@xhr_required
@seller_required
def api_seller_offers():
    incoming_limit = request.args.get('limit', 10, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)

    offers_query = ProductOffer.query \
        .filter(ProductOffer.is_deleted!=True, ProductOffer.product_id==Product.id) \
        .filter(Product.seller_id==g.user.id) \
        .order_by(ProductOffer.created_on.desc())

    offers_count = offers_query.count()

    offers_query = offers_query \
        .limit(incoming_limit) \
        .offset(incoming_offset) \
        .options(joinedload('product').load_only('title', 'primary_photo_key'))

    offers = offers_query.all()
    offers_prepared = list()

    for offer in offers:
        offer_prepared = offer.to_json()
        offer_prepared['_product_title'] = offer.product.title
        offer_prepared['_product_primary_photo_url'] = offer.product.get_primary_photo(transform='w_64,h_52')
        offers_prepared.append(offer_prepared)

    return json.jsonify(
        data=offers_prepared,
        meta=dict(
            total=offers_count
        )
    )


@account.route('/api/account/seller/discounts', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_discount_create():
    form = NewDiscountAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        value = form.value.data * 100 if form.type.data == Discount.ABSOLUTE else form.value.data

        product = Product.get_by_custom_id(form.product_id.data)

        discount = Discount.add(seller=g.user,
                                product_id=product.id,
                                type=form.type.data,
                                value=value)

        return json.jsonify(discount.to_json())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/seller/discounts/<int:discount_id>', methods=['DELETE'])
@login_required
@xhr_required
def api_seller_discount_delete(discount_id):
    discount = Discount.query.get_or_404(discount_id)

    if discount.seller_id != g.user.id:
        abort(403)

    if discount.buyer_id or discount.is_hold:
        # Can't delete used discount
        abort(403)

    db.session.delete(discount)
    db.session.commit()

    return json.jsonify(dict())


@account.route('/api/account/seller/offers', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_offer_create():
    form = NewOfferAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        value = form.value.data * 100 if form.type.data == ProductOffer.ABSOLUTE else form.value.data

        product = Product.get_by_custom_id(form.product_id.data)

        offer = ProductOffer(product_id=product.id,
                             type=form.type.data,
                             value=value,
                             start_date=form.start_date.data,
                             end_date=form.end_date.data)

        db.session.add(offer)
        db.session.commit()

        if (offer.start_date - date.today()).days <= 0 and (offer.end_date - date.today()).days >= 0:
            offer.product.set_active_offer(offer)
            search.product_updated.send(product=offer.product)

        return json.jsonify(offer.to_json())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/seller/offers/<int:offer_id>', methods=['PUT'])
@login_required
@xhr_required
@seller_required
def api_seller_offer_edit(offer_id):
    offer = ProductOffer.query.get_or_404(offer_id)

    if offer.is_deleted:
        abort(404)

    if offer.product.seller_id != g.user.id:
        abort(403)

    form = EditOfferAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        offer.value = form.value.data * 100 if form.type.data == ProductOffer.ABSOLUTE else form.value.data
        offer.start_date = form.start_date.data
        offer.end_date = form.end_date.data
        
        db.session.add(offer)
        db.session.commit()

        if (offer.start_date - date.today()).days <= 0 and (offer.end_date - date.today()).days >= 0:
            # Offer becomes active
            offer.product.set_active_offer(offer)
            search.product_updated.send(product=offer.product)
        elif offer.product.active_offer_id == offer.id:
            # Offer has been active before it was changed
            offer.product.set_active_offer(None)
            search.product_updated.send(product=offer.product)

        return json.jsonify(offer.to_json())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/seller/offers/<int:offer_id>', methods=['DELETE'])
@login_required
@xhr_required
@seller_required
def api_seller_offer_delete(offer_id):
    offer = ProductOffer.query.get_or_404(offer_id)

    if offer.product.seller_id != g.user.id:
        abort(403)

    if offer.product.active_offer_id == offer_id:
        offer.product.set_active_offer(None)
        search.product_updated.send(product=offer.product)

    offer.is_deleted = True

    db.session.add(offer)
    db.session.commit()

    return json.jsonify(dict())


# @account.route('/api/account/seller/orders/<int:order_id>/feedback', methods=['POST'])
# @login_required
# @xhr_required
# def api_seller_order_feedback(order_id):
#     order = Order.query.get_or_404(order_id)
#     if order.product.seller_id != g.user.id:
#         abort(403)

#     if order.state != Order.CLOSED_COMPLETED:
#         abort(400)

#     form = FeedbackAPIForm(csrf_enabled=False)

#     if form.validate_on_submit():
#         # order.create_buyer_feedback(form.rating.data, form.text.data)

#         order_prepared = order.to_json()
#         order_prepared['_state_pretty_print'] = order.get_state_pretty_print()

#         order_feedback = order.get_buyer_feedback()
#         order_prepared['_feedback'] = order_feedback.to_json() if order_feedback else None

#         return json.jsonify(order_prepared)
#     else:
#         raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/seller/orders/<int:order_id>/dispute', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_order_resolution(order_id):
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    if order.state not in (Order.NEW, Order.ACCEPTED, Order.SENT):
        abort(400)

    form = DisputeAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        if form.resolution_kind.data not in ['cancel', 'complete']:
            raise APIError('Please make sure you have specified all the fields properly')

        dispute = Dispute(
            user_id=g.user.id,
            order_id=order.id,
            kind=form.kind.data,
            resolution_kind=form.resolution_kind.data,
            text=form.text.data
        )

        db.session.add(dispute)
        db.session.commit()

        order.change_state(Order.DISPUTE, g.user)

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/seller/orders/<int:order_id>/resolve', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_order_resolve(order_id):
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    if order.state != Order.DISPUTE:
        abort(400)

    dispute = order.get_active_dispute()

    if not dispute or dispute.user_id == g.user.id:
        abort(400)

    dispute.resolve(g.user)

    # Return prepared order object
    return api_seller_order(order_id)


@account.route('/api/account/seller/orders/<int:order_id>/cancel_dispute', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_seller_order_cancel_dispute(order_id):
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id:
        abort(403)

    if order.state != Order.DISPUTE:
        abort(400)

    dispute = order.get_active_dispute()
    
    if not dispute or dispute.user_id != g.user.id:
        abort(400)

    dispute.cancel(g.user)

    # Return prepared order object
    return api_seller_order(order_id)


@account.route('/api/account/seller/attachments/download/<attachment_id>/<filename>', methods=['GET'])
@login_required
def api_seller_attachments_download(attachment_id, filename):
    url = Storage.get_attachment_aws_url(attachment_id, filename)
    return redirect(url)
