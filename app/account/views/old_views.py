from flask import request, flash, url_for, redirect, g, abort, render_template, json, Response, escape, make_response, send_file, session
from flask_login import login_required
from datetime import timedelta, datetime, date

from app.models import db, Order, Feedback, Product, Category, ProductPhoto, Ticket, \
    Transaction, Variable, Dispute, Content, User, Withdrawal, \
    FavoriteProduct, FavoriteSearch, Newsletter, Voucher, Discount, ProductOffer, Tag
from app.utils import delete_product_photo, upload_product_attachment, \
     delete_product_attachment, get_product_attachment_filename, upload_profile_photo, delete_profile_photo, \
     upload_order_attachment, get_order_attachment_filename, static_file_url
from .. import account
from ..forms import PasswordChangeForm, ProfileForm, WithdrawBTCForm, NewProductForm, \
    EditProductForm, NewProductPhotoForm, TransferFundsForm, WithdrawWUForm, \
    TwoFactorAuthForm, NewsletterForm, EmailSettingsForm, DeleteAccountForm, ProfilePhotoForm, \
    VoucherActivateForm, NewDiscountForm, NewInviteForm, ShipProductForm, NewOfferForm, EmptyForm
from app import search
from app.utils.storage import Storage


PRODUCTS_PER_PAGE = 5
TRANSACTIONS_PER_PAGE = 20


@account.route('/account/seller/products.html')
@login_required
def seller_products():
    page = request.args.get('page', 1, type=int)
    mode = request.args.get('mode', 'active')

    products = Product.query.filter_by(seller_id=g.user.id)

    if mode == 'disabled':
        products = products.filter_by(is_deleted=True)
    elif mode == 'pending':
        products = products.filter_by(is_deleted=False, is_approved=False)
    else:
        products = products.filter_by(is_deleted=False, is_approved=True)

    products = products.order_by(Product.is_approved.asc(), Product.created_on.desc())
    pagination = products.paginate(page, per_page=PRODUCTS_PER_PAGE)

    need_pay_seller_fee = False
    seller_fee = g.seller_fee_pp
    if seller_fee and not g.user.seller_fee_paid:
        need_pay_seller_fee = True

    active_count = Product.query.filter_by(is_deleted=False, seller_id=g.user.id, is_approved=True).count()
    pending_count = Product.query.filter_by(is_deleted=False, seller_id=g.user.id, is_approved=False).count()

    return render_template('account/seller_products.html', pagination=pagination, need_pay_seller_fee=need_pay_seller_fee, seller_fee=seller_fee, mode=mode, active_count=active_count, pending_count=pending_count)


@account.route('/account/become_a_seller.html', methods=['GET', 'POST'])
@login_required
def seller_fee():
    if g.user.seller_fee_paid:
        # User has already paid seller fee
        return redirect(url_for('account.seller_products'))

    seller_fee_pp = Variable.get_seller_fee_pp()
    seller_fee = Variable.get_seller_fee()
    can_pay = (g.user.credit >= seller_fee)

    voucher_form = VoucherActivateForm()
    form = EmptyForm()

    if can_pay and form.validate_on_submit():
        Transaction.transaction(type=Transaction.SELLER_FEE,
                                amount=seller_fee,
                                user=g.user,
                                note='One-time seller fee')

        g.user.seller_fee_paid = True
        db.session.add(g.user)
        db.session.commit()

        flash('Fee payment has been processed', 'success')
        return redirect(url_for('account.seller_products'))

    return render_template(
        'account/seller_fee.html',
        seller_fee=seller_fee_pp,
        can_pay=can_pay,
        form=form,
        voucher_form=voucher_form
    )


@account.route('/account/premium.html', methods=['GET', 'POST'])
@login_required
def premium():
    premium_fee_pp = Variable.get_premium_fee_pp()
    premium_fee = Variable.get_premium_fee()
    can_pay = (g.user.credit >= premium_fee)

    voucher_form = VoucherActivateForm()
    form = EmptyForm()

    if can_pay and form.validate_on_submit():
        Transaction.transaction(type=Transaction.PREMIUM_MEMBER_FEE,
                                amount=premium_fee,
                                user=g.user,
                                note='One-time premium membership fee')

        g.user.premium_member = True
        db.session.add(g.user)
        db.session.commit()

        flash('Fee payment has been processed', 'success')
        return redirect(url_for('account.premium'))

    return render_template('account/premium.html', premium_fee=premium_fee_pp, can_pay=can_pay, voucher_form=voucher_form, form=form)


@account.route('/account/buyer/orders')
@login_required
def buyer_orders():
    page = request.args.get('page', 1, type=int)

    states = (Order.NEW, Order.ACCEPTED, Order.SENT, Order.DISPUTE, Order.CLOSED_COMPLETED)

    orders = Order.query \
                  .filter(Order.state.in_(states)) \
                  .filter_by(buyer_id=g.user.id) \
                  .order_by(Order.created_on.desc())

    pagination = orders.paginate(page, per_page=PRODUCTS_PER_PAGE)

    return render_template('account/buyer_orders.html', pagination=pagination)


@account.route('/account/buyer/order/<int:order_id>')
@login_required
def buyer_order_old(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    # if order.state not in (Order.CLOSED_COMPLETED, Order.CLOSED_CANCELLED, Order.CLOSED_REJECTED):
    #     abort(403)

    return render_template('account/buyer_order.html', order=order)


@account.route('/account/buyer/orders/<int:order_id>/download')
@login_required
def buyer_orders_download(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != g.user.id:
        abort(403)

    if order.state not in (Order.CLOSED_COMPLETED, Order.SENT):
        abort(403)

    if not order.product.private_filename_fs:
        abort(404)

    path = get_product_attachment_filename(order.product.private_filename_fs, order.product.id)

    resp = make_response(send_file(path, as_attachment=True, attachment_filename=order.product.private_filename))
    resp.cache_control.no_cache = True
    return resp


@account.route('/account/buyer/order/<int:order_id>/download')
@login_required
def buyer_order_download(order_id):
    order = Order.query.get_or_404(order_id)
    if order.product.seller_id != g.user.id and order.buyer_id != g.user.id:
       abort(403)

    if order.state not in (Order.CLOSED_COMPLETED, Order.SENT):
        abort(403)

    if not order.private_filename_fs:
        abort(404)

    path = get_order_attachment_filename(order.private_filename_fs, order.id)

    resp = make_response(send_file(path, as_attachment=True, attachment_filename=order.private_filename))
    resp.cache_control.no_cache = True
    return resp


@account.route('/account/seller/orders.html', methods=['GET', 'POST'])
@login_required
def seller_orders():
    page = request.args.get('page', 1, type=int)
    state = request.args.get('state')

    states_dict = dict(
        new=dict(states=(Order.NEW,), label='New'),
        inprogress=dict(states=(Order.ACCEPTED, Order.SENT), label='In Progress'),
        disputed=dict(states=(Order.DISPUTE,), label='Disputed'),
        done=dict(states=(Order.CLOSED_COMPLETED, Order.CLOSED_CANCELLED, Order.CLOSED_REJECTED,), label='Done')
    )

    orders = Order.query \
        .filter(Product.seller_id==g.user.id) \
        .filter(Product.id==Order.product_id)

    if not state or state not in states_dict.keys():
        state = 'new'

    orders = orders.filter(Order.state.in_(states_dict[state]['states'])).order_by(Order.created_on.desc())
    pagination = orders.paginate(page, per_page=PRODUCTS_PER_PAGE)

    states = list()
    for s in ('new', 'inprogress', 'disputed', 'done',):
        count = Order.query.filter(Product.seller_id==g.user.id, Product.id==Order.product_id, Order.state.in_(states_dict[s]['states'])).count()
        states.append(dict(label="%s (%d)" % (states_dict[s]['label'], count), state=s))

    return render_template('account/seller_orders.html', pagination=pagination, state=state, states=states)


@account.route('/account/seller/order/<int:order_id>', methods=['GET', 'POST'])
@login_required
def seller_order_old(order_id):
    order = Order.query.get_or_404(order_id)
    form  = ShipProductForm()

    product = Product.query.get_or_404(order.product_id)
    if product.seller_id != g.user.id:
        abort(403)

    #if order.state not in (Order.CLOSED_COMPLETED, Order.CLOSED_CANCELLED, Order.CLOSED_REJECTED):
    #    abort(403)

    if form.validate_on_submit():
        order.private_message = form.private_description.data
        if form.private_attachment.data:
            filename_tmp, filename_fs = upload_order_attachment(form.private_attachment.data, product.get_title_seofied(), str(order.id))
            order.private_filename = filename_tmp
            order.private_filename_fs = filename_fs

        order.change_state(Order.SENT, g.user)

        db.session.add(product)
        db.session.commit()

        return redirect(url_for('account.seller_orders'))

    states_dict = dict(
        new=dict(states=(Order.NEW,), label='New'),
        inprogress=dict(states=(Order.ACCEPTED, Order.SENT), label='In Progress'),
        disputed=dict(states=(Order.DISPUTE,), label='Disputed'),
        done=dict(states=(Order.CLOSED_COMPLETED, Order.CLOSED_CANCELLED, Order.CLOSED_REJECTED,), label='Done')
    )

    states = list()
    for s in ('new', 'inprogress', 'disputed', 'done',):
        states.append(dict(label=states_dict[s]['label'], state=s, active=(order.state in states_dict[s]['states'])))

    return render_template('account/seller_order.html', order=order, form=form, states=states)


@account.route('/account/buyer/orders/history')
@login_required
def buyer_orders_history():
    page = request.args.get('page', 1, type=int)

    states = (Order.CLOSED_COMPLETED, Order.CLOSED_CANCELLED, Order.CLOSED_REJECTED,)

    orders = Order.query \
                  .filter(Order.buyer_id==g.user.id) \
                  .filter(Order.state.in_(states))

    orders = orders.order_by(Order.created_on.desc())

    pagination = orders.paginate(page, per_page=PRODUCTS_PER_PAGE)

    return render_template('account/buyer_orders_history.html', pagination=pagination)


@account.route('/account/newsletters/add', methods=['GET', 'POST'])
@login_required
def newsletters_add():
    latest_newsletter = Newsletter.get_latest_by_seller(g.user)
    if latest_newsletter:
        delta = datetime.utcnow() - latest_newsletter.created_on
        if delta < timedelta(days=1):
            remaining = timedelta(days=1) - delta
            return render_template('account/newsletters_add.html', remaining=remaining)

    form = NewsletterForm()
    if form.validate_on_submit():
        newsletter = Newsletter(seller_id=g.user.id,
                                subject=form.subject.data,
                                text=form.text.data)

        db.session.add(newsletter)
        db.session.commit()

        flash('Your update has been put into the moderation queue', 'warning')
        return redirect(url_for('account.newsletters_add'))

    return render_template('account/newsletters_add.html', form=form)


@account.route('/account/feedbacks')
@login_required
def feedbacks():
    page = request.args.get('page', 1, type=int)
    type = request.args.get('type')

    page_seller = page_buyer = 1
    if type == 'seller':
        page_seller = page
    elif type == 'buyer':
        page_buyer = page

    feedbacks_seller = g.user.query_seller_feedbacks()
    feedbacks_buyer = g.user.query_buyer_feedbacks()

    pagination_seller = feedbacks_seller.paginate(page_seller, per_page=PRODUCTS_PER_PAGE)
    pagination_buyer = feedbacks_buyer.paginate(page_buyer, per_page=PRODUCTS_PER_PAGE)

    return render_template('account/feedbacks.html', pagination_seller=pagination_seller, pagination_buyer=pagination_buyer)


@account.route('/account/seller/feedbacks.html')
@login_required
def seller_feedbacks():
    page = request.args.get('page', 1, type=int)

    feedbacks = g.user.query_seller_feedbacks()
    completed_orders = g.user.query_seller_feedbacks_pending().order_by(Order.closed_on.desc())

    pagination = feedbacks.paginate(page, per_page=PRODUCTS_PER_PAGE)

    return render_template('account/feedbacks_view.html', pagination=pagination, completed_orders=completed_orders, type='ON_SELLER')


@account.route('/account/buyer/feedbacks')
@login_required
def buyer_feedbacks():
    page = request.args.get('page', 1, type=int)

    feedbacks = g.user.query_buyer_feedbacks()
    completed_orders = g.user.query_buyer_feedbacks_pending().order_by(Order.closed_on.desc())

    pagination = feedbacks.paginate(page, per_page=PRODUCTS_PER_PAGE)

    return render_template('account/feedbacks_view.html', pagination=pagination, completed_orders=completed_orders, type='ON_BUYER')



@account.route('/account/add-product.html', methods=['GET', 'POST'])
@login_required
def product_new():
    # if not g.user.profile_description or not g.user.privacy_policy:
    #     flash('You must fill your public profile and privacy policy in order to create products for sale', 'warning')
    #     return redirect(url_for('account.profile'))

    if Variable.get_seller_fee() and not g.user.seller_fee_paid:
        flash('You must pay one-time seller fee in order to create products for sale', 'warning')
        return redirect(url_for('account.seller_fee'))

    form = NewProductForm()
    categories = Category.query_top()

    if form.validate_on_submit():
        product = Product(seller_id=g.user.id,
                          unique_id=Product.get_unique_id(),
                          title=form.title.data,
                          is_private=form.is_private.data,
                          additional_info_message=form.additional_info_message.data,
                          category_id=form.category_id.data,
                          description=form.description.data,
                          price=form.price.data * 100,
                          delivery_time=timedelta(days=form.delivery_time.data),
                          youtube_href=form.youtube_href.data,
                          quantity=form.quantity.data if form.is_quantity_limited.data else None)

        # Check if any extras was added

        if form.extras.data:
            product.set_extras(form.extras.data)

        # Check if tags were added

        if form.tags.data:
            try:
                tags = json.loads(form.tags.data)[:5]
                product.set_data('tags', tags)
            except:
                pass

        # Check if FAQ items were added

        if form.faq.data:
            try:
                faq = json.loads(form.faq.data)
                product.set_data('faq', faq)
            except:
                pass

        db.session.add(product)
        db.session.commit()

        # Process photos

        storage = Storage()
        is_primary = True
        product_photos = list()

        for item in ('photo', 'photo2', 'photo3', 'photo4'):
            if not form[item].data:
                continue

            aws_key, cloudinary_key = storage.upload_product_photo(form[item].data, product.id, product.get_title_seofied())
            product_photos.append(dict(aws_key=aws_key, cloudinary_key=cloudinary_key))
            product.set_data('photos', product_photos)

        if product_photos:
            db.session.add(product)
            db.session.commit()

        # Create missing tags for this product

        Tag.create_for_product(product)

        # Generate new private UUID and set private flag

        if form.is_private.data:
            product.set_private()

        # Add product to search index
        search.product_created.send(product=product)

        flash('New product has been successfully added', 'success')
        return redirect(url_for('account.seller_products'))

    return render_template('account/new_product.html', form=form, categories=categories)


@account.route('/account/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def product_edit(product_id):
    product = Product.query.get_or_404(product_id)

    if product.seller_id != g.user.id:
        # User attempted to edit a product he doesn't own
        abort(403)

    form = EditProductForm(title=product.title,
                           is_private=product.is_private,
                           description=product.description,
                           additional_info_message=product.additional_info_message,
                           price=product.price / 100.0,
                           delivery_time=product.delivery_time.days,
                           category_id=product.category_id,
                           youtube_href=product.youtube_href,
                           quantity=product.quantity if product.quantity else 0,
                           is_quantity_limited=product.quantity is not None,
                           extras=json.dumps(product.get_data('extras') or []),
                           faq=json.dumps(product.get_data('faq') or []),
                           tags=json.dumps(product.get_data('tags') or []))

    categories = Category.query_top()

    if form.validate_on_submit():
        product.title = form.title.data
        product.is_private = form.is_private.data
        product.description = form.description.data
        product.price = form.price.data * 100
        product.quantity = form.quantity.data if form.is_quantity_limited.data else None
        product.delivery_time = timedelta(days=form.delivery_time.data)
        product.category_id = form.category_id.data
        product.youtube_href = form.youtube_href.data
        product.updated_on = datetime.utcnow()
        product.additional_info_message = form.additional_info_message.data

        if form.extras.data:
            product.set_extras(form.extras.data)

        if form.tags.data:
            try:
                tags = json.loads(form.tags.data)[:5]
                product.set_data('tags', tags)
            except:
                pass

        if form.faq.data:
            try:
                faq = json.loads(form.faq.data)
                product.set_data('faq', faq)
            except:
                pass

        db.session.add(product)
        db.session.commit()

        # Create missing tags for this product
        Tag.create_for_product(product)

        # Generate new private UUID and set private flag
        if form.is_private.data:
            product.set_private()

        # Add product to search index
        search.product_updated.send(product=product)

        flash('Product has been successfully edited', 'success')
        #return redirect(url_for('account.seller_products'))
        return redirect(url_for('product', product_id=product_id, product_title=product.get_title_seofied()))

    return render_template('account/edit_product.html', form=form, product=product, categories=categories)


@account.route('/account/products/<int:product_id>/photos', methods=['GET', 'POST'])
@login_required
def product_photos(product_id):
    product = Product.query.get_or_404(product_id)

    if product.seller_id != g.user.id:
        # User attempted to edit a product he doesn't own
        abort(403)

    form = NewProductPhotoForm()
    if form.validate_on_submit():
        storage = Storage()
        photo_aws_key, photo_cloudinary_key = storage.upload_product_photo(form.photo.data, product.id, product.get_title_seofied())

        product_photos = product.get_data('photos')
        if not product_photos:
            product_photos = list()

        product_photos.append(dict(aws_key=photo_aws_key, cloudinary_key=photo_cloudinary_key))
        product.set_data('photos', product_photos)

        db.session.add(product)
        db.session.commit()

        return redirect(url_for('account.product_photos', product_id=product_id))

    return render_template('account/edit_product_photos.html', product=product, form=form)


@account.route('/account/product/<int:product_id>/photos/<int:index>/delete')
@login_required
def product_photos_delete(product_id, index):
    # TODO: make confirmation page and delete on POST request
    product = Product.query.get_or_404(product_id)

    if product.seller_id != g.user.id:
        # User attempted to delete a product he doesn't own
        abort(403)

    product_photos = product.get_data('photos')
    if not product_photos or len(product_photos) < index + 1:
        abort(404)

    product_photo_to_remove = product_photos[index]

    storage = Storage()
    storage.delete_product_photo(product_photo_to_remove['aws_key'], product_photo_to_remove['cloudinary_key'])
    
    product_photos.remove(product_photo_to_remove)
    product.set_data('photos', product_photos)

    db.session.add(product)
    db.session.commit()

    return redirect(url_for('account.product_photos', product_id=product.id))


@account.route('/account/product/<int:product_id>/photos/<int:index>/setprimary')
@login_required
def product_photos_setprimary(product_id, index):
    # TODO: make confirmation page and delete on POST request
    product = Product.query.get_or_404(product_id)

    if product.seller_id != g.user.id:
        # User attempted to delete a product he doesn't own
        abort(403)

    product_photos = product.get_data('photos')
    if not product_photos or len(product_photos) < index + 1:
        abort(404)

    product_photo_to_move = product_photos[index]
    product_photos.remove(product_photo_to_move)
    product_photos.insert(0, product_photo_to_move)

    product.set_data('photos', product_photos)

    db.session.add(product)
    db.session.commit()

    return redirect(url_for('account.product_photos', product_id=product.id))


@account.route('/account/product/<int:product_id>/disable')
@login_required
def product_disable(product_id):
    # TODO: make confirmation page and delete on POST request
    product = Product.query.get_or_404(product_id)

    if product.seller_id != g.user.id:
        # User attempted to delete a product he doesn't own
        abort(403)

    product.is_disabled = True

    db.session.add(product)
    db.session.commit()

    search.product_deleted.send(product=product)

    flash('Product has been disabled', 'success')
    return redirect(url_for('account.seller_products'))


@account.route('/account/product/<int:product_id>/enable')
@login_required
def product_enable(product_id):
    # TODO: make confirmation page and delete on POST request
    product = Product.query.get_or_404(product_id)

    if product.seller_id != g.user.id:
        # User attempted to delete a product he doesn't own
        abort(403)

    product.is_disabled = False

    search.product_updated.send(product=product)

    db.session.add(product)
    db.session.commit()

    flash('Product has been enabled', 'success')
    return redirect(url_for('account.seller_products'))


@account.route('/account/orders/<int:order_id>/accept')
@login_required
def order_accept(order_id):
    # TODO: change by POST request
    order = Order.query.get_or_404(order_id)

    if g.user.id != order.product.seller_id or order.state != Order.NEW:
        abort(403)

    order.change_state(Order.ACCEPTED, g.user)
    flash('Order accepted - You have time {time} for delivery product else buyer well be automatic refound.'.format(time=order.get_deadline_interval()),'success')

    return redirect(url_for('account.seller_orders', state='accepted'))


@account.route('/account/orders/<int:order_id>/reject')
@login_required
def order_reject(order_id):
    # TODO: change by POST request
    order = Order.query.get_or_404(order_id)

    if g.user.id != order.product.seller_id or order.state != Order.NEW:
        abort(403)

    order.change_state(Order.CLOSED_REJECTED, g.user)

    return redirect(url_for('account.seller_orders', state='done'))


@account.route('/account/orders/<int:order_id>/cancel')
@login_required
def order_cancel(order_id):
    # TODO: change by POST request
    order = Order.query.get_or_404(order_id)

    if g.user.id != order.buyer_id or order.state not in (Order.NEW, Order.ACCEPTED, Order.SENT):
        abort(403)

    order.change_state(Order.CLOSED_CANCELLED, g.user)

    return redirect(url_for('account.buyer_orders'))


@account.route('/account/orders/<int:order_id>/ship', methods=['POST'])
@login_required
def order_ship(order_id):
    order = Order.query.get_or_404(order_id)

    if g.user.id != order.product.seller_id or order.state != Order.ACCEPTED:
        abort(403)

    private_message = request.form.get('private_message')
    if private_message:
        # Attach private message if specified
        order.private_message = private_message

    order.change_state(Order.SENT, g.user)

    return redirect(url_for('account.seller_orders', state='inprogress'))


@account.route('/account/orders/<int:order_id>/complete')
@login_required
def order_complete(order_id):
    # TODO: change by POST request
    order = Order.query.get_or_404(order_id)

    if g.user.id != order.buyer_id or order.state != Order.SENT:
        abort(403)

    order.change_state(Order.CLOSED_COMPLETED, g.user)

    search.product_updated.send(product=order.product)

    return redirect(url_for('account.buyer_orders'))


@account.route('/account/orders/<int:order_id>/dispute')
@login_required
def order_dispute(order_id):
    # TODO: change by POST request
    order = Order.query.get_or_404(order_id)

    if g.user.id != order.buyer_id or order.state != Order.SENT:
        abort(403)

    dispute = Dispute(user_id=g.user.id, order_id=order.id)
    db.session.add(dispute)
    db.session.commit()

    order.change_state(Order.DISPUTE, g.user)

    return redirect(url_for('account.buyer_dispute', dispute_id=dispute.id))


@account.route('/account/tickets')
@login_required
def tickets():
    tickets = Ticket.query.filter_by(is_deleted=False, user_id=g.user.id).order_by(Ticket.is_closed.asc(), Ticket.created_on.desc())

    return render_template('account/tickets.html', tickets=tickets)


@account.route('/account/tickets/new', methods=['GET', 'POST'])
@login_required
def ticket_new():
    if request.method == 'POST':
        subject = request.form.get('subject')
        text = request.form.get('text')
        if text:
            ticket = Ticket(user_id=g.user.id, text=text, subject=subject)
            db.session.add(ticket)
            db.session.commit()

            flash('Report abuse successful send!', 'success')

            return redirect(request.referrer)
            #return redirect(url_for('account.ticket', ticket_id=ticket.id))

    return render_template('account/new_ticket.html')



@account.route('/account/tickets/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    if g.user.id != ticket.user_id:
        abort(403)

    return render_template('account/ticket.html', ticket=ticket)


@account.route('/account/buyer/dispute/<int:dispute_id>')
@login_required
def buyer_dispute(dispute_id):
    dispute = Dispute.query.get_or_404(dispute_id)

    if g.user.id not in (dispute.user_id, dispute.get_product().seller_id):
        abort(403)

    return render_template('account/buyer_dispute.html', dispute=dispute)


@account.route('/account/seller/dispute/<int:dispute_id>')
@login_required
def seller_dispute(dispute_id):
    dispute = Dispute.query.get_or_404(dispute_id)

    if g.user.id not in (dispute.user_id, dispute.get_product().seller_id):
        abort(403)

    return render_template('account/seller_dispute.html', dispute=dispute)

@account.route('/account/disputes/<int:dispute_id>/resolve')
@login_required
def dispute_resolve(dispute_id):
    dispute = Dispute.query.get_or_404(dispute_id)

    if dispute.deadline_passed or g.user.id not in (dispute.user_id, dispute.get_product().seller_id):
        abort(403)

    dispute.resolve(g.user)

    return redirect(url_for('account.dispute', dispute_id=dispute_id))


@account.route('/account/tickets/<int:ticket_id>/close')
@login_required
def ticket_close(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    if g.user.id != ticket.user_id:
        abort(403)

    ticket.close()

    return redirect(url_for('account.tickets'))


@account.route('/account/tickets/<int:ticket_id>/delete')
@login_required
def ticket_delete(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    if g.user.id != ticket.user_id:
        abort(403)

    ticket.delete()

    return redirect(url_for('account.tickets'))


@account.route('/account/seller/disputes')
@login_required
def seller_disputes():
    page = request.args.get('page', 1, type=int)

    disputes = Dispute.query \
                      .join(Order) \
                      .join(Product) \
                      .filter(Product.seller_id==g.user.id) \
                      .order_by(Dispute.is_closed.asc(), Dispute.created_on.desc())

    pagination = disputes.paginate(page, per_page=TRANSACTIONS_PER_PAGE)

    return render_template('account/disputes.html', pagination=pagination, mode='seller')


@account.route('/account/buyer/disputes')
@login_required
def buyer_disputes():
    page = request.args.get('page', 1, type=int)

    disputes = Dispute.query \
                      .filter(Dispute.user_id==g.user.id) \
                      .order_by(Dispute.is_closed.asc(), Dispute.created_on.desc())

    pagination = disputes.paginate(page, per_page=TRANSACTIONS_PER_PAGE)

    return render_template('account/disputes.html', pagination=pagination, mode='buyer')


@account.route('/account/orders/<int:order_id>/feedback', methods=['GET', 'POST'])
@login_required
def feedback_new(order_id):
    type = request.args.get('type', type=int)

    if type not in (Feedback.ON_BUYER, Feedback.ON_SELLER):
        abort(404)

    order = Order.query.get_or_404(order_id)

    if (type == Feedback.ON_SELLER) and g.user.id != order.buyer_id:
        # User can't leave product or seller feedback for this purchase
        abort(403)

    if type == Feedback.ON_BUYER and g.user.id != order.product.seller_id:
        # User can't leave buyer feedback for this purchase
        abort(403)

    if request.method == 'POST':
        rating = request.form.get('rating', type=int)
        text = request.form.get('text')
        if text and rating in (Feedback.NEGATIVE, Feedback.NEUTRAL, Feedback.POSITIVE):
            feedback = Feedback(type=type, user_id=g.user.id, rating=rating, text=text, order_id=order.id)
            db.session.add(feedback)
            db.session.commit()
            
            flash('Feedback successful rated for OrderID #{OrderID} '.format(OrderID=order.id), 'success')

            redirect_route = 'account.seller_orders' if type == Feedback.ON_BUYER else 'account.buyer_orders'

            return redirect(url_for(redirect_route))

    return render_template('account/new_feedback.html', type=type, order=order)


@account.route('/account/feedback/<int:feedback_id>/reply', methods=['POST'])
@login_required
def feedback_reply(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)

    if feedback.type == Feedback.ON_SELLER and g.user.id != feedback.order.product.seller_id:
        # User can't reply on this feedback
        abort(403)

    if feedback.type == Feedback.ON_BUYER and g.user.id != feedback.order.buyer_id:
        # User can't reply on this feedback
        abort(403)

    reply = request.form.get('reply')

    if reply:
        feedback.reply = reply
        db.session.add(feedback)
        db.session.commit()

    redirect_route = 'account.seller_feedbacks' if feedback.type == Feedback.ON_SELLER else 'account.buyer_feedbacks'

    return redirect(url_for(redirect_route))


@account.route('/account/settings.html', methods=['GET', 'POST'])
@login_required
def settings_old():
    action = request.args.get('action')

    password_form = PasswordChangeForm()
    if action == 'change_password' and password_form.validate_on_submit():
        g.user.password = password_form.password.data
        db.session.add(g.user)
        db.session.commit()

        flash('Password has been changed', 'success')
        return redirect(url_for('account.settings'))

    profile_description_form = ProfileForm(profile_description=g.user.profile_description)
    if action == 'profile_description' and profile_description_form.validate_on_submit():
        g.user.profile_description = profile_description_form.profile_description.data
        db.session.add(g.user)
        db.session.commit()

        flash('Profile has been updated', 'success')
        return redirect(url_for('account.settings'))

    profile_photo_form = ProfilePhotoForm()
    if action == 'profile_photo' and profile_photo_form.validate_on_submit():
        if profile_photo_form.photo.data:
            storage = Storage()
            photo_data = g.user.get_photo_data()
            if photo_data:
                storage.delete_profile_photo(**photo_data)

            aws_key, cloudinary_key = storage.upload_profile_photo(profile_photo_form.photo.data, str(g.user.id), str(g.user.id))
            g.user.set_photo_data(dict(aws_key=aws_key, cloudinary_key=cloudinary_key))
            
            db.session.add(g.user)
            db.session.commit()

            flash('Photo has been changed', 'success')

        return redirect(url_for('account.settings'))

    delete_account_form = DeleteAccountForm()
    if action == 'delete_account' and delete_account_form.validate_on_submit():
        g.user.is_deleted = True
        db.session.add(g.user)
        db.session.commit()

        return redirect(url_for('account.settings'))

    return render_template('account/settings.html', profile_description_form=profile_description_form, password_form=password_form, delete_account_form=delete_account_form, profile_photo_form=profile_photo_form)


@account.route('/account/newsletter.html', methods=['GET', 'POST'])
@login_required
def settings_email():
    form = EmailSettingsForm(is_newsletter_enabled=g.user.is_newsletter_enabled,
                             is_sales_report_enabled=g.user.is_sales_report_enabled,
                             is_marketplace_digest_enabled=g.user.is_marketplace_digest_enabled)

    if form.validate_on_submit():
        g.user.is_newsletter_enabled = form.is_newsletter_enabled.data
        g.user.is_sales_report_enabled = form.is_sales_report_enabled.data
        g.user.is_marketplace_digest_enabled = form.is_marketplace_digest_enabled.data
        db.session.add(g.user)
        db.session.commit()

        flash('Newsletter options have been updated', 'success')
        return redirect(url_for('account.settings_email'))

    return render_template('account/settings_email.html', form=form)


@account.route('/account/two_factor_auth', methods=['GET', 'POST'])
@login_required
def two_factor_auth():
    form = TwoFactorAuthForm(enabled=g.user.is_two_factor_enabled)

    if form.validate_on_submit():
        g.user.is_two_factor_enabled = bool(form.enabled.data)

        db.session.add(g.user)
        db.session.commit()

        flash('2-FA has been {0}'.format('enabled' if g.user.is_two_factor_enabled else 'disabled', 'success'))
        return redirect(url_for('account.two_factor_auth'))

    return render_template('account/two_factor_auth.html', form=form)


@account.route('/account/profile.html', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm(profile_description=g.user.profile_description)

    if form.validate_on_submit():
        g.user.profile_description = form.profile_description.data
        db.session.add(g.user)
        db.session.commit()

        flash('Profile has been updated', 'success')
        return redirect(url_for('account.settings'))

    return render_template('account/profile.html', form=form)


@account.route('/account/news')
@login_required
def news():
    page = request.args.get('page', 1, type=int)

    news = Content.query_published_member_news()
    pagination = news.paginate(page, per_page=TRANSACTIONS_PER_PAGE)

    return render_template('account/news.html', pagination=pagination)


@account.route('/account/balance.html', methods=['GET', 'POST'])
@login_required
def balance_old():
    address = g.user.request_bitcoin_address()

    formWithdraw = WithdrawBTCForm()
    if formWithdraw.validate_on_submit():
        amount_withdraw = long(formWithdraw.amount.data * 100000000L)

        info = dict(address=formWithdraw.address.data)

        Withdrawal.request_btc(user=g.user,
                               amount=amount_withdraw,
                               info=info)

        flash('Withdrawal has been requested', 'warning')
        return redirect(url_for('account.balance'))

    form2 = TransferFundsForm()
    if form2.validate_on_submit():
        amount = long(form2.amount.data * 100)
        recipient = User.get_active_by_username(form2.recipient.data)
        if not recipient:
            abort(404)

        Transaction.transfer_transaction(sender=g.user,
                                         recipient=recipient,
                                         amount=amount,
                                         note=form2.note.data)

        flash('Funds have been sent', 'success')
        return redirect(url_for('account.deposit_btc'))

    #tranzaction tab
    page = request.args.get('page', 1, type=int)
    transactions = Transaction.query \
                              .filter_by(user_id=g.user.id) \
                              .order_by(Transaction.created_on.desc())

    pagination = transactions.paginate(page, per_page=TRANSACTIONS_PER_PAGE)

    return render_template('account/deposit_btc.html', form1=formWithdraw, form2=form2,  address=address, pagination=pagination)


@account.route('/account/withdraw/btc', methods=['GET', 'POST'])
@login_required
def withdraw_btc():
    form = WithdrawBTCForm()
    if form.validate_on_submit():
        amount = long(form.amount.data * 100000000L)

        info = dict(address=form.address.data)

        Withdrawal.request_btc(user=g.user,
                               amount=amount,
                               info=info)

        flash('Withdrawal has been requested','warning')
        return redirect(url_for('account.withdraw_btc'))

    withdrawals = Withdrawal.query_requests().filter_by(user_id=g.user.id, type=Withdrawal.BTC)

    return render_template('account/withdraw_btc.html', form=form, withdrawals=withdrawals)


@account.route('/account/withdraw/wu', methods=['GET', 'POST'])
@login_required
def withdraw_wu():
    wu_enabled = Variable.get_wu_enabled()

    form = WithdrawWUForm()
    if wu_enabled and request.method == 'POST':
        if form.validate_on_submit():
            info = dict(first_name=form.first_name.data,
                        last_name=form.last_name.data,
                        middle_name=form.middle_name.data if form.middle_name.data else '-',
                        country=form.country.data,
                        city=form.city.data)

            Withdrawal.request_western_union(user=g.user,
                                             amount_usd=form.amount.data,
                                             info=info)

            resp = dict(error=None)
        else:
            if form.amount.errors:
                resp = dict(error_step=1, error="\n".join(form.amount.errors))
            else:
                resp = dict(error_step=2, error='Please fill in all necessary fields')

        return Response(json.htmlsafe_dumps(resp),  mimetype='application/json')

    withdrawals = Withdrawal.query_requests().filter_by(user_id=g.user.id, type=Withdrawal.WESTERN_UNION)

    return render_template('account/withdraw_wu.html', form=form, withdrawals=withdrawals, wu_enabled=wu_enabled)


@account.route('/account/transfer_funds', methods=['GET', 'POST'])
@login_required
def transfer_funds():
    form = TransferFundsForm()
    if form.validate_on_submit():
        amount = long(form.amount.data * 100000000L)
        recipient = User.get_active_by_username(form.recipient.data)
        if not recipient:
            abort(404)

        Transaction.transfer_transaction(sender=g.user,
                                         recipient=recipient,
                                         amount=amount,
                                         note=form.note.data)

        flash('Funds have been sent', 'success')
        return redirect(url_for('account.transfer_funds'))

    return render_template('account/transfer_funds.html', form=form)


@account.route('/account/favorites.html')
@login_required
def favorites_old():
    return redirect(url_for('account.favorite_items'))


@account.route('/account/favorites-items.html')
@login_required
def favorite_items():
    page = request.args.get('page', 1, type=int)
    state = request.args.get('state')


    favorites = FavoriteProduct.query.filter_by(user_id=g.user.id).order_by(FavoriteProduct.created_on.desc())
    pagination = favorites.paginate(page, per_page=TRANSACTIONS_PER_PAGE)

    return render_template('account/favorites-items.html', pagination=pagination, mode='items')


@account.route('/account/favorite-searches.html')
@login_required
def favorite_search():
    page = request.args.get('page', 1, type=int)

    favorites = FavoriteSearch.query.filter_by(user_id=g.user.id).order_by(FavoriteSearch.created_on.desc())
    pagination = favorites.paginate(page, per_page=TRANSACTIONS_PER_PAGE)

    return render_template('account/favorites-search.html', pagination=pagination, mode='searches')


@account.route('/account/favorite/items/<int:product_id>/toggle')
@login_required
def favorite_items_toggle(product_id):
    product = Product.query.get_or_404(product_id)

    if product.is_deleted or product.seller.is_deleted:
        abort(404)

    # TODO: check if product is private and check user rights then

    FavoriteProduct.toggle(g.user.id, product.id)

    return redirect(request.args.get('next') or url_for('product', product_id=product_id, product_title=product.get_title_seofied()))


@account.route('/account/favorite/searches/toggle')
@login_required
def favorite_searches_toggle():
    q = request.args.get('q', '')
    # category_id = request.args.get('category_id', 0, type=int)

    if not q:
        return redirect(url_for('index'))

    FavoriteSearch.toggle(g.user.id, q)

    return redirect(request.args.get('next') or url_for('index', q=q))


@account.route('/account/favorite/searches/<int:favorite_search_id>/go')
@login_required
def favorite_searches_go(favorite_search_id):
    favorite_search = FavoriteSearch.query.get_or_404(favorite_search_id)

    if favorite_search.user_id != g.user.id:
        abort(404)

    favorite_search.update()

    return redirect(url_for('index', q=favorite_search.q))


@account.route('/account/voucher/activate', methods=['POST'])
@login_required
def voucher_activate():
    voucher_type = request.args.get('type')

    form = VoucherActivateForm()

    if voucher_type == Voucher.PREMIUM_MEMBER:
        redirect_url = url_for('account.premium')
        if form.validate_on_submit():
            success, exists = Voucher.use(type=Voucher.PREMIUM_MEMBER, code=form.code.data)
            if success:
                g.user.premium_member = True
                db.session.add(g.user)
                db.session.commit()

                return redirect(redirect_url)
            else:
                if exists:
                    flash('Voucher code has been already used', 'success')
                else:
                    flash('Invalid voucher code', 'danger')
        else:
            flash('Invalid voucher code', 'danger')

    elif voucher_type == Voucher.SELLER:
        redirect_url = url_for('account.seller_fee')
        if form.validate_on_submit():
            success, exists = Voucher.use(type=Voucher.SELLER, code=form.code.data)
            if success:
                g.user.seller_fee_paid = True
                db.session.add(g.user)
                db.session.commit()

                flash('Warning! You received free right seller, you get 3 days to place a product on sale or selling the right will be deleted');
                return redirect(redirect_url)
            else:
                if exists:
                    flash('Voucher code has been already used', 'danger')
                else:
                    flash('Invalid voucher code', 'danger')
        else:
            flash('Invalid voucher code', 'danger')

    else:
        abort(403)

    return redirect(redirect_url)


@account.route('/account/seller/offers.html', methods=['GET', 'POST'])
@login_required
def seller_offers():
    page = request.args.get('page', 1, type=int)

    offers = ProductOffer.query.filter(ProductOffer.product_id==Product.id).filter(Product.seller_id==g.user.id).order_by(ProductOffer.created_on.desc())

    pagination = offers.paginate(page, per_page=TRANSACTIONS_PER_PAGE)

    products = g.user.products.filter(Product.is_deleted!=True, Product.is_approved==True).order_by(Product.created_on.desc())
    form = NewOfferForm()

    if form.validate_on_submit():
        value = form.value.data * 100 if form.type.data == ProductOffer.ABSOLUTE else form.value.data

        product_offer = ProductOffer(product_id=form.product_id.data,
                                     type=form.type.data,
                                     value=value,
                                     start_date=form.start_date.data,
                                     end_date=form.end_date.data)

        db.session.add(product_offer)
        db.session.commit()

        if (product_offer.start_date - date.today()).days <= 0 and (product_offer.end_date - date.today()).days >= 0:
            product = product_offer.get_product()
            product.set_active_offer(product_offer)
            search.product_updated.send(product=product)

        flash('Offer has been created', 'success')
        return redirect(url_for('account.seller_offers'))

    return render_template('account/offers.html', pagination=pagination, form=form, products=products)


@account.route('/account/seller/offers/<int:offer_id>/delete')
@login_required
def seller_offer_delete(offer_id):
    offer = ProductOffer.query.get_or_404(offer_id)
    product = offer.get_product()

    if product.seller_id != g.user.id:
        abort(403)

    if product.active_offer_id == offer_id:
        product.set_active_offer(None)
        search.product_updated.send(product=product)

    db.session.delete(offer)
    db.session.commit()

    return redirect(url_for('account.seller_offers'))


@account.route('/account/seller/discounts.html', methods=['GET', 'POST'])
@login_required
def seller_discounts():
    page = request.args.get('page', 1, type=int)

    discounts = Discount.query.filter_by(seller_id=g.user.id).order_by(Discount.created_on.desc())

    pagination = discounts.paginate(page, per_page=TRANSACTIONS_PER_PAGE)

    products = g.user.products.filter(Product.is_deleted!=True, Product.is_approved==True).order_by(Product.created_on.desc())
    form = NewDiscountForm()

    if form.validate_on_submit():
        value = form.value.data * 100 if form.type.data == Discount.ABSOLUTE else form.value.data

        Discount.add(seller=g.user,
                     product_id=form.product_id.data,
                     type=form.type.data,
                     value=value)

        flash('Discount code has been created', 'success')
        return redirect(url_for('account.seller_discounts'))

    return render_template('account/discounts.html', pagination=pagination, form=form, products=products)


@account.route('/account/seller/discounts/<int:discount_id>/delete')
@login_required
def seller_discount_delete(discount_id):
    discount = Discount.query.get_or_404(discount_id)

    if discount.seller_id != g.user.id:
        abort(403)

    db.session.delete(discount)
    db.session.commit()

    return redirect(url_for('account.seller_discounts'))


@account.route('/account/affiliate/links.html')
@login_required
def affiliate_links():
    return render_template('account/affiliate/links.html');


@account.route('/account/affiliate/invite.html', methods=['GET', 'POST'])
@login_required
def affiliate_code():
    page = request.args.get('page', 1, type=int)
    vouchers = Voucher.query.filter_by(is_invite=True, user_id=g.user.id).order_by(Voucher.used_count.asc(), Voucher.created_on.desc())

    pagination = vouchers.paginate(page, per_page=PRODUCTS_PER_PAGE)

    form = NewInviteForm()

    if form.validate_on_submit():
        Voucher.add(g.user, type=form.type.data, is_invite=True, total_count=1)

        flash('Invite has been created', 'success')
        return redirect(url_for('account.affiliate_code'))

    return render_template('account/affiliate/code.html', pagination=pagination, form=form);


@account.route('/account/affiliate/code/<int:voucher_id>/delete', methods=['GET', 'POST'])
@login_required
def affiliate_code_delete(voucher_id):
    voucher = Voucher.query.get_or_404(voucher_id)

    if voucher.user_id != g.user.id:
        abort(403)

    db.session.delete(voucher)
    db.session.commit()

    return redirect(url_for('account.affiliate_code'))


@account.route('/account/affiliate/earnings.html')
@login_required
def affiliate_statistics():
    page = request.args.get('page', 1, type=int)

    transactions = Transaction.query \
                              .filter_by(user_id=g.user.id) \
                              .filter_by(type=Transaction.AFFILIATE_COMISSION) \
                              .order_by(Transaction.created_on.desc())

    pagination = transactions.paginate(page, per_page=TRANSACTIONS_PER_PAGE)

    return render_template('account/affiliate/statistics.html', pagination=pagination)


@account.route('/account/affiliate/users.html')
@login_required
def affiliates():
    page = request.args.get('page', 1, type=int)

    users = User.query \
                       .filter_by(referer_id=g.user.id) \
                       .order_by(User.registered_on.desc())

    pagination = users.paginate(page, per_page=TRANSACTIONS_PER_PAGE)

    return render_template('account/affiliate/users.html', pagination=pagination)
