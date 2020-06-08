from flask import g, url_for
from datetime import datetime

from app import app, cache
from app.models import Category
from app.messaging import NotificationTypes
from app.utils.storage import Storage, ImagePresets


def prepare_product(product):
    product_prepared = product.to_json()
    product_prepared['is_highlighted'] = bool(product.is_highlighted)
    product_prepared['_is_pro'] = bool(product.seller.premium_member)
    product_prepared['_is_new'] = (datetime.utcnow() - product.published_on).days < app.config['NEW_SERVICE_DAYS'] if product.published_on else False
    product_prepared['_url'] = url_for('product', product_title=product.get_title_seofied(), product_id=product.unique_id)
    product_prepared['_seller'] = product.seller.profile_display_name
    product_prepared['_seller_url'] = url_for('user', username=product.seller.username)
    product_prepared['_seller_is_online'] = product.seller.is_online
    product_prepared['_seller_level'] = product.seller.level.code
    product_prepared['_seller_rating'] = product.seller.rating
    product_prepared['_seller_photo_url'] = product.seller.get_photo_url(ImagePresets.USER_ICON)
    product_prepared['_tags'] = [tag.tag for tag in product.get_tags()]
    product_prepared['_primary_photo_url'] = product.get_primary_photo(ImagePresets.SERVICE_THUMB_PRIMARY)
    product_prepared['_primary_photo_url_smaller'] = product.get_primary_photo(ImagePresets.SERVICE_THUMB_SECONDARY)

    if product.primary_photo_key and product.primary_photo_key.startswith('video:'):
        product_prepared['_primary_video_key'] = product.primary_photo_key[6:]
        product_prepared['_primary_video_poster_url'] = Storage.get_product_video_poster_url(product.primary_photo_key[6:])
        product_prepared['_primary_video_urls'] = { format: Storage.get_product_video_url(product.primary_photo_key[6:], format) for format in ['mp4', 'webm'] }

    cache_key = cache.SharedCache.FRONTEND_SERVICE_STATISTICS % product.id
    product_statistics = cache.get_cached_object(cache_key)

    if not product_statistics:
        product_statistics = product.get_statistics()
        cache.put_cached_object(cache_key, product_statistics, expire=3600)

    product_prepared['_feedbacks_rating'] = product_statistics['feedbacks_rating']
    product_prepared['_completed_count'] = product_statistics['completed']

    # TODO: maybe do a JOIN on FavoriteProduct table?
    product_prepared['_is_favorite'] = product.is_favorite(g.user) if g.user.is_authenticated else False

    return product_prepared


def prepare_application_data(module=None):
    application_data = dict(module=module)

    ## Routes

    application_data['urls'] = dict(
        order=url_for('account.order', order_id='ARG0'),
        inbox='%s#?type=ARG0&id=ARG1' % url_for('account.inbox'),
        oauth_authorize=url_for('auth.oauth_authorize', provider='ARG0', next='ARG1', page='ARG2')
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

    user_prepared = None
    if g.user.is_authenticated:
        user_prepared = g.user.to_json()
        user_prepared['email'] = g.user.email
        user_prepared['credit'] = g.user.credit

    application_data['user'] = user_prepared

    ## Building category tree

    categories_top = cache.get_cached_object(cache.SharedCache.FRONTEND_CATEGORY_TREE)

    if not categories_top:
        categories_all = Category.query_active().all()
        categories_top = list()
        categories_top_dict = dict()

        for category in categories_all:
            if category.parent_id is None:
                categories_top.append(dict(id=category.id, title=category.title, _title_seofied=category.get_title_seofied(), _url=url_for('category', category_title=category.get_title_seofied(), category_id=category.id)))
                continue

            categories_top_dict.setdefault(category.parent_id, []).append(dict(
                id=category.id,
                title=category.title,
                _title_seofied=category.get_title_seofied(),
                count=category.get_active_products_count()
            ))

        for category in categories_top:
            category['subcategories'] = categories_top_dict.get(category['id'], [])

        cache.put_cached_object(cache.SharedCache.FRONTEND_CATEGORY_TREE, categories_top)
        
    application_data['categories'] = categories_top

    return application_data
