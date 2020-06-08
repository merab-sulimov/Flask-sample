import os
from flask import flash, url_for, redirect, render_template, json, request, g, abort
from flask_login import login_required
from datetime import datetime, timedelta
from PIL import Image

from UniversalAnalytics import Tracker
from app import app, db, search
from app.decorators import xhr_required, seller_required
from app.models import Order, Product, Tag, Category, TransactionError
from app.helpers import APIError
from app.utils.storage import Storage
from app.utils import slack, render_markdown
from .. import account
from ..forms import ServiceCreateAPIForm, ServiceUpdateAPIForm
from ..helpers import prepare_application_data, prepare_category_tree


ORDERS_STATE_MAPPING = {
    'active': (Order.NEW, Order.ACCEPTED,),
    'needs_action': (Order.DISPUTE,), # TODO: add another state for missing details?
    'needs_review': (Order.CLOSED_COMPLETED,), # TODO: extra query
    'delivered': (Order.SENT,),
    'completed': (Order.CLOSED_COMPLETED,),
    'cancelled': (Order.CLOSED_CANCELLED, Order.CLOSED_REJECTED,)
}


@account.route('/account/seller/service/create')
@login_required
@seller_required
def service_create():
    if not g.user.can_publish_products:
        flash('You can\'t add more service, has finish limit of your seller level')
        return redirect(url_for('account.index'))

    application_data = prepare_application_data()

    application_data['extra'] = dict(
        categories=prepare_category_tree(),
        min_price=app.config['SERVICE_PRICE_RANGE'][0],
        stripe_key=app.config['STRIPE_PUBLISHABLE_KEY']
    )

    return render_template('new/account/service.html', application_data=application_data)


@account.route('/account/seller/service/<unique_id>/edit')
@login_required
@seller_required
def service_edit(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id:
        abort(404)

    if service.is_deleted:
        return redirect(service.get_url())

    application_data = prepare_application_data()

    prepared_service = service.to_json()
    prepared_service['description'] = service.description
    prepared_service['is_private'] = service.is_private
    prepared_service['revision_count'] = service.revision_count
    prepared_service['category_id'] = service.category_id
    prepared_service['published_on'] = service.published_on.isoformat() if service.published_on else None
    prepared_service['is_approved'] = service.is_approved
    prepared_service['faqs'] = service.get_data('faq')
    prepared_service['tags'] = service.get_data('tags')
    prepared_service['requirements'] = service.get_data('requirements')
    prepared_service['extras'] = service.get_data('extras')
    prepared_service['features'] = service.get_features()

    # List all available features
    features = app.config['SERVICE_FEATURES']

    application_data['extra'] = dict(
        categories=prepare_category_tree(),
        service=prepared_service,
        min_price=app.config['SERVICE_PRICE_RANGE'][0],
        features=features,
        stripe_key=app.config['STRIPE_PUBLISHABLE_KEY'],
        user_credit=g.user.credit,
        user_bonus_credit=g.user.bonus_credit
    )

    try:
        gallery_video_category = Category.query.get(app.config['GALLERY_CATEGORY_IDS']['video'])
        gallery_photo_category = Category.query.get(app.config['GALLERY_CATEGORY_IDS']['photo'])
    except:
        gallery_video_category = gallery_photo_category = None

    gallery_min_photo_dimensions = '%dx%d' % app.config['PHOTO_SIZE']

    return render_template(
        'new/account/service.html',
        application_data=application_data,
        gallery_video_category=gallery_video_category,
        gallery_photo_category=gallery_photo_category,
        gallery_min_photo_dimensions=gallery_min_photo_dimensions
    )


@account.route('/api/account/seller/services', methods=['POST'])
@login_required
@xhr_required
@seller_required
def api_services_create():
    incoming = request.get_json()
    form = ServiceCreateAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        service = Product(
            seller_id=g.user.id,
            unique_id=Product.get_unique_id(),
            title=form.title.data,
            category_id=form.category_id.data,
            description=form.description.data
        )

        if form.faqs.data:
            service.set_data('faq', form.faqs.data)

        if form.tags.data:
            service.set_data('tags', form.tags.data)

        if form.is_private.data:
            # form.is_private.data will always contain True if is_private was sent
            # Workaround: use incoming dict to check actual value of is_private
            if incoming['is_private']:
                service.set_private()

        db.session.add(service)
        db.session.commit()

        if form.tags.data:
            # This is intentially left after updating the service
            Tag.create_multiple(form.tags.data)

        prepared_service = service.to_json()
        prepared_service['_edit_url'] = '%s#?tab=1' % url_for('account.service_edit', unique_id=service.unique_id, _external=True)

        return json.jsonify(prepared_service)
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/seller/services/<unique_id>', methods=['PUT'])
@login_required
@xhr_required
@seller_required
def api_services_update(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    incoming = request.get_json()
    form = ServiceUpdateAPIForm(csrf_enabled=False)
    form.validate()

    errors = dict()
    changed = dict()

    def check_incoming_field(field, auto_update=True):
        if incoming.has_key(field):
            if field in form.errors:
                errors[field] = form.errors[field]
                return False
            else:
                if auto_update:
                    setattr(service, field, form[field].data)
                changed[field] = form[field].data
                return True

        return False

    map(check_incoming_field, ['title', 'category_id', 'description', 'price'])
    check_incoming_field('faqs', False)
    check_incoming_field('tags', False)
    check_incoming_field('requirements', False)
    check_incoming_field('extras', False)
    check_incoming_field('delivery_time', False)
    check_incoming_field('revision_count', False)

    if errors:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=errors))

    if not changed:
        prepared_service = service.to_json()
        prepared_service['_url'] = service.get_url(_external=True)
        return json.jsonify(prepared_service)

    # Update service

    if 'faqs' in changed:
        service.set_data('faq', changed['faqs'])

    if 'tags' in changed:
        service.set_data('tags', changed['tags'])

    if 'requirements' in changed:
        service.set_requirements(changed['requirements'])

    if 'extras' in changed:
        service.set_extras(changed['extras'])

    if 'delivery_time' in changed:
        service.delivery_time = timedelta(days=changed['delivery_time'])

    if 'revision_count' in changed:
        service.revision_count = changed['revision_count']

    if 'title' in changed or 'description' in changed or 'faqs' in changed or 'requirements' in changed or 'extras' in changed:
        # TODO: should only set service as not approved in case actual data has been changed
        # service.is_approved = False
        # service.not_approved = False

        # UPD: We disable this option for some time
        pass
            
    db.session.add(service)
    db.session.commit()

    if 'tags' in changed:
        # This is intentially left after updating the service
        Tag.create_multiple(changed['tags'])

    if service.is_approved and not service.is_private:
        search.product_updated.send(product=service)
    else:
        search.product_deleted.send(product=service)

    prepared_service = service.to_json()
    prepared_service['_url'] = service.get_url(_external=True)

    return json.jsonify(prepared_service)


@account.route('/api/account/seller/services/<unique_id>/publish', methods=['POST'])
@login_required
@seller_required
def api_services_publish(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    if not service.price or not service.delivery_time:
        # Do not allow publish service without price and delivery time
        raise APIError('Please check that you\'ve selected price and delivery time for your service')

    service.published_on = datetime.utcnow()

    db.session.add(service)
    db.session.commit()

    if service.is_approved:
        search.product_updated.send(product=service)

    slack.notification('{} ADDED NEW SERVICE IN PENDING'.format(g.user.username), icon=slack.Icons.DANGER)

    # send event to Google Analytics
    tracker = Tracker.create('UA-86740209-1')
    tracker.send('event', 'NewService', g.user.username, unique_id)
    del tracker

    return json.jsonify(service.to_json())


@account.route('/api/account/seller/services/<unique_id>/pause', methods=['POST'])
@login_required
@seller_required
def api_services_pause(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    service.published_on = None

    db.session.add(service)
    db.session.commit()

    search.product_deleted.send(product=service)

    return json.jsonify(service.to_json())


@account.route('/api/account/seller/services/<unique_id>/resume', methods=['POST'])
@login_required
@seller_required
def api_services_start(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    service.published_on = datetime.utcnow()

    db.session.add(service)
    db.session.commit()

    if service.is_approved:
        search.product_updated.send(product=service)

    return json.jsonify(service.to_json())


@account.route('/api/account/seller/services/<unique_id>/delete', methods=['POST'])
@login_required
@seller_required
def api_services_delete(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    service.is_deleted = True

    db.session.add(service)
    db.session.commit()

    search.product_deleted.send(product=service)

    return json.jsonify(service.to_json())


@account.route('/api/account/seller/services/<unique_id>/urls')
@login_required
@seller_required
def api_services_urls(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    urls = dict()
    urls['external'] = service.get_url(_external=True)

    for platform in ['facebook', 'twitter', 'linkedin', 'googleplus']:
        urls[platform] = url_for('product_share', product_id=unique_id, platform=platform)

    urls['mailto'] = service.get_mailto_url()

    return json.jsonify(urls)


@account.route('/api/account/seller/services/<unique_id>/photos')
@xhr_required
@login_required
@seller_required
def api_services_photos(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    photos = service.get_data('photos') or list()
    photos_prepared = list()
    
    for photo in photos:
        photos_prepared.append(dict(
            id=photo.get('id', None),
            md5=photo.get('md5', None),
            primary=(service.primary_photo_key == photo['cloudinary_key']),
            url=Storage.get_product_photo_url(photo, 'w_135,h_118,c_fill,g_center')
        ))

    return json.jsonify(photos_prepared)


@account.route('/api/account/seller/services/<unique_id>/photos', methods=['POST'])
@login_required
@seller_required
def api_services_photos_upload(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    # Check photo size
    photo_fileobj = request.files['photo']
    min_photo_size = app.config.get('PHOTO_SIZE')
    allowed_photo_formats = app.config.get('ALLOWED_PHOTO_FORMATS')

    try:
        image = Image.open(photo_fileobj)
        if image.format not in allowed_photo_formats:
            raise
    except:
        raise APIError('Image format cannot be identified. Supported formats are: JPG, PNG')

    if image.size[0] < min_photo_size[0] or image.size[1] < min_photo_size[1]:
        raise APIError('Minimum allowed image size is %dx%d' % min_photo_size)

    photo_fileobj.seek(0, os.SEEK_END)  # Seek to the end to be able to stat file

    size_bytes = photo_fileobj.tell()

    if size_bytes > 5 * 1024 * 1024:
        raise APIError('Maximum allowed size is 5MB')

    photo_fileobj.seek(0)  # Seek file back so S3 uploader can read it from the beginning

    incoming_md5 = request.form.get('md5', None)

    storage = Storage()
    photo_aws_key, photo_cloudinary_key = storage.upload_product_photo(request.files['photo'], service.id, service.get_title_seofied())

    photos = service.get_data('photos')
    if not photos:
        photos = list()

    photos.append(dict(aws_key=photo_aws_key, cloudinary_key=photo_cloudinary_key, md5=incoming_md5))
    service.set_photos(photos)

    if len(photos) == 1 and not service.primary_photo_key:
        # It's the first photo, make it primary
        service.primary_photo_key = photos[0]['cloudinary_key']

    db.session.add(service)
    db.session.commit()

    photos_prepared = list()
    
    for photo in photos:
        photos_prepared.append(dict(
            id=photo.get('id', None),
            md5=photo.get('md5', None),
            primary=(service.primary_photo_key == photo['cloudinary_key']),
            url=Storage.get_product_photo_url(photo, 'w_135,h_118,c_fill,g_north_west')
        ))

    return json.jsonify(photos_prepared)


@account.route('/api/account/seller/services/<unique_id>/photos/<photo_id>', methods=['DELETE'])
@login_required
@seller_required
def api_services_photos_delete(unique_id, photo_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    photos = service.get_data('photos')
    if not photos:
        photos = list()

    photos_modified = list()
    photo_removed = None

    for photo in photos:
        if 'id' in photo and photo['id'] == photo_id:
            photo_removed = photo
        else:
            photos_modified.append(photo)

    if not photo_removed:
        abort(404)

    storage = Storage()
    storage.delete_product_photo(photo_removed['aws_key'], photo_removed['cloudinary_key'])

    if service.primary_photo_key == photo_removed['cloudinary_key']:
        service.primary_photo_key = None
        if photos_modified:
            service.primary_photo_key = photos_modified[0]['cloudinary_key']
        else:
            videos = service.get_data('videos')
            if videos:
                service.primary_photo_key = 'video:%s' % videos[0]['key']

    service.set_photos(photos_modified)

    db.session.add(service)
    db.session.commit()

    photos_prepared = list()
    
    for photo in photos_modified:
        photos_prepared.append(dict(
            id=photo.get('id', None),
            md5=photo.get('md5', None),
            primary=(service.primary_photo_key == photo['cloudinary_key']),
            url=Storage.get_product_photo_url(photo, 'w_135,h_118,c_fill,g_north_west')
        ))

    return json.jsonify(photos_prepared)


@account.route('/api/account/seller/services/<unique_id>/gallery/<item_id>/primary', methods=['POST'])
@login_required
@seller_required
def api_services_gallery_primary(unique_id, item_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    photos = service.get_data('photos')
    if not photos:
        photos = list()

    photo_primary = None

    for photo in photos:
        if 'id' in photo and photo['id'] == item_id:
            photo_primary = photo

    if photo_primary:
        service.primary_photo_key = photo_primary['cloudinary_key']
        
        db.session.add(service)
        db.session.commit()
    else:
        videos = service.get_data('videos')
        if not videos:
            videos = list()

        video_primary = None

        for video in videos:
            if 'id' in video and video['id'] == item_id:
                video_primary = video

        if not video_primary:
            abort(404)

        service.primary_photo_key = 'video:%s' % video_primary['key']
        db.session.add(service)
        db.session.commit()

    return json.jsonify(dict())


@account.route('/api/account/seller/services/<unique_id>/videos')
@xhr_required
@login_required
@seller_required
def api_services_videos(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    videos = service.get_data('videos') or list()
    videos_prepared = list()
    
    for video in videos:
        videos_prepared.append(dict(
            id=video.get('id', None),
            md5=video.get('md5', None),
            url=Storage.get_product_video_poster_url(video['key']),
            code=Storage.get_product_video_code(video['key']),
            primary=(service.primary_photo_key == 'video:%s' % video['key'])
        ))

    return json.jsonify(videos_prepared)


@account.route('/api/account/seller/services/<unique_id>/videos', methods=['POST'])
@login_required
@seller_required
def api_services_videos_upload(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    storage = Storage()

    try:
        file = request.files['video']
    except IndexError:
        # TODO: Use custom exception here is better: Ovveride exception class and add exception handler via @app.errorhandler.
        abort(400)

    #TODO: we have code duplication on both client and server sides. Better to use common constants and pass them to clientside
    #TODO: on initial rendering or via api (like route /serverconstants)

    MIMETYPES = [
        "video/mp4",
        "video/webm",
        "video/ogg"
    ]

    if file.content_type not in MIMETYPES:
        #TODO: again better solution is to customize exception
        raise APIError('Video format cannot be identified. Supported formats are: MP4, WEBM, OGV')

    video_key = storage.upload_product_video(file, url_for('webhooks_video_convert', _external=True))

    if not video_key:
        # TODO: report to sentry?
        abort(500)

    incoming_md5 = request.form.get('md5', None)
    video_metadata = dict(key=video_key, md5=incoming_md5)

    videos = service.get_data('videos')
    if not videos:
        videos = list()

    videos.append(video_metadata)
    service.set_videos(videos)

    if len(videos) == 1 and not service.primary_photo_key:
        # It's the first video, make it primary
        service.primary_photo_key = 'video:%s' % videos[0]['key']

    db.session.add(service)
    db.session.commit()

    videos_prepared = list()
    
    for video in videos:
        videos_prepared.append(dict(
            id=video.get('id', None),
            md5=video.get('md5', None),
            url=Storage.get_product_video_poster_url(video['key']),
            code=Storage.get_product_video_code(video['key']),
            primary=(service.primary_photo_key == 'video:%s' % video['key'])
        ))

    return json.jsonify(videos_prepared)


@account.route('/api/account/seller/services/<unique_id>/videos/<video_id>', methods=['DELETE'])
@login_required
@seller_required
def api_services_videos_delete(unique_id, video_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    videos = service.get_data('videos')
    if not videos:
        videos = list()

    videos_modified = list()
    video_removed = None

    for video in videos:
        if 'id' in video and video['id'] == video_id:
            video_removed = video
        else:
            videos_modified.append(video)

    if not video_removed:
        abort(404)

    storage = Storage()
    storage.delete_product_video(video_removed['key'])

    if service.primary_photo_key == 'video:%s' % video_removed['key']:
        service.primary_photo_key = None
        if videos_modified:
            service.primary_photo_key = 'video:%s' % videos_modified[0]['key']
        else:
            photos = service.get_data('photos')
            if photos:
                service.primary_photo_key = photos[0]['cloudinary_key']

    service.set_videos(videos_modified)

    db.session.add(service)
    db.session.commit()

    videos_prepared = list()
    
    for video in videos_modified:
        videos_prepared.append(dict(
            id=video.get('id', None),
            md5=video.get('md5', None),
            url=Storage.get_product_video_poster_url(video['key']),
            code=Storage.get_product_video_code(video['key']),
            primary=(service.primary_photo_key == 'video:%s' % video['key'])
        ))

    return json.jsonify(videos_prepared)


@account.route('/api/account/seller/services/<unique_id>/feature', methods=['POST'])
@login_required
@seller_required
def api_services_feature(unique_id):
    service = Product.get_by_custom_id(unique_id)
    if not service or service.seller_id != g.user.id or service.is_deleted:
        abort(404)

    incoming = request.get_json()
    result = list()

    try:
        for incoming_id in incoming:
            amount, bonus_account = service.order_feature(incoming_id)
            result.append(dict(id=incoming_id, amount=amount, bonus_account=bonus_account))
    except TransactionError, e:
        raise APIError(e.message, payload=dict(features=service.get_features(), no_credit=True))
    except Exception, e:
        raise APIError(e.message, payload=dict(features=service.get_features()))

    if service.is_highlighted:
        search.product_updated.send(product=service)

    if result:
        # If at least one of the features has been ordered - enable Auto Approve for this service
        service.set_auto_approve()

    slack.notification_sale(
        'Ordered features by {0}. {1}'.format(
            g.user.username,
            ', '.join(['{0} for {1}{2:.2f}'.format(item['id'], 'B' if item['bonus_account'] else '$', item['amount'] / 100.0) for item in result])
        )
    )

    return json.jsonify(dict(features=service.get_features(), is_approved=service.is_approved))


# @account.route('/api/account/seller/services/<unique_id>/auto_approve', methods=['POST'])
# @login_required
# @seller_required
# def api_services_auto_approve(unique_id):
#     service = Product.get_by_custom_id(unique_id)
#     if not service or service.seller_id != g.user.id or service.is_deleted:
#         abort(404)

#     if service.get_data('auto_approve'):
#         abort(403)

#     try:
#         amount, bonus_credit = service.order_auto_approve()
#     except TransactionError, e:
#         raise APIError(e.message, payload=dict(no_credit=True))
#     except Exception, e:
#         raise APIError(e.message)

#     search.product_updated.send(product=service)

#     slack.notification_sale(
#         'Ordered Auto Approve by {0} for {1}{2:.2f}'.format(
#             g.user.username,
#             'B' if bonus_credit else '$',
#             amount / 100.0
#         )
#     )

#     return json.jsonify(dict(features=service.get_features()))


@account.route('/api/account/seller/services/<unique_id>/description/render', methods=['POST'])
@login_required
@seller_required
def api_services_description_render(unique_id):
    incoming = request.get_json()
    incoming_text = incoming.get('text')
 
    return render_markdown(incoming_text)
