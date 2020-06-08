from flask import request, abort, g, url_for, json, make_response, session, flash, redirect
import stripe
from app.utils import slack
from UniversalAnalytics import Tracker
from validate_email import validate_email
from uuid import UUID

from app import app, search, email, db, messaging, statistic
from app.models import Product, EnquiryOffer, User, UserSocialAccount, Order, Discount, SearchSuggest, Transaction, \
    Ticket, Tag, Feedback, FavoriteSearch, Variable, Enquiry, UserEndorsement, isoformat, Report, Product_Vote, \
    UserSearchHistory
from app.utils import upload_temp_attachment, UploadException
from app.utils.storage import ImagePresets
from app.decorators import xhr_required, login_required
from app.helpers import APIError
from datetime import datetime, timedelta
from .helpers import prepare_product
from .forms import ReportAPIForm


SORTING_MAPPING = {
    'recommended': search.ProductSorting.RECOMMENDED,
    '-date': search.ProductSorting.DATE_DESC,
    'price': search.ProductSorting.PRICE_ASC,
    '-price': search.ProductSorting.PRICE_DESC,
    '-orders': search.ProductSorting.ORDERS_DESC
}



def is_valid_uuid(uuid_to_test, version=4):
    try:
        uuid_obj = UUID(uuid_to_test, version=version)
    except:
        return False

    return str(uuid_obj) == uuid_to_test


@app.route('/api/search')
@xhr_required
def api_search():
    # TODO: require some token, generated on the index page
    incoming_query = request.args.get('query')
    incoming_limit = request.args.get('limit', 9, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)
    incoming_categories = request.args.get('categories', '')
    incoming_tags = request.args.get('tags', '')
    incoming_sort = request.args.get('sort', 'recommended')
    incoming_prices = map(lambda key: int(request.args.get(key, 0, type=float) * 100), ('price_from', 'price_to'))
    incoming_online = request.args.get('online', False)
    incoming_min_rating = request.args.get('min_rating', 0, type=int)
    incoming_search_id = request.args.get('search_id')

    query_args = dict(
        q=incoming_query,
        sorting=SORTING_MAPPING.get(incoming_sort, search.ProductSorting.RECOMMENDED),
        include_private=(g.user.is_authenticated and g.user.premium_member),
        price=incoming_prices,
        online=incoming_online,
        start=incoming_offset,
        limit=incoming_limit
    )

    if incoming_min_rating:
        query_args['min_rating_int'] = incoming_min_rating

    if incoming_categories:
        category_ids = [int(category_id) for category_id in incoming_categories.split(',') if category_id.isdigit()]
        query_args['category_ids'] = category_ids

    if incoming_tags:
        # tag_ids = [int(tag_id) for tag_id in incoming_tags.split(',') if tag_id.isdigit()]
        # query_args['tags'] = [tag.tag for tag in Tag.get_multiple(tag_ids)]
        query_args['tags'] = [tag for tag in incoming_tags.split(',')]

    if incoming_search_id:
        query_args['random_seed'] = incoming_search_id

    # import time
    # millis = int(round(time.time() * 1000))

    ids, total, tags = search.search_products(**query_args)

    # print 'after ES search', int(round(time.time() * 1000)) - millis

    products = Product.get_multiple(ids)

    # print 'after SQL search', int(round(time.time() * 1000)) - millis

    products_prepared = map(prepare_product, products)

    # print 'after preparation', int(round(time.time() * 1000)) - millis

    favorite = False

    if g.user.is_authenticated:
        favorite = FavoriteSearch.check(g.user.id, incoming_query)
        if incoming_query is not None:
            search_activity = UserSearchHistory(user_id=g.user.id, query=incoming_query)
            db.session.add(search_activity)
            db.session.commit()
    # print 'before sending JSON', int(round(time.time() * 1000)) - millis

    return json.jsonify(dict(
        data=products_prepared,
        meta=dict(
            total=total,
            tags=tags,
            favorite=favorite
        )
    ))


@app.route('/api/search/favorite/toggle', methods=['POST'])
@xhr_required
@login_required
def api_favorite_search_toggle():
    incoming_query = request.args.get('query')

    if not incoming_query:
        abort(400)

    FavoriteSearch.toggle(g.user.id, incoming_query)

    return json.jsonify(dict())


@app.route('/api/user/<user_id>/feedbacks')
@xhr_required
def api_user_feedbacks(user_id):
    user = User.query.get_or_404(user_id)

    incoming_limit = request.args.get('limit', 5, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)
    incoming_sort = request.args.get('sort')

    feedbacks_query = user.query_seller_feedbacks()
    feedbacks_query = feedbacks_query.order_by(Feedback.created_on.asc() if incoming_sort == 'asc' else Feedback.created_on.desc())

    feedbacks = feedbacks_query.limit(incoming_limit).offset(incoming_offset)

    feedbacks_total = user.query_seller_feedbacks().count()
    feedbacks_prepared = []

    for feedback in feedbacks:
        user = User.query.get(feedback.user_id)
        feedback_prepared = feedback.to_json()
        feedback_prepared['_user_username'] = user.username
        feedback_prepared['_user_url'] = url_for('user', username=user.username)
        feedback_prepared['_user_photo_url'] = user.get_photo_url(ImagePresets.USER_PRIMARY)
        feedback_prepared['_created_on_printable'] = feedback.created_on.strftime('%B %Y')
        feedback_prepared['_rating_int'] = feedback.get_rating_int()
        feedbacks_prepared.append(feedback_prepared)

    return json.jsonify(feedbacks_prepared)


@app.route('/api/service/<product_id>/report', methods=['POST'])
@xhr_required
@login_required
def api_service_report(product_id):
    product = Product.query.get_or_404(product_id)

    form = ReportAPIForm(csrf_enabled=False)
    if form.validate_on_submit():

        report = Report(
            product_id=product.id,
            user_id=g.user.id,
            reason=form.reason.data,
            data_json=form.get_extra_data_as_json()
        )

        db.session.add(report)
        db.session.commit()

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@app.route('/api/service/<product_id>/vote/<any(up,down):direction>')
@xhr_required
@login_required
def api_service_vote(product_id, direction):
    product = Product.query.get_or_404(product_id)
    query = Product_Vote.query.filter(Product_Vote.voter_id == g.user.id,
                                      Product_Vote.product_id == product.id)
    if db.session.query(query.exists()).scalar():
        raise APIError('You already vote')

    if direction == 'up':
        product.votes = Product.votes + 1
    else:
        product.votes = Product.votes - 1

    vote = Product_Vote(
        product_id=product.id,
        voter_id=g.user.id,
        up=direction == 'up',
        down=direction == 'down'
    )
    db.session.add(vote)
    db.session.add(product)
    db.session.commit()
    return json.jsonify()


@app.route('/api/service/<product_id>/feedbacks')
@xhr_required
def api_service_feedbacks(product_id):

    #TODO: better version for check private service.
    if is_valid_uuid(product_id, version=4):
        product = Product.query.filter_by(uuid=product_id).first()
    else:
        product = Product.query.filter_by(unique_id=product_id).first()

    if not product or product.is_deleted:
        abort(404)

    incoming_limit = request.args.get('limit', 5, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)
    incoming_sort = request.args.get('sort')

    feedbacks_query = product.query_feedbacks()
    feedbacks_query = feedbacks_query.order_by(Feedback.created_on.asc() if incoming_sort == 'asc' else Feedback.created_on.desc())

    feedbacks = feedbacks_query.limit(incoming_limit).offset(incoming_offset)

    feedbacks_total = product.query_feedbacks().count()
    feedbacks_prepared = []

    for feedback in feedbacks:
        user = User.query.get(feedback.user_id)
        feedback_prepared = feedback.to_json()
        feedback_prepared['_user_username'] = user.username
        feedback_prepared['_user_url'] = url_for('user', username=user.username)
        feedback_prepared['_user_photo_url'] = user.get_photo_url(ImagePresets.USER_PRIMARY)
        feedback_prepared['_created_on_printable'] = feedback.created_on.strftime('%B %Y')
        feedback_prepared['_rating_int'] = feedback.get_rating_int()
        feedbacks_prepared.append(feedback_prepared)

    return json.jsonify(feedbacks_prepared)


@app.route('/api/search/extra/<product_id>')
@xhr_required
def api_search_extra(product_id):

    #TODO: better version for check private service.
    if is_valid_uuid(product_id, version=4):
        product = Product.query.filter_by(uuid=product_id).first()
    else:
        product = Product.query.filter_by(unique_id=product_id).first()

    if not product or product.is_deleted:
        abort(404)

    products = list()
    products_type = 'more'

    best_products, _ = search.search_best(product=product, limit=3)

    if best_products:
        products = Product.get_multiple(best_products)
    else:
        similar_products = search.search_similar(product, limit=3)
        products = Product.get_multiple(similar_products)
        products_type = 'similar'

    products_prepared = map(prepare_product, products)

    return json.jsonify(dict(
        data=products_prepared,
        meta=dict(type=products_type)
    ))


@app.route('/api/search/user/<int:user_id>')
@xhr_required
def api_search_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_deleted or user.is_disabled:
        abort(404)

    incoming_limit = request.args.get('limit', 6, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)

    best_products, best_products_total = search.search_best(seller=user, limit=incoming_limit, start=incoming_offset)

    products = Product.get_multiple(best_products)
    products_prepared = map(prepare_product, products)

    return json.jsonify(dict(
        data=products_prepared,
        meta=dict(
            total=best_products_total
        )
    ))


@app.route('/api/search/multiple')
@xhr_required
def api_search_multiple():
    ids = request.args.get('ids')
    if not ids:
        return make_response(json.jsonify(dict()), 404)

    products = Product.query.filter(Product.unique_id.in_(ids.split(','))).limit(6)

    products_prepared = map(prepare_product, products)

    return json.jsonify(products_prepared)


@app.route('/api/order/upload', methods=['POST'])
@xhr_required
def api_order_upload():
    try:
        filename, filename_fs = upload_temp_attachment(request.files['file'], app.config.get('ALLOWED_ATTACHMENT_EXTENSIONS'))
    except UploadException, e:
        return make_response(json.jsonify(dict(error=e.message)), 400)

    return json.jsonify(dict(filename=filename, tmpfilename=filename_fs))


@app.route('/api/enquiry', methods=['POST'])
@xhr_required
@login_required
def api_enquiry():
    incoming = request.get_json()
    incoming_service_id = incoming.get('service_id')
    incoming_seller_id = incoming.get('seller_id')
    incoming_text = incoming.get('text')
    incoming_meta = incoming.get('meta')

    product, seller = None, None

    if incoming_service_id:
        product = Product.get_by_custom_id(incoming_service_id)
        if not product or product.seller.id == g.user.id:
            abort(404)

        # Check if the product isn't deleted and seller is active
        if product.is_deleted or product.published_on is None or product.seller.is_deleted or product.seller.is_disabled:
            abort(404)

        # Product is not approved
        if not product.is_approved:
            abort(404)
    elif incoming_seller_id:
        seller = User.query.get_or_404(incoming_seller_id)

        if not seller.seller_fee_paid or seller.is_disabled or seller.is_deleted or seller.id == g.user.id:
            abort(404)
    else:
        raise APIError('Either service or seller is required to create enquiry')

    if not incoming_text:
        raise APIError('Text is required')

    attachments = None

    if incoming_meta and 'attachments' in incoming_meta and type(incoming_meta['attachments']) == list:
        for attachment in incoming_meta['attachments']:
            if 'attachmentId' not in attachment or 'filename' not in attachment:
                raise APIError('Wrong attachments format')

        attachments = incoming_meta['attachments']

    new_chat_count = Enquiry.query.filter(Enquiry.user_id == g.user.id,
                                          Enquiry.created_on >= (datetime.now() - timedelta(hours=1))).count()

    if new_chat_count >= 10:
        raise APIError('Limit reached. Try again later.', status_code=429)

    enquiry = Enquiry.get_or_create(g.user, product=product, seller=seller)

    messaging.new_enquiry(
        enquiry,
        g.user,
        product.seller if product else seller,
        incoming_text,
        service=product,
        attachments=attachments
    )

    # TODO: create function to build anchor URLs
    return json.jsonify(dict(
        id=enquiry.id,
        _url='%s#?type=enquiry&id=%d' % (url_for('account.inbox'), enquiry.id)
    ))


@app.route('/api/order/<custom_id>/verify', methods=['POST'])
@xhr_required
def api_order_verify(custom_id):
    product = Product.get_by_custom_id(custom_id)
    if not product:
        abort(404)

    # Check if the product isn't deleted and seller is active
    if product.is_deleted or product.published_on is None or product.seller.is_deleted or product.seller.is_disabled:
        abort(404)

    # Do not allow view not approved product except for seller
    if not product.is_approved and not (g.user.is_authenticated and product.seller_id == g.user.id):
        abort(404)

    incoming = request.get_json()

    product_offer = product.get_active_offer()
    if product.get_active_offer():
        abort(400)

    # Apply discount if code has been provided, and there is no active offer on the service

    discount_code = incoming['discount'] if incoming.has_key('discount') else None
    if not discount_code:
        abort(400)

    discount = Discount.check(discount_code, product)
    if not discount:
        abort(400)

    discount_value = discount.calculate_discount(product.price)

    return json.jsonify(dict(discount_value=discount_value))


@app.route('/api/order/<custom_id>', methods=['POST'])
@xhr_required
def api_order(custom_id):
    product = Product.get_by_custom_id(custom_id)
    if not product:
        abort(404)

    # Check if the product isn't deleted and seller is active
    if product.is_deleted or product.published_on is None or product.seller.is_deleted or product.seller.is_disabled:
        abort(404)

    # Do not allow view not approved product except for seller
    if not product.is_approved and not (g.user.is_authenticated and product.seller_id == g.user.id):
        abort(404)

    incoming = request.get_json()

    enquiry_offer = None
    incoming_enquiry_offer_id = incoming.get('enquiry_offer_id')

    # Enquiry offers are only can be used by authenticated users
    if incoming_enquiry_offer_id and g.user.is_authenticated:
        tmp_offer = EnquiryOffer.query.get(incoming_enquiry_offer_id)
        if tmp_offer and not tmp_offer.is_closed and not tmp_offer.is_accepted:
            enquiry = tmp_offer.get_enquiry()
            if enquiry.user_id == g.user.id and product.id == tmp_offer.product_id:
                enquiry_offer = tmp_offer

    # Check if current user can order
    can_order = False
    if not (g.user.is_authenticated and product.seller_id == g.user.id):
        if product.quantity is None or product.quantity > 0:
            can_order = True

    if not can_order:
        raise APIError('Service is not available', status_code=403)

    # Apply discount if code has been provided

    discount_code = incoming['discount'] if incoming.has_key('discount') else None
    discount = None

    if discount_code and not enquiry_offer:
        # Discount is disabled when enquiry offer is set
        discount = Discount.check(discount_code, product)

    selected_extras = incoming.get('extras') if incoming.has_key('extras') else list()

    # Add order fee

    amount, fee = Order.calculate_amount(product, discount=discount, enquiry_offer=enquiry_offer, selected_extras=selected_extras)

    if 'stripeSource' in incoming:
        # Pay by credit card
        # First we are going to create a "pending" order which won't charge user until payment is confirmed
        buyer = g.user

        if not g.user.is_authenticated:
            stripe_email = incoming['stripeEmail']
            if not validate_email(stripe_email):
                raise APIError('Please check e-mail address you\'ve specified')

            buyer = User.query.filter_by(email=stripe_email).first()

            if buyer and (buyer.is_deleted or buyer.is_disabled):
                raise APIError('The account associated with this email address was disabled. If you feel this was done in error, please contact our support team.', 403)

            if not buyer:
                buyer, password = User.generate(stripe_email)
                code = buyer.request_verification()
                url = url_for('auth.register_verify', code=code, email=stripe_email, _external=True)

                if User.REFERER_COOKIE in request.cookies:
                    # We have a cookie with referer ID
                    buyer.set_referer(request.cookies.get(User.REFERER_COOKIE))

                buyer.record_register(ip=g.ip, type=User.RegisterTypes.AUTOSIGNUP)
                email.send_welcome_autosignup(stripe_email, buyer.username, password, url)

        return_url = url_for('product_order_payment', custom_id=custom_id, _external=True)

        source_id = incoming['stripeSource']
        customer_id = buyer.get_meta_data('stripe_customer')
        customer = None

        source = stripe.Source.retrieve(source_id)

        if incoming['remember'] and source['usage'] == 'reusable':
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

        source_3ds = stripe.Source.create(
            amount=amount + fee,
            currency='usd',
            type='three_d_secure',
            three_d_secure={
                'card': source_id,
            },
            redirect={
                'return_url': return_url
            }
        )

        if source_3ds['status'] == 'chargeable' or (source_3ds['status'] == 'pending' and source_3ds['redirect']['status'] == 'pending'):
            order = Order.order(
                product,
                buyer,
                discount=discount,
                enquiry_offer=enquiry_offer,
                selected_extras=selected_extras,
                stripe_source=source_3ds['id']
            )

            if source_3ds['status'] == 'pending':
                redirect_url = source_3ds['redirect']['url']
            else:
                redirect_url = url_for('product_order_payment', custom_id=custom_id, source=source_3ds['id'])

            return json.jsonify(dict(_redirect_url=redirect_url))

        order.cancel_pending(note='Payment failed and order couldn\'t be processed')
        raise APIError('Payment failed and order couldn\'t be processed', 500)
    else:
        # Pay by site credit
        if not g.user.is_authenticated:
            abort(403)

        if g.user.credit < amount + fee:
            # This should not happen as validation is done on the client side
            raise APIError('Not enough balance', status_code=403)

        # Issuing order
        order = Order.order(
            product,
            g.user,
            discount=discount,
            enquiry_offer=enquiry_offer,
            selected_extras=selected_extras
        )

        order_url = url_for('account.buyer_order', order_id=order.id)

        return json.jsonify(dict(id=order.id, _url=order_url))


@app.route('/api/order/<custom_id>/<order_id>/status', methods=['POST'])
@xhr_required
def api_order_status(custom_id, order_id):
    product = Product.get_by_custom_id(custom_id)
    if not product:
        abort(404)

    order = Order.query.get_or_404(order_id)
    if order.state not in (Order.NEW, Order.CLOSED_CANCELLED) or (g.user.is_authenticated and order.buyer_id != g.user.id):
        abort(404)

    if order.is_pending and order.state == Order.CLOSED_CANCELLED:
        return json.jsonify(dict(error='Payment failed and order couldn\'t be processed'))

    if not order.is_pending and order.state == Order.NEW:
        order_url = url_for('account.buyer_order', order_id=order.id)
        return json.jsonify(dict(success=True, _url=order_url))

    return json.jsonify(dict(is_pending=True))


@app.route('/api/become_seller', methods=['POST'])
@xhr_required
@login_required
def api_become_seller():
    if g.user.seller_fee_paid:
        # User has already paid seller fee
        abort(403)

    seller_fee = Variable.get_seller_fee()

    if seller_fee and g.user.credit < seller_fee:
        abort(403)

    incoming = request.get_json()
    incoming_description = incoming.get('description')
    incoming_headline = incoming.get('headline')
    incoming_rate = incoming.get('rate')
    incoming_languages = incoming.get('languages')
    incoming_skills = incoming.get('skills')

    error_fields = dict()

    if not incoming_description or len(incoming_description) < 120 or len(incoming_description) > 1000:
        error_fields['description'] = 1

    if incoming_rate:
        try:
            incoming_rate = int(incoming_rate)
            if incoming_rate < 0:
                raise
        except:
            error_fields['rate'] = 1

    if not incoming_headline or len(incoming_headline) > 100:
        error_fields['headline'] = 1

    if incoming_languages:
        if type(incoming_languages) != list or not all((set(item) == set(('id', 'level_id',)) for item in incoming_languages)):
            error_fields['languages'] = 1
    else:
        error_fields['languages'] = 1

    if incoming_skills:
        if type(incoming_skills) != list or not all((set(item) == set(('id', 'level_id',)) for item in incoming_skills)):
            error_fields['skills'] = 1

    if not g.user.get_photo_data():
        # User has not uploaded his photo
        error_fields['photo'] = 1

    if not g.user.phone_number or not g.user.phone_number_verified:
        # User has not verified his phone number
        # UPD: we now allow not to verify phone number if user has verified his facebook account
        connected_accounts = UserSocialAccount.query.filter_by(user_id=g.user.id).all()
        connected_accounts_set = set(map(lambda account: account.provider, connected_accounts))

        if 'facebook' not in connected_accounts_set:
            error_fields['phone_number'] = 1

    if error_fields:
        raise APIError('Missing data', payload=dict(fields=error_fields))

    if seller_fee:
        Transaction.transaction(
            type=Transaction.SELLER_FEE,
            amount=seller_fee,
            user=g.user,
            note='One-time seller fee'
        )

    g.user.seller_fee_paid = True
    g.user.profile_description = incoming_description
    g.user.profile_headline = incoming_headline

    if incoming_rate:
        g.user.profile_rate = incoming_rate

    if incoming_languages:
        g.user.set_meta_data('languages', incoming_languages)

    if incoming_skills:
        g.user.set_meta_data('skills', incoming_skills)

    db.session.add(g.user)
    db.session.commit()

    referer = g.user.get_referer()
    if referer:
        referer.record_affiliate_become_seller(g.user)

    slack.notification('New user become a seller : {0}'.format(g.user.username), icon=slack.Icons.DANGER)

    # send event to Google Analytics
    tracker = Tracker.create('UA-86740209-1')
    tracker.send('event', 'BecomeSeller', g.user.username)
    del tracker

    return json.jsonify(dict(_url=url_for('account.service_create')))


@app.route('/api/contact', methods=['POST'])
@xhr_required
def api_contact():
    # TODO: ddos protection and use wtforms instead of manual check

    incoming = request.get_json()
    incoming_reason = incoming.get('reason')
    incoming_email = incoming.get('email')
    incoming_comments = incoming.get('comments')

    if not incoming_reason or not incoming_email or not incoming_comments:
        raise APIError('Please fill in required fields')

    email.send_contact_us(reason=incoming_reason, email=incoming_email, comments=incoming_comments)

    return json.jsonify(dict())


@app.route('/api/endorse', methods=['POST'])
@xhr_required
@login_required
def api_endorse_create():
    # TODO: ddos protection and use wtforms instead of manual check

    incoming = request.get_json()
    incoming_user_id = incoming.get('user_id')
    incoming_text = incoming.get('text')

    if not incoming_user_id or type(incoming_user_id) != int or not incoming_text:
        raise APIError('Please fill in required fields')

    user_id = int(incoming_user_id)

    if g.user.id == user_id:
        raise APIError('You can\'t endorse yourself')

    if g.user.seller_fee_paid:
        raise APIError('Only buyers can endorse')

    if g.user.is_authenticated and UserEndorsement.query.filter_by(user_id=user_id, publisher_user_id=g.user.id).first():
        raise APIError('You have already published endorsement for this user')

    endorsement = UserEndorsement(
        user_id=user_id,
        publisher_user_id=g.user.id if g.user.is_authenticated else None,
        text=incoming_text
    )

    db.session.add(endorsement)
    db.session.commit()

    if not g.user.is_authenticated:
        session['auth_endorsement_id'] = endorsement.id

    return json.jsonify(dict(id=endorsement.id))


@app.route('/api/profile/languages')
@app.route('/api/become_seller/languages')
@xhr_required
@login_required
def api_become_seller_languages():
    from app.utils.data.languages import LANGUAGES, LEVELS

    return json.jsonify(dict(languages=LANGUAGES, levels=LEVELS))


@app.route('/api/profile/skills')
@app.route('/api/become_seller/skills')
@xhr_required
@login_required
def api_become_seller_skills():
    from app.utils.data.skills import SKILLS, LEVELS

    return json.jsonify(dict(skills=SKILLS, levels=LEVELS))


@app.route('/api/search/suggest')
@xhr_required
def api_search_suggest():
    #TODO : Support elastic search, else kill database.
    incoming_query = request.args.get('query')

    search_suggest_query = SearchSuggest.query \
                  .filter(SearchSuggest.is_approved == True) \
                  .filter(SearchSuggest.keywords.ilike('%s%%' % incoming_query)) \
                  .order_by(SearchSuggest.id.asc())

    return json.jsonify(
        [item.keywords for item in search_suggest_query.all()][:10]
    )


@app.route('/api/unsubscribe', methods=['POST'])
@xhr_required
def api_unsubscribe():
    # TODO: move definitions in one place
    SUBSCRIPTIONS = [
        'new_users'
    ]

    incoming_uuid = request.args.get('uuid', '')
    if len(incoming_uuid) != 32:
        abort(404)

    user = User.query.filter_by(uuid=incoming_uuid).first()

    if not user:
        abort(404)

    incoming_data = request.get_json()

    disabled_subscriptions = user.get_meta_data('disabled_subscriptions') or dict()

    for id in incoming_data:
        if id not in SUBSCRIPTIONS:
            continue

        if not incoming_data[id]:
            disabled_subscriptions[id] = True
        else:
            del disabled_subscriptions[id]

    user.set_meta_data('disabled_subscriptions', disabled_subscriptions)
    db.session.add(user)
    db.session.commit()

    return json.jsonify(dict())


@app.route('/api/affiliate', methods=['POST'])
@xhr_required
def api_affiliate():
    if g.user.is_authenticated:
        return json.jsonify(dict())

    incoming = request.get_json()
    incoming_id = incoming.get('id')
    incoming_url = incoming.get('url')
    incoming_referer = incoming.get('referer')
    referer_id = request.cookies.get(User.REFERER_COOKIE)

    if not incoming_id or not referer_id or not g.ip:
        return json.jsonify(dict())

    try:
        # Check whether ID is hex
        int(incoming_id, 16)
    except ValueError:
        print "Invalid incoming ID: %s" % incoming_id
        return json.jsonify(dict())

    referer_user = User.query.get(referer_id)

    if not referer_user or referer_user.is_deleted:
        print "Referer user not found by ID: %s" % referer_id
        return json.jsonify(dict())

    try:
        statistic.AffiliateImpression.try_save_unique(incoming_id, g.ip)
    except statistic.AffiliateImpression.NotUniqueException:
        # Impression is not unique
        return json.jsonify(dict())

    referer_user.record_affiliate_impression(
        ip=g.ip,
        url=incoming_url,
        client_id=incoming_id,
        referer_url=incoming_referer
    )

    return json.jsonify(dict())
