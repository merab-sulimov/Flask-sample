import os
import random
import string
import boto3
import uuid
import cloudinary
import cloudinary.uploader
import urllib2
import requests
import json
from tempfile import mkdtemp
from os import path
from urlparse import urlparse
from botocore.client import Config

from app import app
from app import cache


class ImagePresets:
    """
    Image presets are used to cache most useful transformations of the images.
    Presets are defined on the Image Service side. See file presets.json
    """

    USER_ICON = 'p_ui'  # Micro icon for the index page left to seller's name. h_52,w_52,c_thumb,g_face
    USER_PRIMARY = 'p_up'  # Primary 100x100 user icon. h_100,w_100,c_thumb,g_face
    SERVICE_THUMB_PRIMARY = 'p_stp'  # Main thumbnail for the index page. c_pad,g_center,h_148,w_255,q_90
    SERVICE_THUMB_SECONDARY = 'p_sts'  # Smaller thumbnail - used on seller and freelancer pages. c_pad,g_center,h_113,w_192,q_90
    SERVICE_THUMB_CAROUSEL = 'p_stc'  # Thumbnails in carousel. c_fill,g_center,w_145,h_70,q_90
    SERVICE_PRIMARY = 'p_sp'  # Primary photo of the service on the service page. c_pad,g_center,h_400,w_670


VIDEO_PROCESSING_EXPIRE = 30*60


class Storage:
    class ImageType:
        USER_IMAGE = 'u'
        USER_VERIFICATION_IMAGE = 'uv'
        USER_COVER_IMAGE = 'uc'
        AFFILIATE_LINK_IMAGE = 'al'

    @staticmethod
    def get_product_photo_url(photo, transform='', product_title=None, protocol='https'):
        if app.config.get('USE_JOBDONE_IMAGE_SERVICE') and 'aws_key' in photo:
            return u'{0}://img.jobdone.net/s3/{1}/{2}'.format(protocol, transform, photo['aws_key'])

        key = photo['cloudinary_key']
        directory = 'image/upload'

        if product_title:
            key = '/'.join((photo['cloudinary_key'], product_title))
            directory = 'images'

        return u'{0}://res.cloudinary.com/{1}/{2}/{3}/{4}.jpg'.format(protocol, app.config.get('CLOUDINARY_CLOUD_NAME'), directory, transform, key)

    @staticmethod
    def get_image_url(type, image_object, transform='', protocol='https'):
        if app.config.get('USE_JOBDONE_IMAGE_SERVICE') and 'aws_key' in image_object:
            return u'{0}://img.jobdone.net/s3/{1}/{2}'.format(protocol, transform, image_object['aws_key'])

        return u'{0}://res.cloudinary.com/{1}/image/upload/{2}/{3}.png'.format(
            protocol,
            app.config.get('CLOUDINARY_CLOUD_NAME'),
            transform,
            image_object['cloudinary_key']
        )

    @staticmethod
    def get_image_aws_url(aws_key):
        configuration = app.config.get('AWS_IMAGES_CONFIGURATION')
        return u'https://{0}.s3.amazonaws.com/{1}'.format(configuration['bucket'], aws_key)

    @staticmethod
    def get_profile_photo_url(image_object, transform=''):
        return Storage.get_image_url(Storage.ImageType.USER_IMAGE, image_object, transform)

    @staticmethod
    def get_profile_cover_url(image_object, transform=''):
        return Storage.get_image_url(Storage.ImageType.USER_COVER_IMAGE, image_object, transform)

    @staticmethod
    def get_attachment_aws_url(attachment_id, filename):
        configuration = app.config.get('AWS_ATTACHMENTS_CONFIGURATION')
        return u'https://{0}.s3.amazonaws.com/{1}/{2}/{3}'.format(configuration['bucket'], configuration['prefix'], attachment_id, filename)

    @staticmethod
    def get_product_video_poster_url(key):
        return u'{0}{1}.jpeg'.format(app.config.get('VIDEO_CDN_PREFIX'), key)

    @staticmethod
    def get_product_video_code(key, controls=True, product_title=None):
        if cache.search_token('video_processing:%s' % key, cache.TokenType.VARIABLE, destroy_token=False):
            # The video is still being processed
            return u'''
                <video class="video-processing"></video>
                <div class="video-processing-caption">Video is being processed</div>
            '''

        return u'''
            <video {2} controlsList="nodownload" poster="{0}{1}.jpeg">
              <source src="{0}670/webm/{1}.webm" type="video/webm"/>
              <source src="{0}670/mp4/{1}.mp4" type="video/mp4"/>
               Your browser does not support HTML5 video tags
            </video>
        '''.format(app.config.get('VIDEO_CDN_PREFIX'), key, 'controls' if controls else '')

    @staticmethod
    def get_product_video_url(key, format, product_title=None):
        return u'{0}670/{1}/{2}.{1}'.format(app.config.get('VIDEO_CDN_PREFIX'), format, key)

    def __init__(self):
        self.client = boto3.client(
            's3',
            aws_access_key_id=app.config.get('AWS_ACCESS_KEY'),
            aws_secret_access_key=app.config.get('AWS_SECRET_KEY'),
            aws_session_token=app.config.get('AWS_SESSION_TOKEN'),
            config=Config(signature_version='s3v4')
        )

        cloudinary.config( 
            cloud_name = app.config.get('CLOUDINARY_CLOUD_NAME'), 
            api_key = app.config.get('CLOUDINARY_API_KEY'), 
            api_secret = app.config.get('CLOUDINARY_API_SECRET')
        )

    def upload_product_photo(self, file, product_id, product_title, filename=None):
        configuration = app.config.get('AWS_IMAGES_CONFIGURATION')

        filename = file.filename if hasattr(file, 'filename') else filename

        _, photo_extension = os.path.splitext(filename)
        photo_random_filename = u'{0}-{1}{2}'.format(
            product_title[:64],
            ''.join(random.choice(string.digits + string.ascii_letters) for _ in range(10)),
            photo_extension
        )

        bucket, prefix = configuration['bucket'], configuration['prefix']
        key = u'{0}/{1}/{2}'.format(prefix, product_id, photo_random_filename)

        self.client.upload_fileobj(file, bucket, key, ExtraArgs=dict(ACL='public-read'))

        cloudinary_key = None
        if not app.config.get('USE_JOBDONE_IMAGE_SERVICE'):
            result = cloudinary.uploader.upload(Storage.get_image_aws_url(key))
            cloudinary_key = result.get('public_id')
        else:
            try:
                for preset in (ImagePresets.SERVICE_PRIMARY, ImagePresets.SERVICE_THUMB_CAROUSEL, ImagePresets.SERVICE_THUMB_PRIMARY, ImagePresets.SERVICE_THUMB_SECONDARY):
                    requests.head(Storage.get_product_photo_url(dict(aws_key=key), transform=preset))
            except Exception as e:
                print e

        return key, cloudinary_key

    def upload_image(self, type, file, identifier, filename=None):
        configuration = app.config.get('AWS_PROFILE_IMAGES_CONFIGURATION')

        filename = file.filename if hasattr(file, 'filename') else filename

        _, photo_extension = os.path.splitext(filename)
        photo_random_filename = '{0}-{1}{2}'.format(
            identifier,
            ''.join(random.choice(string.digits + string.ascii_letters) for _ in range(10)),
            photo_extension
        )

        bucket, prefix = configuration['bucket'], configuration['prefix']
        key = u'{0}/{1}/{2}'.format(prefix, type, photo_random_filename)

        self.client.upload_fileobj(file, bucket, key, ExtraArgs=dict(ACL='public-read'))

        cloudinary_key = None
        if not app.config.get('USE_JOBDONE_IMAGE_SERVICE'):
            result = cloudinary.uploader.upload(Storage.get_image_aws_url(key))
            cloudinary_key = result.get('public_id')
        else:
            if type == Storage.ImageType.USER_IMAGE:
                try:
                    for preset in (ImagePresets.USER_ICON, ImagePresets.USER_PRIMARY):
                        requests.head(Storage.get_product_photo_url(dict(aws_key=key), transform=preset))
                except Exception as e:
                    print e

        return key, cloudinary_key

    def upload_verification_photo(self, file, photo_id, filename=None):
        return self.upload_image(Storage.ImageType.USER_VERIFICATION_IMAGE, file, photo_id, filename=filename)

    def upload_profile_photo(self, file, user_id, username, filename=None):
        return self.upload_image(Storage.ImageType.USER_IMAGE, file, username, filename=filename)

    def upload_profile_cover(self, file, user_id, username, filename=None):
        return self.upload_image(Storage.ImageType.USER_COVER_IMAGE, file, username, filename=filename)

    def upload_attachment(self, file, filename=None):
        configuration = app.config.get('AWS_ATTACHMENTS_CONFIGURATION')

        filename = file.filename if hasattr(file, 'filename') else filename

        attachment_id = uuid.uuid4()
        bucket, prefix = configuration['bucket'], configuration['prefix']
        key = u'{0}/{1}/{2}'.format(prefix, attachment_id, filename)

        self.client.upload_fileobj(file, bucket, key, ExtraArgs=dict(ACL='public-read'))

        return attachment_id, filename

    def upload_profile_photo_from_url(self, url, user_id, username):
        fp = urllib2.urlopen(url).fp
        filename = urlparse(url).path.rsplit('/', 1)[-1]

        return self.upload_profile_photo(fp, user_id, username, filename=filename)

    def upload_product_video(self, file, callback_url, mimetype=None, filename=None):
        url = 'http://video.jobdone.net/upload'
        data = (
            ('callback', callback_url),
            ('output', 'w_670,f_mp4',),
            ('output', 'w_670,f_webm',),
            # ('output', 'w_255,h_148,c_pad,g_south_west,f_mp4',),
            # ('output', 'w_255,h_148,c_pad,g_south_west,f_webm',)
        )

        file_data = (
            'video%s' % os.path.splitext(file.filename if hasattr(file, 'filename') else filename)[1],
            file,
            file.mimetype if hasattr(file, 'mimetype') else mimetype
        )

        try:
            resp = requests.post(url, data=data, files=dict(file=file_data))
            resp.raise_for_status()

            resp_data = resp.json()
        except Exception, e:
            print "Error uploading video"
            print e  # TODO: capture by Raven
            return None

        if not resp_data.get('OK') or not resp_data.get('key'):
            return None

        key = os.path.splitext(resp_data['key'])[0]  # TODO: fix on the converter side to return key without extension

        # We put a token with video public ID
        # While token exists, we consider that video is still processing and show that for users
        # Token is deleted once video is finished processing and we receive POST request on the webhook URL
        # If for some reason, webhook URL is not called, token will exprre in time defined in VIDEO_PROCESSING_EXPIRE constant
        cache.add_token('video_processing:%s' % key, cache.TokenType.VARIABLE, 1, expire=VIDEO_PROCESSING_EXPIRE)

        return key

    def upload_product_video_callback(self, key):
        # Search token by default will cause its deletion
        cache.search_token('video_processing:%s' % key, cache.TokenType.VARIABLE)

    def delete_product_video(self, cloudinary_key):
        pass  # TODO: not yet implemented on converter side

    def delete_product_photo(self, aws_key, cloudinary_key):
        configuration = app.config.get('AWS_IMAGES_CONFIGURATION')

        try:
            self.client.delete_object(Bucket=configuration['bucket'], Key=aws_key)
            cloudinary.uploader.destroy(cloudinary_key)
        except:
            # We don't care, it's deletion
            pass

    def delete_profile_cover(self, aws_key, cloudinary_key):
        configuration = app.config.get('AWS_PROFILE_IMAGES_CONFIGURATION')

        try:
            self.client.delete_object(Bucket=configuration['bucket'], Key=aws_key)
            cloudinary.uploader.destroy(cloudinary_key)
        except:
            # We don't care, it's deletion
            pass

    def delete_profile_photo(self, aws_key, cloudinary_key):
        configuration = app.config.get('AWS_PROFILE_IMAGES_CONFIGURATION')

        try:
            self.client.delete_object(Bucket=configuration['bucket'], Key=aws_key)
            cloudinary.uploader.destroy(cloudinary_key)
        except:
            # We don't care, it's deletion
            pass

    def delete_attachment(self, attachment_id, filename):
        configuration = app.config.get('AWS_ATTACHMENTS_CONFIGURATION')

        key = u'{0}/{1}/{2}'.format(configuration['prefix'], attachment_id, filename)

        try:
            self.client.delete_object(Bucket=configuration['bucket'], Key=key)
        except:
            # We don't care, it's deletion
            pass
