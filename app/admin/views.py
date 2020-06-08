from flask import request, flash, url_for, redirect, g, abort, render_template, json, Response, escape, session

from app.models import db, Category, Ticket, Order, BitcoinAddress, Transaction, User, Dispute, \
    Product, Content, Withdrawal, Variable, Newsletter, Voucher, Tag, AffiliateLink, Report, UserVerification, \
    UserVerificationPhoto
from app.decorators import admin_required
from app import search
from app.utils.storage import Storage
from . import admin
from .forms import EmailChangeForm, DepositUserForm, NewsForm, PasswordChangeForm, NewVoucherForm, NewAffiliateLinkForm

ORDERS_PER_PAGE = 20
USER_VERIFICATIONS_PER_PAGE = 20
USERS_PER_PAGE = 20
ADDRESSES_PER_PAGE = 30
WITHDRAWALS_PER_PAGE = 20


@admin.before_request
def before_request():
    g.admin_opened_tickets_count = Ticket.query_opened().count()
    g.admin_opened_disputes_count = Dispute.query_opened().count()
    g.admin_new_orders_count = Order.query.filter_by(state=Order.NEW).count()
    g.admin_verification_orders_count = Order.query.filter_by(state=Order.NEW, is_pending_verification=True).count()
    g.admin_users_count = User.query.count()
    g.admin_products_count = Product.query.filter(Product.is_deleted != True, Product.published_on != None).count()
    g.admin_verification_products_count = Product.query.filter(Product.is_deleted != True, Product.is_approved != True,
                                                               Product.not_approved != True,
                                                               Product.published_on != None).count()
    g.admin_news_count = Content.query.filter_by(type=Content.MEMBER_NEWS).count()
    g.admin_withdrawals_count = Withdrawal.query_requests(all=False).count()
    g.admin_free_addresses_count = BitcoinAddress.query.filter_by(user_id=None).count()
    g.admin_newsletters_count = Newsletter.query.filter_by(is_sent=False).count()
    g.admin_pending_user_verifications = UserVerification.query. \
        filter(UserVerification.state == UserVerification.PENDING).count()


@admin.route('/admin/test_email/<template>')
@admin_required
def test_email(template):
    args = {k: request.args[k] for k in request.args}
    result = render_template('email/%s' % template, **args)
    return Response(result, mimetype='text/plain' if template.endswith('txt') else 'text/html')


@admin.route('/admin/')
@admin_required
def index():
    return redirect(url_for('admin.tickets'))


@admin.route('/admin/verifications')
@admin_required
def user_verifications():
    page = request.args.get('page', 1, type=int)
    pending = UserVerification.query.filter_by(state=UserVerification.PENDING). \
        order_by(UserVerification.created_on.asc())
    pagination = pending.paginate(page, per_page=USER_VERIFICATIONS_PER_PAGE)
    return render_template('admin/user_verifications.html', pagination=pagination)


@admin.route('/admin/verifications/<int:user_id>')
@admin_required
def user_verification(user_id):
    verification = UserVerification.query.get_or_404(user_id)
    photos = UserVerificationPhoto.query.filter_by(user_id=user_id).all()
    return render_template('admin/user_verification.html', verification=verification, photos=photos)


@admin.route('/admin/verifications/<int:user_id>/<any(rejected,completed):action>', methods=('POST',))
@admin_required
def user_verification_post(user_id, action):
    verification = UserVerification.query.get_or_404(user_id)
    verification.state = action
    db.session.add(verification)
    if action == UserVerification.REJECTED:  # hide all photos !
        db.engine.execute("UPDATE user_verification_photos SET hidden=1 WHERE hidden=0 AND user_id=%s;", (user_id,))
    db.session.commit()
    return redirect(url_for('admin.user_verifications'))


@admin.route('/admin/orders')
@admin_required
def orders():
    page = request.args.get('page', 1, type=int)
    orders = Order.query.order_by(Order.created_on.desc())

    pagination = orders.paginate(page, per_page=ORDERS_PER_PAGE)

    return render_template('admin/orders.html', pagination=pagination)


@admin.route('/admin/orders/pending')
@admin_required
def orders_pending_verification():
    page = request.args.get('page', 1, type=int)
    orders = Order.query.filter_by(state=Order.NEW, is_pending_verification=True).order_by(Order.created_on.desc())

    pagination = orders.paginate(page, per_page=ORDERS_PER_PAGE)

    return render_template('admin/orders_pending.html', pagination=pagination)


@admin.route('/admin/orders/pending/<int:order_id>')
@admin_required
def order_pending(order_id):
    order = Order.query.get_or_404(order_id)

    if not order.is_pending_verification:
        return redirect(url_for('admin.orders_pending'))

    return render_template('admin/order_pending.html', order=order)


@admin.route('/admin/orders/pending/<int:order_id>/accept')
@admin_required
def order_pending_accept(order_id):
    order = Order.query.get_or_404(order_id)

    if not order.is_pending_verification:
        return redirect(url_for('admin.orders_pending_verification'))

    order.is_pending_verification = False
    db.session.add(order)
    db.session.commit()

    return redirect(url_for('admin.orders_pending_verification'))


@admin.route('/admin/orders/pending/<int:order_id>/reject')
@admin_required
def order_pending_reject(order_id):
    order = Order.query.get_or_404(order_id)

    if not order.is_pending_verification:
        return redirect(url_for('admin.orders_pending_verification'))

    order.change_state(new_state=Order.CLOSED_CANCELLED, user=g.user)

    return redirect(url_for('admin.orders_pending_verification'))


@admin.route('/admin/disputes')
@admin_required
def disputes():
    page = request.args.get('page', 1, type=int)

    disputes = Dispute.query \
        .order_by(Dispute.is_closed.asc(), Dispute.created_on.asc())

    pagination = disputes.paginate(page, per_page=ORDERS_PER_PAGE)

    return render_template('admin/disputes.html', pagination=pagination)


@admin.route('/admin/disputes/<int:dispute_id>')
@admin_required
def dispute(dispute_id):
    dispute = Dispute.query.get_or_404(dispute_id)

    order = dispute.get_order()

    return render_template('admin/dispute.html', dispute=dispute, order=order)


@admin.route('/admin/disputes/<int:dispute_id>/moneyback')
@admin_required
def dispute_moneyback(dispute_id):
    dispute = Dispute.query.get_or_404(dispute_id)

    # Emulating resolution by seller
    # Which means moneyback
    dispute.resolve(dispute.order.product.seller, force_resolution_kind='cancel', by_admin=True)

    return redirect(url_for('admin.disputes'))


@admin.route('/admin/disputes/<int:dispute_id>/close')
@admin_required
def dispute_close(dispute_id):
    dispute = Dispute.query.get_or_404(dispute_id)

    # Emulating resolution by the originator
    # Which means completion of the order
    dispute.resolve(dispute.order.buyer, force_resolution_kind='complete', by_admin=True)

    return redirect(url_for('admin.disputes'))


@admin.route('/admin/tickets')
@admin_required
def tickets():
    tickets = Ticket.query.order_by(Ticket.is_closed.asc(), Ticket.created_on.desc())
    reports = Report.query.order_by(Report.is_closed.asc(), Report.created_on.desc())
    return render_template('admin/tickets.html', tickets=tickets, reports=reports)


@admin.route('/admin/tickets/<int:ticket_id>')
@admin_required
def ticket(ticket_id):
    ticket = Ticket.query.get(ticket_id)

    # ticket.read()
    db.session.add(ticket)
    db.session.commit()

    if not ticket:
        abort(404)

    return render_template('admin/ticket.html', ticket=ticket)


@admin.route('/admin/tickets/<int:ticket_id>/close')
@admin_required
def ticket_close(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    ticket.close()

    return redirect(url_for('admin.tickets'))


@admin.route('/admin/reports/<int:report_id>')
@admin_required
def report(report_id):
    report = Report.query.get_or_404(report_id)
    return render_template('admin/report.html', report=report)


@admin.route('/admin/reports/<int:report_id>/close')
@admin_required
def report_close(report_id):
    report = Report.query.get_or_404(report_id)
    report.close()
    return redirect(url_for('admin.tickets'))


@admin.route('/admin/categories')
@admin_required
def categories():
    categories = Category.query_top()

    return render_template('admin/categories.html', categories=categories)


@admin.route('/admin/categories/new', methods=['POST'])
@admin_required
def categories_new():
    title = request.form.get('title')
    description = request.form.get('description')
    parent_id = request.form.get('parent_id', type=int)

    if not title:
        flash('Please enter a title')
        return redirect(url_for('admin.categories'))

    category = Category(title=title, description=description)
    if parent_id:
        category.parent_id = parent_id

    db.session.add(category)
    db.session.commit()

    flash("Category has been added")
    return redirect(url_for('admin.categories'))


@admin.route('/admin/categories/<int:category_id>/delete')
@admin_required
def categories_delete(category_id):
    category = Category.query.get(category_id)

    if not category:
        flash("Category with ID %s not found" % category_id)
        return redirect(url_for('admin.categories'))

    db.session.delete(category)
    db.session.commit()

    flash("Category has been deleted")
    return redirect(url_for('admin.categories'))


@admin.route('/admin/users')
@admin_required
def users():
    page = request.args.get('page', 1, type=int)
    search_term = request.args.get('q')

    users_query = User.query
    if search_term:
        users_query = users_query.filter_by(username=search_term)

    users = users_query.order_by(User.registered_on.desc())
    pagination = users.paginate(page, per_page=ADDRESSES_PER_PAGE)

    return render_template('admin/users.html', pagination=pagination)


@admin.route('/admin/users/export')
@admin_required
def users_export():
    export_type = request.args.get('type')
    if export_type == 'newsletter':
        users = User.query.filter(User.is_deleted != True, User.is_newsletter_enabled == True)
        rows = (','.join((user.username, user.email)) for user in users)
        result = '\n'.join(rows)
    else:
        result = ''

    return Response(result, mimetype='text/csv')


@admin.route('/admin/users/<int:user_id>')
@admin_required
def user(user_id):
    user = User.query.get_or_404(user_id)

    password_form = PasswordChangeForm()

    last_error = session.pop('last_error', None)
    last_error_type = request.args.get('last_error_type')

    return render_template('admin/user.html', user=user, password_form=password_form, last_error=last_error,
                           last_error_type=last_error_type)


@admin.route('/admin/users/<int:user_id>/deactivate')
@admin_required
def user_deactivate(user_id):
    user = User.query.get_or_404(user_id)

    user.is_disabled = True
    db.session.add(user)

    db.session.commit()

    return redirect(url_for('admin.user', user_id=user.id))


@admin.route('/admin/users/<int:user_id>/activate')
@admin_required
def user_activate(user_id):
    user = User.query.get_or_404(user_id)

    user.is_disabled = False
    db.session.add(user)
    db.session.commit()

    return redirect(url_for('admin.user', user_id=user.id))


@admin.route('/admin/users/<int:user_id>/sell')
@admin_required
def user_enable_seller(user_id):
    user = User.query.get_or_404(user_id)

    user.seller_fee_paid = True
    db.session.add(user)
    db.session.commit()

    flash('Seller enabled')
    return redirect(url_for('admin.user', user_id=user_id))


@admin.route('/admin/users/<int:user_id>/sell_disable')
@admin_required
def user_disable_seller(user_id):
    user = User.query.get_or_404(user_id)

    user.seller_fee_paid = False
    db.session.add(user)
    db.session.commit()

    flash('Seller disable')
    return redirect(url_for('admin.user', user_id=user_id))


@admin.route('/admin/users/<int:user_id>/change_email', methods=['GET', 'POST'])
@admin_required
def user_change_email(user_id):
    user = User.query.get_or_404(user_id)

    form = EmailChangeForm()
    if form.validate_on_submit():
        user.email = form.email.data
        db.session.add(user)
        db.session.commit()

        flash('E-mail has been changed')
        return redirect(url_for('admin.user', user_id=user_id))

    return render_template('admin/user_change_email.html', user=user, form=form)


@admin.route('/admin/users/<int:user_id>/deposit', methods=['GET', 'POST'])
@admin_required
def user_deposit(user_id):
    user = User.query.get_or_404(user_id)

    form = DepositUserForm()
    if form.validate_on_submit():
        amount = form.amount.data * 100
        Transaction.transaction(type=Transaction.DEPOSIT_NOFEE,
                                amount=amount,
                                user=user,
                                note='No-fee deposit by administrator "%s"' % g.user.username)

        flash('Funds has been added')
        return redirect(url_for('admin.user', user_id=user_id))

    return render_template('admin/user_deposit.html', user=user, form=form)


@admin.route('/admin/users/<int:user_id>/change_password', methods=['POST'])
@admin_required
def user_change_password(user_id):
    user = User.query.get_or_404(user_id)

    form = PasswordChangeForm()
    if form.validate_on_submit():
        user.password = form.password.data
        db.session.add(user)
        db.session.commit()

        flash('Password has been changed')
        return redirect(url_for('admin.user', user_id=user_id))

    session['last_error'] = 'Please check that you typed all fields correctly'

    return redirect(url_for('admin.user', user_id=user_id, last_error_type='change_password'))


@admin.route('/admin/users/<int:user_id>/toggle_seller', methods=['POST'])
@admin_required
def user_toggle_seller(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        user.is_seller_disabled = not user.is_seller_disabled
        db.session.add(user)
        db.session.commit()

        flash('Seller has been %s' % ('disabled' if user.is_seller_disabled else 'enabled'))
        return redirect(url_for('admin.user', user_id=user_id))

    return redirect(url_for('admin.user', user_id=user_id, last_error_type='toggle_seller'))


@admin.route('/admin/users/<int:user_id>/toggle_premium', methods=['POST'])
@admin_required
def user_toggle_premium(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        user.premium_member = not user.premium_member
        db.session.add(user)
        db.session.commit()

        flash('Premium membership has been %s' % ('enabled' if user.premium_member else 'disabled'))
        return redirect(url_for('admin.user', user_id=user_id))

    return redirect(url_for('admin.user', user_id=user_id, last_error_type='toggle_premium'))


@admin.route('/admin/users/<int:user_id>/verify')
@admin_required
def user_verify_email(user_id):
    user = User.query.get_or_404(user_id)

    user.is_verified = True
    user.verification_code = None
    db.session.add(user)
    db.session.commit()

    flash('Verify email account has been successfull')
    return redirect(url_for('admin.user', user_id=user_id))


@admin.route('/admin/products')
@admin_required
def products():
    page = request.args.get('page', 1, type=int)
    username = request.args.get('username')

    products_query = Product.query.filter(Product.is_deleted != True, Product.published_on != None)
    if username:
        products_query = products_query.join(User).filter(User.username == username)

    products = products_query.order_by(Product.is_approved.asc(), Product.created_on.desc())
    pagination = products.paginate(page, per_page=ADDRESSES_PER_PAGE)

    return render_template('admin/products.html', pagination=pagination)


@admin.route('/admin/products/pending')
@admin_required
def products_pending_verification():
    page = request.args.get('page', 1, type=int)
    username = request.args.get('username')

    products_query = Product.query.filter(Product.is_deleted != True, Product.is_approved != True,
                                          Product.not_approved != True, Product.published_on != None)
    if username:
        products_query = products_query.join(User).filter(User.username == username)

    products = products_query.order_by(Product.published_on.asc())
    pagination = products.paginate(page, per_page=ADDRESSES_PER_PAGE)

    return render_template('admin/products.html', pagination=pagination)


@admin.route('/admin/products/<int:product_id>')
@admin_required
def product(product_id):
    product = Product.query.get_or_404(product_id)

    return render_template('admin/product.html', product=product)


@admin.route('/admin/products/<int:product_id>/approve')
@admin_required
def product_approve(product_id):
    product = Product.query.get_or_404(product_id)

    product.verification_approve()

    if not product.is_private:
        search.product_updated.send(product=product)

    return redirect(url_for('admin.product', product_id=product.id))


@admin.route('/admin/products/<int:product_id>/not_approve')
@admin_required
def product_not_approve(product_id):
    product = Product.query.get_or_404(product_id)

    product.verification_reject()

    search.product_deleted.send(product=product)

    return redirect(url_for('admin.product', product_id=product.id))


@admin.route('/admin/products/<int:product_id>/unapprove')
@admin_required
def product_unapprove(product_id):
    product = Product.query.get_or_404(product_id)

    product.verification_reject()

    search.product_deleted.send(product=product)

    return redirect(url_for('admin.product', product_id=product.id))


@admin.route('/admin/tags/<int:tag_id>/approve')
@admin_required
def tag_approve(tag_id):
    tag = Tag.query.get_or_404(tag_id)

    tag.is_approved = True
    db.session.add(tag)
    db.session.commit()

    return redirect(url_for('admin.product', product_id=request.args.get('product_id')))


@admin.route('/admin/tags/<int:tag_id>/unapprove')
@admin_required
def tag_unapprove(tag_id):
    tag = Tag.query.get_or_404(tag_id)

    tag.is_approved = False
    db.session.add(tag)
    db.session.commit()

    return redirect(url_for('admin.product', product_id=request.args.get('product_id')))


@admin.route('/admin/products/<int:product_id>/delete')
@admin_required
def product_delete(product_id):
    product = Product.query.get_or_404(product_id)

    product.is_deleted = True
    db.session.add(product)
    db.session.commit()

    search.product_deleted.send(product=product)

    return redirect(url_for('admin.products'))


@admin.route('/admin/newsletters')
@admin_required
def newsletters():
    page = request.args.get('page', 1, type=int)

    newsletters_query = Newsletter.query

    newsletters = newsletters_query.order_by(Newsletter.is_sent.asc(), Newsletter.created_on.desc())
    pagination = newsletters.paginate(page, per_page=ADDRESSES_PER_PAGE)

    return render_template('admin/newsletters.html', pagination=pagination)


@admin.route('/admin/newsletters/<int:newsletter_id>')
@admin_required
def newsletter(newsletter_id):
    newsletter = Newsletter.query.get_or_404(newsletter_id)

    return render_template('admin/newsletter.html', newsletter=newsletter)


@admin.route('/admin/newsletters/<int:newsletter_id>/approve')
@admin_required
def newsletter_approve(newsletter_id):
    newsletter = Newsletter.query.get_or_404(newsletter_id)

    newsletter.approve()

    return redirect(url_for('admin.newsletter', newsletter_id=newsletter.id))


@admin.route('/admin/newsletters/<int:newsletter_id>/delete')
@admin_required
def newsletter_delete(newsletter_id):
    newsletter = Newsletter.query.get_or_404(newsletter_id)

    db.session.delete(newsletter)
    db.session.commit()

    return redirect(url_for('admin.newsletters'))


@admin.route('/admin/news')
@admin_required
def news():
    page = request.args.get('page', 1, type=int)

    news_query = Content.query.filter_by(type=Content.MEMBER_NEWS)
    news = news_query.order_by(Content.is_published.desc(), Content.created_on.desc())

    pagination = news.paginate(page, per_page=ADDRESSES_PER_PAGE)

    return render_template('admin/news.html', pagination=pagination)


@admin.route('/admin/news/add', methods=['GET', 'POST'])
@admin_required
def news_add():
    form = NewsForm()
    if form.validate_on_submit():
        content = Content(type=Content.MEMBER_NEWS,
                          user_id=g.user.id,
                          is_published=form.is_published.data,
                          title=form.title.data if form.title.data else None,
                          text=form.text.data)

        db.session.add(content)
        db.session.commit()

        return redirect(url_for('admin.news'))

    return render_template('admin/news_edit.html', form=form)


@admin.route('/admin/news/<int:content_id>/edit', methods=['GET', 'POST'])
@admin_required
def news_edit(content_id):
    content = Content.query.get_or_404(content_id)
    if content.type != Content.MEMBER_NEWS:
        abort(403)

    form = NewsForm(title=content.title,
                    text=content.text,
                    is_published=content.is_published)

    if form.validate_on_submit():
        content.title = form.title.data if form.title.data else None
        content.text = form.text.data
        content.is_published = form.is_published.data

        db.session.add(content)
        db.session.commit()

        return redirect(url_for('admin.news'))

    return render_template('admin/news_edit.html', content=content, form=form)


@admin.route('/admin/news/<int:content_id>/delete')
@admin_required
def news_delete(content_id):
    content = Content.query.get_or_404(content_id)
    if content.type != Content.MEMBER_NEWS:
        abort(403)

    db.session.delete(content)
    db.session.commit()

    return redirect(url_for('admin.news'))


@admin.route('/admin/addresses')
@admin_required
def addresses():
    page = request.args.get('page', 1, type=int)
    show = request.args.get('show', 'all')

    addresses_query = BitcoinAddress.query

    if show == 'confirmed':
        addresses_query = addresses_query.filter(
            BitcoinAddress.amount > 0,
            BitcoinAddress.is_amount_confirmed == True
        )

    addresses = addresses_query.order_by(BitcoinAddress.touched_on.desc(), BitcoinAddress.id.desc())

    pagination = addresses.paginate(page, per_page=ADDRESSES_PER_PAGE)

    return render_template('admin/addresses.html', pagination=pagination, show=show)


@admin.route('/admin/withdrawals')
@admin_required
def withdrawals():
    page = request.args.get('page', 1, type=int)
    withdrawals = Withdrawal.query_requests().order_by(Withdrawal.is_closed.asc(), Withdrawal.created_on.asc())

    pagination = withdrawals.paginate(page, per_page=WITHDRAWALS_PER_PAGE)

    wu_enabled = Variable.get_wu_enabled()

    return render_template('admin/withdrawals.html', pagination=pagination, wu_enabled=wu_enabled)


@admin.route('/admin/withdrawals/<int:withdrawal_id>/reject')
@admin_required
def withdrawal_reject(withdrawal_id):
    withdrawal = Withdrawal.query.get_or_404(withdrawal_id)

    withdrawal.reject()
    flash('Withdrawal request has been rejected')

    return redirect(url_for('admin.withdrawals'))


@admin.route('/admin/withdrawals/<int:withdrawal_id>/confirm', methods=['POST'])
@admin_required
def withdrawal_confirm(withdrawal_id):
    withdrawal = Withdrawal.query.get_or_404(withdrawal_id)

    note = request.form.get('note', '')
    reply = dict(note=note)

    withdrawal.confirm(reply)
    flash('Withdrawal request #%d has been confirmed' % withdrawal_id)

    return redirect(url_for('admin.withdrawals'))


@admin.route('/admin/addresses/upload', methods=['POST'])
@admin_required
def addresses_upload():
    addresses_file = request.files['addresses']

    if not addresses_file:
        flash('Please specify a file')
        return redirect(url_for('admin.addresses'))

    if '.' in addresses_file.filename and addresses_file.filename.rsplit('.', 1)[1] != 'key':
        flash('Unknown file format. File should have .key extension')
        return redirect(url_for('admin.addresses'))

    import re

    total = 0
    duplicates = 0
    skipped = 0

    for line in addresses_file.readlines():
        total += 1
        address = line.strip()
        if not re.match(r'^[13][a-km-zA-HJ-NP-Z0-9]{26,33}$', address):
            skipped += 1
            continue

        if not BitcoinAddress.add(address):
            duplicates += 1

    flash("Addresses have been added: %d from %d total (%d are duplicate, %d are invalid)" % (
        total - (duplicates + skipped), total, duplicates, skipped))
    return redirect(url_for('admin.addresses'))


@admin.route('/admin/withdrawals/toggle_wu')
@admin_required
def withdrawals_toggle_wu():
    wu_enabled = Variable.get_wu_enabled()
    Variable.set_wu_enabled(not wu_enabled)
    return redirect(url_for('admin.withdrawals'))


@admin.route('/admin/vouchers', methods=['GET', 'POST'])
@admin_required
def vouchers():
    page = request.args.get('page', 1, type=int)
    vouchers = Voucher.query.filter(Voucher.is_invite != True).order_by(Voucher.created_on.desc())

    pagination = vouchers.paginate(page, per_page=ADDRESSES_PER_PAGE)

    form = NewVoucherForm()

    if form.validate_on_submit():
        Voucher.add(None, type=form.type.data, total_count=form.total_count.data, is_invite=False)

        flash('Voucher has been created')
        return redirect(url_for('admin.vouchers'))

    return render_template('admin/vouchers.html', pagination=pagination, form=form)


@admin.route('/admin/vouchers/<int:voucher_id>/delete')
@admin_required
def voucher_delete(voucher_id):
    voucher = Voucher.query.get_or_404(voucher_id)

    db.session.delete(voucher)
    db.session.commit()

    return redirect(url_for('admin.vouchers'))


@admin.route('/admin/affiliate_links', methods=['GET', 'POST'])
@admin_required
def affiliate_links():
    page = request.args.get('page', 1, type=int)
    links = AffiliateLink.query.filter(AffiliateLink.is_deleted != True).order_by(AffiliateLink.created_on.desc())

    pagination = links.paginate(page, per_page=ADDRESSES_PER_PAGE)

    form = NewAffiliateLinkForm()

    if form.validate_on_submit():
        affiliate_link = AffiliateLink(
            title=form.title.data,
            description=form.description.data,
            url=form.url.data,
            unique_url_id=form.unique_url_id.data
        )

        storage = Storage()
        aws_key, cloudinary_key = storage.upload_image(
            Storage.ImageType.AFFILIATE_LINK_IMAGE,
            form.image.data,
            form.unique_url_id.data
        )

        affiliate_link.set_image_data(dict(aws_key=aws_key, cloudinary_key=cloudinary_key))

        db.session.add(affiliate_link)
        db.session.commit()

        flash('Affiliate link has been added')
        return redirect(url_for('admin.affiliate_links'))

    return render_template('admin/affiliate_links.html', pagination=pagination, form=form)


@admin.route('/admin/affiliate_links/<int:affiliate_link_id>/delete')
@admin_required
def affiliate_link_delete(affiliate_link_id):
    affiliate_link = AffiliateLink.query.get_or_404(affiliate_link_id)

    affiliate_link.is_deleted = True

    db.session.add(affiliate_link)
    db.session.commit()

    return redirect(url_for('admin.affiliate_links'))


@admin.route('/admin/affiliate_links/<int:affiliate_link_id>/toggle')
@admin_required
def affiliate_link_toggle_hidden(affiliate_link_id):
    affiliate_link = AffiliateLink.query.get_or_404(affiliate_link_id)

    affiliate_link.is_hidden = not bool(affiliate_link.is_hidden)

    db.session.add(affiliate_link)
    db.session.commit()

    return redirect(url_for('admin.affiliate_links'))
