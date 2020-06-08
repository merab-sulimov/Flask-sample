import urllib
from flask import request, abort, render_template, g, redirect, url_for, json, make_response, send_from_directory, Markup, escape
from werkzeug.contrib.atom import AtomFeed
from datetime import datetime, timedelta

from app import app, search, cache
from app.models import Category, Product, User, Tag, Variable, UserSocialAccount, Order, Discount, AffiliateLink, EnquiryOffer, UserEndorsement
from app.helpers import SearchPagination
from app.utils import static_file_url, render_markdown
from app.utils.storage import ImagePresets
from .helpers import prepare_product, prepare_application_data


PRODUCTS_PER_PAGE = 12
SORTING_LABELS = (
    ('-date', 'Date added'),
    ('price', 'Lower price'),
    ('-price', 'Higher price'),
    ('-orders', 'Best Sellers')
)

DATE_FILTER_LABELS = (
    ('0', 'Added: Any time'),
    ('365', 'In the last year'),
    ('31', 'In the last month'),
    ('7', 'In the last week'),
    ('1', 'In the last day')
)


@app.errorhandler(404)
def not_found(e):
    if request.is_xhr:
        return json.jsonify(), 404

    application_data = prepare_application_data()
    return render_template('new/404.html', application_data=application_data, header_hide_search=True), 404


@app.route('/')
def index():
    application_data = prepare_application_data()
    application_data['extra'] = dict()

    if request.args.get('mode') == 'recovery':
        token = request.args.get('token')
        if token:
            application_data['extra']['mode'] = 'recovery'
            application_data['extra']['token'] = token

    if request.args.get('mode') in ('login', 'signup'):
        application_data['extra']['mode'] = request.args.get('mode')
        if request.args.get('code'):
            application_data['extra']['code'] = request.args.get('code')

        if request.args.get('next'):
            application_data['extra']['next'] = request.args.get('next')

    if not g.user.is_authenticated:
        # Show landing for non-authenticated users
        return render_template('new/landing.html', application_data=application_data, header_hide_search=True)

    ## Building tag list

    # tags = Tag.query.filter_by(is_approved=True).all()
    # extra['tags'] = [dict(id=tag.id, title=tag.tag) for tag in tags]

    ## Price bounds

    max_price = cache.get_cached_object(cache.SharedCache.FRONTEND_MAX_PRICE)

    if max_price is None:
        max_price = Product.get_max_price()
        cache.put_cached_object(cache.SharedCache.FRONTEND_MAX_PRICE, max_price)

    application_data['extra']['price_bounds']=(0, max_price,)

    return render_template('new/index.html',
                           application_data=application_data)


@app.route('/explore')
def explore():
    application_data = prepare_application_data()
    extra = dict()

    if g.user.is_authenticated:
        # For authenticated users redirect back to index
        return redirect(url_for('index'))

    ## Price bounds

    max_price = cache.get_cached_object(cache.SharedCache.FRONTEND_MAX_PRICE)

    if max_price is None:
        max_price = Product.get_max_price()
        cache.put_cached_object(cache.SharedCache.FRONTEND_MAX_PRICE, max_price)

    application_data['extra'] = dict(
        price_bounds=(0, max_price,)
    )

    return render_template('new/index.html',
                           application_data=application_data)


@app.route('/explore/<category_title>-<int:category_id>.html')
def category(category_title, category_id):
    category = Category.query.get(category_id)
    if not category:
        return redirect(url_for('index'))

    application_data = prepare_application_data()
    extra = dict()

    ## Building tag list

    # tags = Tag.query.filter_by(is_approved=True).all()
    # extra['tags'] = [dict(id=tag.id, title=tag.tag) for tag in tags]

    top_category = category.get_parent() if category.parent_id else category
    category = category if category.parent_id else None
    displayed_category = category if category else top_category

    include_private = g.user.is_authenticated and g.user.premium_member

    cache_key = (cache.SharedCache.FRONTEND_CATEGORY_STATISTICS if not include_private else cache.SharedCache.FRONTEND_CATEGORY_STATISTICS_INCL_PRIVATE) % displayed_category.id
    displayed_category_statistics = cache.get_cached_object(cache_key)

    if not displayed_category_statistics:
        displayed_category_statistics = displayed_category.get_statistics(include_private=include_private)
        cache.put_cached_object(cache_key, displayed_category_statistics)

    application_data['extra'] = dict(
        category_id=category.id if category else None,
        top_category_id=top_category.id
    )

    return render_template('new/index.html',
                           application_data=application_data,
                           category=category,
                           top_category=top_category,
                           displayed_category=displayed_category,
                           displayed_category_statistics=displayed_category_statistics)


@app.route('/service/<product_title>-<product_id>.html')
def product(product_title, product_id):
    product = Product.get_by_custom_id(product_id)
    if not product:
        abort(404)

    if product.is_private and len(product_id) < 32:
        abort(404)

    # Check if product_title is not equal to the current seofied title -> do redirect
    if not product.is_private:
        product_title_seofied = product.get_title_seofied()
        if product_title_seofied != product_title:
            return redirect(url_for('product', product_title=product_title_seofied, product_id=product.unique_id), 301)

    # Check if the product isn't deleted and seller is active
    # UPD: do not send 404 on deleted product if it was approved before it was deleted
    if product.published_on is None or product.seller.is_deleted or product.seller.is_disabled:
        abort(404)

    # Do not allow view not approved product except for seller
    # UPD: products pending approval are now shown
    if product.not_approved and not (g.user.is_authenticated and product.seller_id == g.user.id) and not g.user.is_admin:
        abort(404)

    product.record_view(
        user_id=g.user.id if g.user.is_authenticated else None,
        ip=g.ip
    )

    product_categories = list()
    product_categories.append(Category.query.get(product.category_id))
    if product_categories[0].parent_id is not None:
        product_categories.insert(0, Category.query.get(product_categories[0].parent_id))

    product_tags = product.get_tags()

    product_seller = product.seller

    product_photos_count = len(product.get_photos())
    product_thumbnails_count = product_photos_count + len(product.get_videos())
    product_offer = product.get_active_offer()
    product_price_offer = product_offer.calculate_price(product.price) if product_offer else None
    product_statistics = product.get_statistics()
    product_faq = product.get_data('faq')
    product_seller_statistics = product_seller.get_statistics()
    product_is_favorite = product.is_favorite(g.user) if g.user.is_authenticated else False

    product_description = Markup(render_markdown(product.description))

    # Check if current user can order
    can_order = False
    if not (g.user.is_authenticated and product.seller_id == g.user.id):
        if product.quantity is None or product.quantity > 0:
            can_order = True

    if product.is_deleted:
        can_order = False

    application_data = prepare_application_data('service') # Bootstrap data for VUE application (to be parsed into JSON)

    ## Adding extra data

    application_data['extra'] = dict(
        product=product.to_json(),
        product_thumbnails_count=product_thumbnails_count,
        product_seller=product_seller.to_json(),
        product_is_favorite=product_is_favorite,
        product_seller_photo_url=product_seller.get_photo_url(ImagePresets.USER_PRIMARY)
    )

    return render_template(
        'new/product.html',
        application_data=application_data,
        product=product,
        can_order=can_order,
        product_categories=product_categories,
        product_tags=product_tags,
        product_seller=product_seller,
        product_offer=product_offer,
        product_price_offer=product_price_offer,
        product_statistics=product_statistics,
        product_faq=product_faq,
        product_seller_statistics=product_seller_statistics,
        product_photos_count=product_photos_count,
        product_description=product_description
    )


@app.route('/service/order/<product_title>-<product_id>.html')
def product_order(product_title, product_id):
    product = Product.get_by_custom_id(product_id)
    if not product:
        abort(404)

    if product.is_private and len(product_id) < 32:
        abort(404)

    # Check if the product isn't deleted and seller is active
    if product.is_deleted or product.published_on is None or product.seller.is_deleted or product.seller.is_disabled:
        abort(404)

    # Do not allow view not approved product except for seller
    if not product.is_approved and not (g.user.is_authenticated and product.seller_id == g.user.id):
        abort(404)

    enquiry_offer = None
    incoming_enquiry_offer_id = request.args.get('offer')

    # Enquiry offers are only can be used by authenticated users
    if incoming_enquiry_offer_id and g.user.is_authenticated:
        tmp_offer = EnquiryOffer.query.get(incoming_enquiry_offer_id)
        if tmp_offer and not tmp_offer.is_closed and not tmp_offer.is_accepted:
            enquiry = tmp_offer.get_enquiry()
            if enquiry.user_id == g.user.id and product.id == tmp_offer.product_id:
                enquiry_offer = tmp_offer

    if enquiry_offer:
        product_price = enquiry_offer.price
    else:
        product_offer = product.get_active_offer()
        product_price = product_offer.calculate_price(product.price) if product_offer else product.price

    # Check if current user can order
    can_order = False
    if not (g.user.is_authenticated and product.seller_id == g.user.id):
        if product.quantity is None or product.quantity > 0:
            can_order = True

    # User is not allowed to order this product
    # Redirect him back either to private or public product page
    if not can_order:
        return redirect(product.get_url())

    # Extras and requirements list
    product_extras = product.get_data('extras') or []

    product_prepared = prepare_product(product)

    # If source is specified - repeat previous order

    incoming_source = request.args.get('source')
    selected_product_extras = tuple()
    selected_discount_code = None

    if incoming_source:
        order = Order.query.filter(
            Order.stripe_source == incoming_source,
            Order.state.in_((Order.NEW, Order.CLOSED_CANCELLED,))
        ).first()

        if order and not (g.user.is_authenticated and order.buyer_id != g.user.id):
            selected_product_extras = order.get_data('extras') or tuple()

            discount = order.get_data('discount')
            if discount:
                discount = Discount.query.get(discount['id'])
                selected_discount_code = discount.code if discount else None

    # Bootstrap data for VUE application (to be parsed into JSON)

    application_data = prepare_application_data()

    application_data['extra'] = dict(
        product=product_prepared,
        product_seller=product.seller.to_json(),
        product_price=product_price,
        product_extras=product_extras,
        enquiry_offer_id=enquiry_offer.id if enquiry_offer else None,
        selected_product_extras=selected_product_extras,
        selected_discount_code=selected_discount_code,
        order_fee=app.config['ORDER_FEE'],
        stripe_key=app.config['STRIPE_PUBLISHABLE_KEY']
    )

    return render_template('new/order.html',
                           product=product,
                           application_data=application_data,
                           product_price=product_price,
                           product_seller=product.seller,
                           enquiry_offer=enquiry_offer,
                           order_fee=app.config['ORDER_FEE'],)


@app.route('/service/order/<custom_id>/payment')
def product_order_payment(custom_id):
    incoming_source = request.args.get('source')
    if not incoming_source:
        abort(404)

    product = Product.get_by_custom_id(custom_id)
    if not product:
        abort(404)

    order = Order.query.filter(
        Order.stripe_source == incoming_source,
        Order.state.in_((Order.NEW, Order.CLOSED_CANCELLED,))
    ).first()

    if not order or (g.user.is_authenticated and order.buyer_id != g.user.id):
        abort(404)

    order_fee = order.get_data('fee') or 0

    order_extras = order.get_data('extras') or tuple()

    order_discount = order.get_data('discount')
    if order_discount:
        order_discount = order_discount.get('value', 0)

    order_url = url_for(
        'product_order',
        product_id=custom_id,
        product_title=order.product.get_title_seofied(),
        source=incoming_source
    )

    product_offer = product.get_active_offer()
    product_price = product_offer.calculate_price(product.price) if product_offer else product.price

    product_prepared = prepare_product(product)

    application_data = prepare_application_data()

    application_data['extra'] = dict(
        product=product_prepared,
        order=dict(id=order.id),
        service=dict(id=product.get_custom_id())
    )

    return render_template('new/order-payment.html',
                           application_data=application_data,
                           product=product,
                           product_price=product_price,
                           order=order,
                           order_extras=order_extras,
                           order_discount=order_discount,
                           order_url=order_url,
                           order_fee=order_fee)


@app.route('/service/<product_id>/share/<platform>')
def product_share(product_id, platform):
    if platform not in ('facebook', 'twitter', 'googleplus', 'linkedin'):
        abort(404)

    product = Product.get_by_custom_id(product_id)
    if not product:
        abort(404)

    # Check if the product isn't deleted and seller is active
    if product.is_deleted or product.published_on is None or product.seller.is_deleted or product.seller.is_disabled:
        abort(404)

    # Do not allow view not approved but DO allow pending approval product
    if product.not_approved:
        abort(404)

    url = product.get_url(_external=True)

    if platform == 'facebook':
        url_query = urllib.urlencode((
            ('app_id', app.config['OAUTH_CREDENTIALS']['facebook']['id']),
            ('display', 'page'),
            ('href', url),
            ('redirect_uri', url)
        ))

        return redirect('https://www.facebook.com/dialog/share?%s' % url_query)
    elif platform == 'twitter':
        url_query = urllib.urlencode((
            ('text', 'Check out my service on JobDone.net'),
            ('url', url),
        ))

        return redirect('https://twitter.com/intent/tweet?%s' % url_query)
    elif platform == 'googleplus':
        url_query = urllib.urlencode((
            ('text', 'Check out my service on JobDone.net'),
            ('url', url),
        ))

        return redirect('https://plus.google.com/share?%s' % url_query)
    elif platform == 'linkedin':
        url_query = urllib.urlencode((
            ('title', 'Check out my service on JobDone.net'),
            ('url', url),
        ))

        return redirect('https://www.linkedin.com/shareArticle?%s' % url_query)


@app.route('/freelancer/<username>.html')
def user(username):
    user = User.get_active_by_username(username)
    if not user:
        abort(404)

    application_data = prepare_application_data()

    application_data['extra'] = dict(
        user=user.to_json(),
        user_photo_url=user.get_photo_url(ImagePresets.USER_PRIMARY)
    )

    if g.user.is_authenticated and g.user.id == user.id:
        application_data['extra']['profile_description'] = user.profile_description
        application_data['extra']['profile_headline'] = user.profile_headline

    user_statistics = user.get_statistics()

    user_endorsements = UserEndorsement.query.filter(
        UserEndorsement.user_id == user.id,
        UserEndorsement.publisher_user_id != None
    ).order_by(UserEndorsement.created_on.desc()).all()

    user_endorsements_prepared = list()

    for user_endorsement in user_endorsements:
        publisher = User.query.get(user_endorsement.publisher_user_id)  # TODO: optimize

        user_endorsements_prepared.append(dict(
            id=user_endorsement.id,
            text=user_endorsement.text,
            created_on=user_endorsement.created_on,
            _publisher_username=publisher.username,
            _publisher_photo_url=publisher.get_photo_url(ImagePresets.USER_PRIMARY)
        ))

    connected_accounts = UserSocialAccount.query.filter_by(user_id=user.id).all()
    connected_accounts_set = set(map(lambda account: account.provider, connected_accounts))
    user_accounts_prepared = list()

    for provider in ('facebook', 'google', 'linkedin'):
        user_accounts_prepared.append(dict(
            provider=provider,
            provider_pp=provider.title(),
            connected=(provider in connected_accounts_set)
        ))

    return render_template(
        'new/user.html',
        application_data=application_data,
        user=user,
        user_statistics=user_statistics,
        user_endorsements=user_endorsements_prepared,
        user_accounts=user_accounts_prepared
    )


@app.route('/freelancer/<username>/widget.js')
def user_widget(username):
    user = User.get_active_by_username(username)
    if not user or not user.seller_fee_paid:
        abort(404)

    incoming_avatar_type = request.args.get('avatar_type', type=int, default=1)
    incoming_widget_type = request.args.get('widget_type', type=int, default=0)

    user_headline = escape(user.profile_headline) if user.profile_headline else ''

    user_rating_int, _ = user.get_rating()
    user_rating_int = int(round(user_rating_int))

    return render_template(
        'user-widget.js',
        avatar_type=incoming_avatar_type,
        widget_type=incoming_widget_type,
        user=user,
        user_headline=user_headline,
        user_rating_int=user_rating_int
    ), 200, {'Content-Type': 'application/javascript; charset=utf-8'}


@app.route('/freelancer/<username>/endorse.html')
def user_endorse(username):
    from app.utils.data import skills

    user = User.get_active_by_username(username)
    if not user or not user.seller_fee_paid:
        abort(404)

    if g.user.is_authenticated and g.user.id == user.id:
        return redirect(url_for('user', username=username))

    user_skills = user.get_meta_data('skills') or list()

    for item in user_skills:
        skill_title, level_title = skills.resolve(item['id'], item['level_id'])
        item['title'] = skill_title
        item['level'] = level_title

    application_data = prepare_application_data()

    application_data['extra'] = dict(
        user=user.to_json(),
        user_skills=user_skills
    )

    return render_template(
        'new/user-endorse.html',
        application_data=application_data,
        user=user
    )


@app.route('/share/<unique_url_id>')
def affiliate_link(unique_url_id):
    affiliate_link = AffiliateLink.query.filter_by(unique_url_id=unique_url_id).first()
    if not affiliate_link or affiliate_link.is_deleted:
        abort(404)

    # TODO: record visit?

    return render_template('new/affiliate_link.html', affiliate_link=affiliate_link)


@app.route('/share/<unique_url_id>/platform/<platform>')
def affiliate_link_share(unique_url_id, platform):
    if platform not in ('facebook', 'twitter', 'googleplus', 'linkedin'):
        abort(404)

    affiliate_link = AffiliateLink.query.filter_by(unique_url_id=unique_url_id).first()
    if not affiliate_link or affiliate_link.is_deleted:
        abort(404)

    url = url_for(
        'affiliate_link',
        unique_url_id=unique_url_id,
        agent=g.user.username if g.user.is_authenticated else None,
        _external=True
    )

    if platform == 'facebook':
        url_query = urllib.urlencode((
            ('app_id', app.config['OAUTH_CREDENTIALS']['facebook']['id']),
            ('display', 'page'),
            ('href', url),
            ('redirect_uri', url)
        ))

        return redirect('https://www.facebook.com/dialog/share?%s' % url_query)
    elif platform == 'twitter':
        url_query = urllib.urlencode((
            ('url', url),
        ))

        return redirect('https://twitter.com/intent/tweet?%s' % url_query)
    elif platform == 'googleplus':
        url_query = urllib.urlencode((
            ('url', url),
        ))

        return redirect('https://plus.google.com/share?%s' % url_query)
    elif platform == 'linkedin':
        url_query = urllib.urlencode((
            ('url', url),
        ))

        return redirect('https://www.linkedin.com/shareArticle?%s' % url_query)


@app.route('/share/invite/<username>/platform/<platform>')
def invite_share(username, platform):
    if platform not in ('facebook', 'twitter', 'googleplus', 'linkedin'):
        abort(404)

    url = url_for(
        'index',
        mode='signup',
        invitation=username,
        _external=True
    )

    if platform == 'facebook':
        url_query = urllib.urlencode((
            ('app_id', app.config['OAUTH_CREDENTIALS']['facebook']['id']),
            ('display', 'page'),
            ('href', url),
            ('redirect_uri', url)
        ))

        return redirect('https://www.facebook.com/dialog/share?%s' % url_query)
    elif platform == 'twitter':
        url_query = urllib.urlencode((
            ('url', url),
        ))

        return redirect('https://twitter.com/intent/tweet?%s' % url_query)
    elif platform == 'googleplus':
        url_query = urllib.urlencode((
            ('url', url),
        ))

        return redirect('https://plus.google.com/share?%s' % url_query)
    elif platform == 'linkedin':
        url_query = urllib.urlencode((
            ('url', url),
        ))

        return redirect('https://www.linkedin.com/shareArticle?%s' % url_query)


@app.route('/share/invite/<username>/platform/<platform>')
def endorse_share(username, platform):
    if platform not in ('facebook', 'twitter', 'googleplus', 'linkedin'):
        abort(404)

    url = url_for(
        'user_endorse',
        username=username,
        _external=True
    )

    if platform == 'facebook':
        url_query = urllib.urlencode((
            ('app_id', app.config['OAUTH_CREDENTIALS']['facebook']['id']),
            ('display', 'page'),
            ('href', url),
            ('redirect_uri', url)
        ))

        return redirect('https://www.facebook.com/dialog/share?%s' % url_query)
    elif platform == 'twitter':
        url_query = urllib.urlencode((
            ('url', url),
        ))

        return redirect('https://twitter.com/intent/tweet?%s' % url_query)
    elif platform == 'googleplus':
        url_query = urllib.urlencode((
            ('url', url),
        ))

        return redirect('https://plus.google.com/share?%s' % url_query)
    elif platform == 'linkedin':
        url_query = urllib.urlencode((
            ('url', url),
        ))

        return redirect('https://www.linkedin.com/shareArticle?%s' % url_query)


@app.route('/support')
def support():
    return redirect(app.config['SUPPORT_URL'])


@app.route('/contact-us.html')
def contact_us():
    return redirect(url_for('support'))

    # Bootstrap data for VUE application (to be parsed into JSON)
    application_data = prepare_application_data()

    return render_template('new/contact_us.html', application_data=application_data)


@app.route('/terms.html')
def terms():
    # Bootstrap data for VUE application (to be parsed into JSON)
    application_data = prepare_application_data()

    return render_template('new/terms.html', application_data=application_data)


@app.route('/privacy.html')
def privacy():
    # Bootstrap data for VUE application (to be parsed into JSON)
    application_data = prepare_application_data()

    return render_template('new/privacy-policy.html', application_data=application_data)

@app.route('/content-policy.html')
def content_policy():
    # Bootstrap data for VUE application (to be parsed into JSON)
    application_data = prepare_application_data()

    return render_template('new/content-policy.html', application_data=application_data)


@app.route('/unsubscribe-settings.html')
def unsubscribe_settings():
    # Bootstrap data for VUE application (to be parsed into JSON)
    application_data = prepare_application_data()

    incoming_uuid = request.args.get('uuid', '')
    if len(incoming_uuid) != 32:
        abort(404)

    user = User.query.filter_by(uuid=incoming_uuid).first()

    if not user:
        abort(404)

    disabled_subscriptions = user.get_meta_data('disabled_subscriptions') or dict()

    application_data['extra'] = dict(
        disabled_subscriptions=disabled_subscriptions,
        uuid=incoming_uuid
    )

    return render_template(
        'new/unsubscribe-settings.html',
        application_data=application_data,
        user=user
    )


# @app.route('/unsubscribe.html')
# def unsubscribe():
#     # Bootstrap data for VUE application (to be parsed into JSON)
#     application_data = prepare_application_data()

#     return render_template('new/unsubscribe.html', application_data=application_data)


@app.route('/affiliate.html')
def affiliate():
    application_data = prepare_application_data()

    application_data['extra'] = dict(page='affiliate')

    return render_template('new/affiliate-landing.html', application_data=application_data)


@app.route('/become_seller.html')
def become_seller():
    from app.utils.country import COUNTRIES
    from app.utils.data import languages, skills

    if g.user.is_authenticated and g.user.seller_fee_paid:
        # User has already paid seller fee
        return redirect(url_for('account.seller'))

    application_data = prepare_application_data()

    if not g.user.is_authenticated:
        next_url = url_for('account.seller')
        application_data['extra'] = dict(next=next_url)
        return render_template('new/become-seller-landing.html', application_data=application_data, next=next_url)

    seller_fee = Variable.get_seller_fee()
    seller_fee_pp = '{0:.2f}'.format(seller_fee / 100.0)
    can_pay = (g.user.credit >= seller_fee)

    connected_accounts = UserSocialAccount.query.filter_by(user_id=g.user.id).all()
    connected_accounts_set = set(map(lambda account: account.provider, connected_accounts))

    user_meta_data = g.user.get_meta_data()
    user_languages = user_meta_data.get('languages', [dict(id='en', level_id=0)])
    user_skills = user_meta_data.get('skills', [])

    for item in user_languages:
        language_title, level_title = languages.resolve(item['id'], item['level_id'])
        item['title'] = language_title
        item['level'] = level_title

    for item in user_skills:
        skill_title, level_title = skills.resolve(item['id'], item['level_id'])
        item['title'] = skill_title
        item['level'] = level_title

    application_data['extra'] = dict(
        description=g.user.profile_description,
        headline=g.user.profile_headline,
        rate=u'{0:.2f}'.format(g.user.profile_rate / 100.0) if g.user.profile_rate else '',
        user_languages=user_languages,
        user_skills=user_skills
    )

    accounts_prepared = list()

    for provider in ('facebook', 'google', 'linkedin'):
        accounts_prepared.append(dict(
            provider=provider,
            provider_pp=provider.title(),
            connected=(provider in connected_accounts_set)
        ))

    return render_template(
        'new/become-seller.html',
        application_data=application_data,
        hide_footer=True,
        accounts=accounts_prepared,
        seller_fee=seller_fee,
        seller_fee_pp=seller_fee_pp,
        can_pay=can_pay,
        countries=COUNTRIES
    )


@app.route('/old')
def index_old():
    categories = Category.query_top()
    search_query = request.args.get('q')
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', '-date')
    include_private = (g.user.is_authenticated and g.user.premium_member)
    price = map(lambda key: request.args.get(key, 0, type=float) * 100, ('price_from', 'price_to'))

    date_filter = DATE_FILTER_LABELS[:1]
    date_filter += tuple(map(lambda label: (label[0], '%s - %d' % (label[1], search.count_search_products(search_query, include_private=include_private, since=datetime.utcnow() - timedelta(days=int(label[0])), price=price))), DATE_FILTER_LABELS[1:]))

    since = request.args.get('date', type=int)
    if since:
        since = datetime.utcnow() - timedelta(days=since)

    tags = Tag.query.filter_by(is_approved=True).all()

    selected_tags = ()
    selected_tags_ids = request.args.getlist('tags', type=int)

    if selected_tags_ids:
        selected_tags = Tag.get_multiple(selected_tags_ids)

    ids, total = search.search_products(q=search_query,
                                        include_private=include_private,
                                        since=since,
                                        start=((page - 1) * PRODUCTS_PER_PAGE),
                                        limit=PRODUCTS_PER_PAGE,
                                        price=price,
                                        tags=[tag.tag for tag in selected_tags])

    products = Product.get_multiple(ids)
    pagination = SearchPagination(products, page=page, total=total, per_page=PRODUCTS_PER_PAGE)

    return render_template('index.html', pagination=pagination, categories=categories, sorting=SORTING_LABELS, date_filter=date_filter, tags=tags, selected_tags_ids=selected_tags_ids)


@app.route('/atom.xml')
def atom_xml():
    kwargs = dict()
    referer = request.args.get('referer')
    if referer:
        kwargs['referer'] = referer

    products = Product.query_active().order_by(Product.created_on.desc()).limit(20)

    feed = AtomFeed('New products',
                    feed_url=url_for('atom_xml', _external=True),
                    url=url_for('index', _external=True))

    for product in products:
        feed.add(product.title, product.description, content_type='text',
                 id=product.id,
                 url=url_for('product', product_title=product.get_title_seofied(), product_id=product.unique_id, _external=True, **kwargs),
                 updated=product.created_on)

    return feed.get_response()


@app.route('/api/services/<unique_id>.json')
def product_json(unique_id):
    product = Product.query.filter_by(unique_id=unique_id).first()
    if not product:
        abort(404)

    # Check if the product isn't deleted and seller is active
    if product.is_deleted or product.seller.is_deleted:
        abort(404)

    return json.jsonify(dict(title=product.title, unique_id=unique_id, price=product.price_discount))


@app.route('/api/services/bulk.json')
def products_bulk_json():
    ids = request.args.get('ids')
    if not ids:
        return make_response(json.jsonify(dict()), 404)

    products = Product.query.filter(Product.unique_id.in_(ids.split(','))).limit(6)

    products_jsonified = []
    for product in products:
        if not product:
            return make_response(json.jsonify(dict()), 404)

        # Check if the product isn't deleted and seller is active
        if product.is_deleted or product.seller.is_deleted:
            return make_response(json.jsonify(dict()), 404)

        photo_url = None
        photo = product.get_primary_photo()

        if photo:
            photo_url = static_file_url(photo.get_thumb_url())

        products_jsonified.append(
            dict(
                title=product.title,
                unique_id=product.unique_id,
                price_offer=product.price_offer if product.active_offer_id else None,
                price=product.price,
                seller_username=product.seller.username,
                url=url_for('product', product_title=product.title, product_id=product.unique_id),
                photo_url=photo_url,
                category_title=product.category.title if product.category else None
            )
        )

    return json.jsonify(products_jsonified)


@app.route('/api/tags')
def tags_json():
    tags_query = Tag.query.filter(Tag.is_approved==True)

    search = request.args.get('search', None)
    if search:
        tags_query = tags_query.filter(Tag.tag.like(search + '%'))

    tags = tags_query.all()

    return json.jsonify(map(lambda tag: tag.tag, tags))


@app.route("/robots.txt")
def robots_txt():
    #TODO:check if who want to download sitemap.xml is googlebot or bingbot. 1. check useragent 2. check reverse dns.

    user_agents = {'bingbot','googlebot','adsbot-google','mediapartners'}
    if not any(agent in str(request.headers.get('User-Agent')).lower() for agent in user_agents):
        abort(404)

    # try:
    #     dnsbots = {'googlebot.com', 'search.msn.com'}
    #     remote_addr = gethostbyaddr(str(request.remote_addr))[0]
    #     if not any(dnsbot in str(remote_addr).lower() for dnsbot in dnsbots):
    #         abort(404)
    # except:
    #     abort(404)

    return send_from_directory(app.static_folder, 'robots.txt')


@app.route("/sitemap.xml")
def sitemap_xml():
    #TODO:check if who want to download sitemap.xml is googlebot or bingbot. 1. check useragent 2. check reverse dns.

    user_agents = {'bingbot','googlebot','adsbot-google','mediapartners'}
    if not any(agent in str(request.headers.get('User-Agent')).lower() for agent in user_agents):
        abort(404)

    # try:
    #     dnsbots = {'googlebot.com', 'search.msn.com'}
    #     remote_addr = gethostbyaddr(str(request.remote_addr))[0]
    #     if not any(dnsbot in str(remote_addr).lower() for dnsbot in dnsbots):
    #         abort(404)
    # except:
    #     abort(404)

    return send_from_directory(app.static_folder, 'sitemap.xml')


@app.route("/opensearch.xml")
def opensearch_xml():
    return send_from_directory(app.static_folder, 'opensearch.xml')
