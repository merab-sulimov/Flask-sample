import sys
import os
import requests
from tempfile import mktemp
from flask_script import prompt_bool
from flask import url_for

from app import app, db
from app.models import Product, ProductPhoto
from app.utils.storage import Storage


def images_uploads():
    if not prompt_bool("Converting local image uploads (ProductPhotos) to S3 and Cloudinary. Please confirm operation:"):
        print "Cancelled"
        return

    storage = Storage()

    products = Product.query.all()
    for product in products:
        print "Working on %s..." % product.title

        photos = product.get_data('photos')
        if photos:
            print "Already converted. Checking if primary_photo_key is set..."
            if not product.primary_photo_key:
                primary_photo_key = photos[0]['cloudinary_key']
                product.primary_photo_key = primary_photo_key
                db.session.add(product)
                db.session.commit()

            print "Updating photos with IDs"
            product.set_photos(photos)

            continue

        for photo in product.product_photos:
            filename = os.path.join(app.config['UPLOAD_FOLDER'], str(product.id), photo.filename)
            print "Uploading %s" % filename

            with open(filename, 'r') as f:
                photo_aws_key, photo_cloudinary_key = storage.upload_product_photo(f, product.id, product.get_title_seofied(), filename=photo.filename)
                
                photos = list()
                photos.append(dict(aws_key=photo_aws_key, cloudinary_key=photo_cloudinary_key))
                product.set_data('photos', photos)

                db.session.add(product)
                db.session.commit()


def videos_from_cloudinary():
    if not prompt_bool("Converting videos from Cloudinary to use our service. Please confirm operation:"):
        print "Cancelled"
        return

    storage = Storage()

    products = Product.query.filter(Product.data_json != None, Product.data_json.ilike(r'%"videos": [{%')).all()
    for product in products:
        print "Working on %s..." % product.unique_id

        videos = product.get_data('videos')
        converted_videos = list()

        for video in videos:
            if 'cloudinary_key' not in video:
                print "Skipping already converted video"
                continue

            converted_video = dict(id=video['id'])
            if 'md5' in video:
                converted_video['md5'] = video['md5']

            resp = requests.get('https://res.cloudinary.com/selfmarket/video/upload/q_95/%s.mp4' % video['cloudinary_key'])

            temp_file_name = mktemp()
            with open(temp_file_name, 'w+b') as temp_file:
                temp_file.write(resp.content)

            mimetype = resp.headers.get('content-type', 'video/mp4')
            filename = '%s.%s' % (video['cloudinary_key'], mimetype.split('/')[-1])

            print "Attempting to convert %s with mimetype=%s and filename=%s" % (video['cloudinary_key'], mimetype, filename)

            callback_url = url_for('webhooks_video_convert', _external=True)

            with open(temp_file_name, 'r+b') as temp_file:
                converted_video['key'] = storage.upload_product_video(temp_file, callback_url, mimetype=mimetype, filename=filename)

            if not converted_video['key']:
                raise Exception('Can\'t convert video %s' % video['cloudinary_key'])

            print "Done. Key=%s" % converted_video['key']

            if product.primary_photo_key == 'video:%s' % video['cloudinary_key']:
                product.primary_photo_key = 'video:%s' % converted_video['key']

            converted_videos.append(converted_video)

        product.set_videos(converted_videos)
        db.session.add(product)
        db.session.commit()


operations = dict(images_uploads=images_uploads, videos_from_cloudinary=videos_from_cloudinary)
