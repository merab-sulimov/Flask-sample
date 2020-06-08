from flask import url_for, redirect, render_template, json, request, g, abort, make_response
from flask_login import login_required
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func
from sqlalchemy.sql.functions import coalesce
from datetime import timedelta, datetime

from app import messaging, db, app, search
from app.decorators import xhr_required
from app.models import Order, OrderOffer, EnquiryOffer, Product, Dispute, Feedback, Deliverable, TransactionError, calculate_order_fee, isoformat
from app.helpers import APIError
from app.utils.storage import Storage
from app.utils import UploadException
from app.utils.tz import get_local_datetime
from .. import account
from ..helpers import prepare_application_data, prepare_order_summary
from ..forms import FeedbackAPIForm, DisputeAPIForm, RevisionAPIForm


ORDERS_STATE_MAPPING = {
    'active': (Order.NEW, Order.ACCEPTED,),
    'needs_action': (Order.DISPUTE,), # TODO: add another state for missing details?
    'needs_review': (Order.CLOSED_COMPLETED,),
    'delivered': (Order.SENT,),
    'completed': (Order.CLOSED_COMPLETED,),
    'cancelled': (Order.CLOSED_CANCELLED, Order.CLOSED_REJECTED,)
}


@account.route('/account/buyer')
@login_required
def buyer():
    tab_counts = dict()
    for tab, states in ORDERS_STATE_MAPPING.iteritems():
        query = Order.query \
                     .filter(Order.state.in_(states)) \
                     .filter(coalesce(Order.is_pending, False) != True) \
                     .filter(Order.buyer_id == g.user.id)

        if tab == 'needs_review':
            query = query.outerjoin(Feedback, and_(Feedback.order_id == Order.id, Feedback.type == Feedback.ON_SELLER)) \
                         .group_by(Order) \
                         .having(func.count(Feedback.id) == 0)

        tab_counts[tab] = query.count()

    return render_template('new/account/buyer.html', application_data=prepare_application_data(), tab_counts=tab_counts)


@account.route('/account/buyer/orders/<order_id>/verification')
@login_required
def buyer_order_verification(order_id):
    if not order_id.isdigit():
        abort(404)

    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if not order.is_pending_verification:
        return redirect(url_for('account.buyer_order', order_id=order_id))

    summary, total = prepare_order_summary(order, include_fee=True)

    application_data = prepare_application_data()

    order_prepared = order.to_json()

    product_requirements = order.product.get_data('requirements')

    order_buyer_prepared = order.buyer.to_json()
    order_buyer_prepared['_photo_url'] = order.buyer.get_photo_url('h_80,w_80,c_thumb,g_face')

    order_seller_prepared = order.product.seller.to_json()
    order_seller_prepared['_photo_url'] = order.product.seller.get_photo_url('h_80,w_80,c_thumb,g_face')

    application_data['extra'] = dict(
        mode='buyer',
        order=order_prepared,
        service=order.product.to_json(),
        buyer=order_buyer_prepared,
        seller=order_seller_prepared,
        product_requirements=product_requirements
    )

    return render_template('new/account/order-verification.html',
        application_data=application_data,
        mode='buyer',
        order=order,
        summary=summary,
        total=total
    )


@account.route('/account/buyer/orders/<order_id>/requirements')
@login_required
def buyer_order_requirements(order_id):
    if not order_id.isdigit():
        abort(404)

    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.is_pending_verification:
        return redirect(url_for('account.buyer_order_verification', order_id=order_id))

    if order.is_requirements_provided or order.state != Order.NEW:
        return redirect(url_for('account.buyer_order', order_id=order_id))

    summary, total = prepare_order_summary(order, include_fee=True)

    application_data = prepare_application_data()

    order_prepared = order.to_json()
    order_prepared['_state_pretty_print'] = order.get_state_pretty_print()

    product_requirements = order.product.get_data('requirements')

    order_buyer_prepared = order.buyer.to_json()
    order_buyer_prepared['_photo_url'] = order.buyer.get_photo_url('h_80,w_80,c_thumb,g_face')

    order_seller_prepared = order.product.seller.to_json()
    order_seller_prepared['_photo_url'] = order.product.seller.get_photo_url('h_80,w_80,c_thumb,g_face')

    application_data['extra'] = dict(
        mode='buyer',
        order=order_prepared,
        service=order.product.to_json(),
        buyer=order_buyer_prepared,
        seller=order_seller_prepared,
        product_requirements=product_requirements
    )

    return render_template('new/account/order-requirements.html',
        application_data=application_data,
        mode='buyer',
        order=order,
        summary=summary,
        total=total
    )


@account.route('/account/buyer/orders/<order_id>/review')
@login_required
def buyer_order_review(order_id):
    if not order_id.isdigit():
        abort(404)

    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.state != Order.CLOSED_COMPLETED or order.get_seller_feedback():
        # Order is not CLOSED_COMPLETED or already has a feedback
        return redirect(url_for('account.buyer_order', order_id=order_id))

    application_data = prepare_application_data()
    
    order_prepared = order.to_json()

    order_buyer_prepared = order.buyer.to_json()
    order_buyer_prepared['_photo_url'] = order.buyer.get_photo_url('h_80,w_80,c_thumb,g_face')

    order_seller_prepared = order.product.seller.to_json()
    order_seller_prepared['_photo_url'] = order.product.seller.get_photo_url('h_80,w_80,c_thumb,g_face')

    application_data['extra'] = dict(
        mode='buyer',
        order=order_prepared,
        service=order.product.to_json(),
        buyer=order_buyer_prepared,
        seller=order_seller_prepared
    )

    return render_template('new/account/order-review.html',
        application_data=application_data,
        mode='buyer',
        order=order
    )


@account.route('/account/buyer/orders/<order_id>')
@login_required
def buyer_order(order_id):
    if not order_id.isdigit():
        abort(404)

    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id and not g.user.is_admin:
        abort(403)

    if order.is_pending:
        abort(404)

    if order.is_pending_verification:
        return redirect(url_for('account.buyer_order_verification', order_id=order_id))

    if not order.is_requirements_provided and order.state == Order.NEW:
        return redirect(url_for('account.buyer_order_requirements', order_id=order_id))

    summary, total = prepare_order_summary(order, include_fee=True)

    application_data = prepare_application_data()

    order_prepared = order.to_json()
    order_prepared['_state_pretty_print'] = order.get_state_pretty_print()
    order_prepared['is_requirements_provided'] = order.is_requirements_provided

    if order.is_requirements_provided and order.requirements_provided_on:
        order_accept_deadline = order.requirements_provided_on + timedelta(seconds=app.config['ORDER_ACCEPT_DEADLINE'])
        order_prepared['requirements_provided_on'] = order.requirements_provided_on
    else:
        order_accept_deadline = order.created_on + timedelta(seconds=app.config['ORDER_ACCEPT_DEADLINE'])

    order_prepared['_accept_deadline'] = order_accept_deadline
    order_prepared['_accept_deadline_passed'] = order_accept_deadline < datetime.utcnow()

    if order.state == Order.SENT and order.delivered_on:
        order_prepared['_sent_deadline'] = order.delivered_on + timedelta(seconds=app.config['ORDER_SENT_DEADLINE'])

    order_feedback = order.get_seller_feedback()
    order_prepared['_feedback'] = order_feedback.to_json() if order_feedback else None

    order_dispute = order.get_active_dispute()
    order_prepared['_dispute_text'] = order_dispute.text if order_dispute and order_dispute.text else None
    order_prepared['_dispute_user_id'] = order_dispute.user_id if order_dispute else None
    order_prepared['_dispute_resolution_kind'] = order_dispute.resolution_kind if order_dispute else None
    order_prepared['_dispute_created_on'] = isoformat(order_dispute.created_on) if order_dispute else None

    order_prepared['revision_count_left'] = order.revision_count_left
    order_prepared['_revision_count'] = order.get_revision_count()

    product_requirements = order.product.get_data('requirements')
    order_requirements = order.get_data('requirements')

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

    application_data['extra'] = dict(
        mode='buyer',
        order=order_prepared,
        service=order.product.to_json(),
        buyer=order_buyer_prepared,
        seller=order_seller_prepared,
        order_requirements=order_requirements,
        product_requirements=product_requirements
    )

    order_sent_deadline_timedelta = timedelta(seconds=app.config['ORDER_SENT_DEADLINE'])

    return render_template('new/account/buyer-order.html',
        application_data=application_data,
        mode='buyer',
        order=order,
        summary=summary,
        total=total,
        order_sent_deadline_timedelta=order_sent_deadline_timedelta,
        admin_mode=(order.buyer_id != g.user.id and g.user.is_admin)
    )


@account.route('/account/buyer/orders/<order_id>/resolution')
@login_required
def buyer_order_resolution(order_id):
    if not order_id.isdigit():
        abort(404)

    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
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
        mode='buyer',
        order=order_prepared,
        service=order.product.to_json(),
        buyer=order_buyer_prepared,
        seller=order_seller_prepared
    )

    return render_template('new/account/order-dispute.html',
        application_data=application_data,
        mode='buyer',
        order=order
    )


@account.route('/api/account/buyer/orders')
@login_required
@xhr_required
def api_buyer_orders():
    incoming_query = request.args.get('query')
    incoming_limit = request.args.get('limit', 5, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)
    incoming_type = request.args.get('type', 'active')

    states = ORDERS_STATE_MAPPING.get(incoming_type)
    if not states:
        raise APIError('Order type is required')

    orders_query = Order.query \
                  .filter(Order.state.in_(states)) \
                  .filter(coalesce(Order.is_pending, False) != True) \
                  .filter(Order.buyer_id == g.user.id) \
                  .order_by(Order.created_on.desc())

    if incoming_type == 'needs_review':
        orders_query = orders_query.outerjoin(Feedback, and_(Feedback.order_id == Order.id, Feedback.type == Feedback.ON_SELLER)) \
                                   .group_by(Order) \
                                   .having(func.count(Feedback.id) == 0)

    orders_count = orders_query.count()

    orders_query = orders_query \
        .limit(incoming_limit) \
        .offset(incoming_offset) \
        .options(joinedload('product').load_only('title', 'primary_photo_key')) \
        .options(joinedload('product.seller').load_only('username', 'photo_data'))

    orders = orders_query.all()
    orders_prepared = list()

    for order in orders:
        order_prepared = order.to_json()
        order_prepared['is_requirements_provided'] = order.is_requirements_provided
        order_prepared['is_pending_verification'] = order.is_pending_verification
        order_prepared['_url'] = url_for('account.buyer_order', order_id=order.id)
        order_prepared['_product_title'] = order.product.title
        order_prepared['_product_seller_photo'] = order.product.seller.get_photo_url('h_52,w_52,c_thumb,g_face')
        order_prepared['_product_seller_username'] = order.product.seller.username
        orders_prepared.append(order_prepared)

    return json.jsonify(
        data=orders_prepared,
        meta=dict(
            total=orders_count
        )
    )


@account.route('/api/account/buyer/orders/<int:order_id>')
@login_required
@xhr_required
def api_buyer_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    order_prepared = order.to_json()
    order_prepared['_state_pretty_print'] = order.get_state_pretty_print()
    order_prepared['is_requirements_provided'] = order.is_requirements_provided

    order_feedback = order.get_seller_feedback()
    order_prepared['_feedback'] = order_feedback.to_json() if order_feedback else None

    order_dispute = order.get_active_dispute()
    order_prepared['_dispute_text'] = order_dispute.text if order_dispute and order_dispute.text else None
    order_prepared['_dispute_user_id'] = order_dispute.user_id if order_dispute else None
    order_prepared['_dispute_resolution_kind'] = order_dispute.resolution_kind if order_dispute else None
    order_prepared['_dispute_created_on'] = isoformat(order_dispute.created_on) if order_dispute else None

    if order.state == Order.SENT and order.delivered_on:
        order_prepared['_sent_deadline'] = order.delivered_on + timedelta(seconds=app.config['ORDER_SENT_DEADLINE'])

    order_prepared['_total_price'] = order.get_total_price()

    order_prepared['revision_count_left'] = order.revision_count_left
    order_prepared['_revision_count'] = order.get_revision_count()

    order_prepared['_url'] = url_for('account.buyer_order', order_id=order_id)

    return json.jsonify(order_prepared)


@account.route('/api/account/buyer/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
@xhr_required
def api_buyer_order_cancel(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.state != Order.NEW:
        abort(400)

    if order.is_requirements_provided and order.requirements_provided_on:
        order_accept_deadline = order.requirements_provided_on + timedelta(seconds=app.config['ORDER_ACCEPT_DEADLINE'])
    else:
        order_accept_deadline = order.created_on + timedelta(seconds=app.config['ORDER_ACCEPT_DEADLINE'])

    if order_accept_deadline > datetime.utcnow():
        # Do not allow to cancel order where accept deadline is not passed yet
        abort(400)

    order.change_state(Order.CLOSED_CANCELLED, g.user)

    # Return prepared order object
    return api_buyer_order(order_id)


@account.route('/api/account/buyer/orders/<int:order_id>/start', methods=['POST'])
@login_required
@xhr_required
def api_buyer_order_start(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.state != Order.NEW or order.is_requirements_provided:
        abort(400)

    product_requirements = order.product.get_data('requirements')
    product_requirements_dict = dict()

    for product_requirement in product_requirements:
        product_requirements_dict[product_requirement['id']] = product_requirement

    incoming = request.get_json()
    incoming_requirements = incoming.get('requirements')
    incoming_requirements_dict = dict()

    for incoming_requirement in incoming_requirements:
        incoming_requirements_dict[incoming_requirement['id']] = incoming_requirement

    for product_requirement in product_requirements:
        incoming_requirement = incoming_requirements_dict[product_requirement['id']] if product_requirement['id'] in incoming_requirements_dict else None

        if product_requirement['required'] and not incoming_requirement:
            abort(400)

        if not incoming_requirement:
            continue

        reply = incoming_requirement['reply']

        if product_requirement['required'] and not reply:
            abort(400)

        if not reply:
            continue

        if product_requirement['type'] == 'text' and type(reply) not in (unicode, str):
            abort(400)

        if product_requirement['type'] == 'files' and type(reply) is not list:
            abort(400)

        if product_requirement['type'] == 'files':
            for attachment in reply:
                if set(attachment) != set(('size', 'attachmentId', 'filename',)):
                    abort(400)

    order.set_data('requirements', incoming_requirements)
    order.is_requirements_provided = True
    order.requirements_provided_on = datetime.utcnow()
    db.session.add(order)
    db.session.commit()

    # Return prepared order object
    return api_buyer_order(order_id)


@account.route('/api/account/buyer/orders/<int:order_id>/revision', methods=['POST'])
@login_required
@xhr_required
def api_buyer_order_revision(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.state != Order.SENT:
        abort(400)

    if not order.revision_count_left:
        abort(403)

    form = RevisionAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        order.change_state(Order.ACCEPTED, g.user)
        messaging.handle_order_revision(order, form.description.data, form.files.data)
        return api_buyer_order(order_id)
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/buyer/orders/<int:order_id>/complete', methods=['POST'])
@login_required
@xhr_required
def api_buyer_order_complete(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.state != Order.SENT:
        abort(400)

    order.change_state(Order.CLOSED_COMPLETED, g.user)

    return json.jsonify(dict(_url=url_for('account.buyer_order_review', order_id=order_id)))



@account.route('/api/account/buyer/orders/<int:order_id>/deliverable/<int:deliverable_id>/vote', methods=['POST'])
@login_required
@xhr_required
def api_buyer_order_deliverable_vote(order_id, deliverable_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    deliverable = Deliverable.query.get_or_404(deliverable_id)
    if deliverable.order_id != order_id or deliverable.rating:
        abort(403)

    incoming_json = request.get_json()
    incoming_rating = incoming_json.get('rating')

    if not type(incoming_rating) == int or incoming_rating < 1 or incoming_rating > 5:
        abort(400)

    deliverable.rating = incoming_rating
    db.session.add(deliverable)
    messaging.handle_order_deliverable_vote(order, deliverable)

    # We have to make sure that we notified messaging server before saving rating into database
    db.session.commit()

    # Return prepared order object
    return api_buyer_order(order_id)


@account.route('/api/account/buyer/orders/<int:order_id>/offer/<int:order_offer_id>/accept', methods=['POST'])
@login_required
@xhr_required
def api_buyer_order_offer_accept(order_id, order_offer_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    order_offer = OrderOffer.query.get_or_404(order_offer_id)
    if order_offer.order_id != order_id or order_offer.is_closed or order_offer.is_accepted:
        abort(403)

    try:
        order.accept_offer(order_offer)
    except TransactionError, e:
        raise APIError(e.message, payload=dict(no_credit=True))

    # Return prepared order object
    return json.jsonify(dict())


@account.route('/api/account/buyer/offers/<int:enquiry_offer_id>/accept', methods=['POST'])
@login_required
@xhr_required
def api_buyer_offer_accept(enquiry_offer_id):
    enquiry_offer = EnquiryOffer.query.get_or_404(enquiry_offer_id)
    if enquiry_offer.get_enquiry().user_id != g.user.id or enquiry_offer.is_closed or enquiry_offer.is_accepted:
        abort(403)

    service = enquiry_offer.get_product()
    redirect_url = service.get_url(route='product_order', offer=enquiry_offer.id)

    # Return prepared order object
    return json.jsonify(dict(_url=redirect_url))


@account.route('/api/account/buyer/offers/<int:enquiry_offer_id>/cancel', methods=['POST'])
@login_required
@xhr_required
def api_buyer_offer_cancel(enquiry_offer_id):
    enquiry_offer = EnquiryOffer.query.get_or_404(enquiry_offer_id)
    if enquiry_offer.get_product().user_id != g.user.id or enquiry_offer.is_closed or enquiry_offer.is_accepted:
        abort(403)

    enquiry_offer.is_closed = True
    db.session.add(enquiry_offer)
    messaging.handle_enquiry_offer_update(enquiry_offer)

    # We have to make sure that we notified messaging server before saving into database
    db.session.commit()

    # Return prepared order object
    return json.jsonify(dict())


@account.route('/api/account/buyer/orders/<int:order_id>/feedback', methods=['POST'])
@login_required
@xhr_required
def api_buyer_order_feedback(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.state != Order.CLOSED_COMPLETED:
        abort(400)

    form = FeedbackAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        order.create_seller_feedback(form.rating.data, form.text.data)

        # Update product in search index once feedback is published
        search.product_updated.send(product=order.product)

        order_prepared = order.to_json()
        order_prepared['_state_pretty_print'] = order.get_state_pretty_print()

        order_feedback = order.get_seller_feedback()
        order_prepared['_feedback'] = order_feedback.to_json() if order_feedback else None

        return json.jsonify(order_prepared)
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/buyer/orders/<int:order_id>/dispute', methods=['POST'])
@login_required
@xhr_required
def api_buyer_order_resolution(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.state not in (Order.NEW, Order.ACCEPTED, Order.SENT):
        abort(400)

    form = DisputeAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        dispute = Dispute(
            user_id=g.user.id,
            order_id=order.id,
            kind=form.kind.data,
            resolution_kind='cancel',
            text=form.text.data
        )

        db.session.add(dispute)
        db.session.commit()

        order.change_state(Order.DISPUTE, g.user)

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/buyer/orders/<int:order_id>/resolve', methods=['POST'])
@login_required
@xhr_required
def api_buyer_order_resolve(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.state != Order.DISPUTE:
        abort(400)

    dispute = order.get_active_dispute()
    
    if not dispute or dispute.user_id == g.user.id:
        abort(400)

    dispute.resolve(g.user)

    # Return prepared order object
    return api_buyer_order(order_id)


@account.route('/api/account/buyer/orders/<int:order_id>/cancel_dispute', methods=['POST'])
@login_required
@xhr_required
def api_buyer_order_cancel_dispute(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.state != Order.DISPUTE:
        abort(400)

    dispute = order.get_active_dispute()
    
    if not dispute or dispute.user_id != g.user.id:
        abort(400)

    dispute.cancel(g.user)

    # Return prepared order object
    return api_buyer_order(order_id)
    

@account.route('/api/account/buyer/attachments/upload', methods=['POST'])
@login_required
def api_buyer_attachments_upload():
    storage = Storage()
    try:
        attachment_id, filename = storage.upload_attachment(request.files['file'])
    except UploadException, e:
        return make_response(json.jsonify(dict(error=e.message)), 400)

    return json.jsonify(dict(filename=filename, attachmentId=attachment_id))


@account.route('/api/account/buyer/attachments/delete', methods=['POST'])
@login_required
@xhr_required
def api_buyer_attachments_delete():
    data = request.get_json()

    storage = Storage()
    storage.delete_attachment(data['attachmentId'], data['filename'])

    return json.jsonify(dict())


@account.route('/api/account/buyer/attachments/download/<attachment_id>/<filename>', methods=['GET'])
@login_required
def api_buyer_attachments_download(attachment_id, filename):
    url = Storage.get_attachment_aws_url(attachment_id, filename)
    return redirect(url)
