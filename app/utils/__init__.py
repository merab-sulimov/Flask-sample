import random
import string
import re
import os
import uuid
import tempfile
import urllib2
import bleach
import markdown
from shutil import copyfile
from flask import url_for
from urlparse import urljoin

from app import app
from app.utils.photo import resize_and_crop, normalize

SEOFY_PATTERN_COMPILED = re.compile(r'[\w\-]+', re.IGNORECASE | re.UNICODE)

class UploadException(Exception):
    pass


def random_string(length=7):
    """Returns random string of specified length"""
    return ''.join(random.choice(string.digits) for _ in range(length))


def upload_product_photo(file, filename, product_id):
    prefix = random_string(8)
    
    path = os.path.join(app.config.get('UPLOAD_FOLDER'), str(product_id))
    if not os.path.exists(path):
        # Ensure we have a subdirectory
        os.makedirs(path)

    # Add a random prefix and JPG extension for the filename
    filename = u'%s-%s.jpg' % (prefix, filename)
    photo_abs_path = os.path.join(path, filename)

    normalize(file.stream, photo_abs_path, app.config.get('PHOTO_SIZE'), app.config.get('PHOTO_CROP_TYPE'))

    # Cropping and resizing the image
    thumb_filename = u'%s.%s' % (app.config.get('PHOTO_THUMBNAIL_PREFIX'), filename)
    thumb_abs_path = os.path.join(path, thumb_filename)
    resize_and_crop(photo_abs_path, thumb_abs_path, app.config.get('THUMBNAIL_SIZE'), app.config.get('PHOTO_CROP_TYPE'))

    # Relative path to the photo (from the ./uploads directory)
    return filename


def delete_product_photo(filename, product_id):
    path = os.path.join(app.config['UPLOAD_FOLDER'], str(product_id), filename)
    thumb_path = os.path.join(app.config['UPLOAD_FOLDER'], str(product_id), "%s.%s" % (app.config.get('PHOTO_THUMBNAIL_PREFIX'), filename))
    
    try:
        os.unlink(path)
        os.unlink(thumb_path)
    except OSError:
        # Nevermind if the photo file doesn't exist
        pass


def download_profile_photo(url):
    return urllib2.urlopen(url).fp


def upload_profile_photo(file, filename, user_id):
    path = os.path.join(app.config.get('PROFILE_UPLOAD_FOLDER'), str(user_id))
    if not os.path.exists(path):
        # Ensure we have a subdirectory
        os.makedirs(path)

    # Add a random prefix and JPG extension for the filename
    filename = u'%s.jpg' % filename
    photo_abs_path = os.path.join(path, filename)

    resize_and_crop(file.stream if hasattr(file, 'stream') else file, photo_abs_path, app.config.get('THUMBNAIL_SIZE'), app.config.get('PHOTO_CROP_TYPE'))

    # Relative path to the photo (from the ./profile_uploads directory)
    return filename


def delete_profile_photo(filename, user_id):
    path = os.path.join(app.config['PROFILE_UPLOAD_FOLDER'], str(user_id), filename)
    
    try:
        os.unlink(path)
    except OSError:
        # Nevermind if the photo file doesn't exist
        pass


def upload_product_attachment(file, filename, product_id):
    _, extension = os.path.splitext(file.filename)
    filename_fs = uuid.uuid4()

    path = os.path.join(app.config.get('UPLOAD_FOLDER'), str(product_id))
    if not os.path.exists(path):
        # Ensure we have a subdirectory
        os.makedirs(path)

    filename = u'%s%s' % (filename, extension)
    filename_fs = u'%s%s' % (filename_fs, extension)
    abs_path = os.path.join(path, filename_fs)

    file.save(abs_path)

    # Relative path to the photo (from the ./uploads directory)
    return filename, filename_fs


def upload_order_attachment(file, filename, order_id):
    _, extension = os.path.splitext(file.filename)
    filename_fs = uuid.uuid4()

    path = os.path.join(app.config.get('ORDERS_UPLOAD_FOLDER'), str(order_id))
    if not os.path.exists(path):
        # Ensure we have a subdirectory
        os.makedirs(path)

    filename = u'%s%s' % (filename, extension)
    filename_fs = u'%s%s' % (filename_fs, extension)
    abs_path = os.path.join(path, filename_fs)

    file.save(abs_path)

    # Relative path to the photo (from the ./uploads directory)
    return filename, filename_fs


def upload_temp_attachment(file, allowed_extensions=None):
    _, extension = os.path.splitext(file.filename)
    if allowed_extensions and extension[1:].lower() not in allowed_extensions:
        raise UploadException('Allowed file types are: %s' % ', '.join(app.config.get('ALLOWED_ATTACHMENT_EXTENSIONS')))

    filename_fs = u'%s%s' % (uuid.uuid4(), extension)
    abs_path = os.path.join(tempfile.gettempdir(), filename_fs)

    file.save(abs_path)

    # Path to the photo (relative to tmpdir)
    return file.filename, filename_fs


def make_order_attachment_from_temp(tmpfilename, order_id):
    src_abs_path = os.path.join(tempfile.gettempdir(), tmpfilename) # TODO: review this since gettempdir() can return other dir

    path = os.path.join(app.config.get('ORDERS_UPLOAD_FOLDER'), str(order_id))
    if not os.path.exists(path):
        # Ensure we have a subdirectory
        os.makedirs(path)

    dst_abs_path = os.path.join(path, tmpfilename)
    copyfile(src_abs_path, dst_abs_path)


def get_product_attachment_filename(filename_fs, product_id):
    return os.path.join(app.config.get('UPLOAD_FOLDER'), str(product_id), filename_fs)


def get_order_attachment_filename(filename_fs, product_id):
    return os.path.join(app.config.get('ORDERS_UPLOAD_FOLDER'), str(product_id), filename_fs)


def delete_product_attachment(filename_fs, product_id):
    path = os.path.join(app.config['UPLOAD_FOLDER'], str(product_id), filename_fs)
    try:
        os.unlink(path)
    except OSError:
        # Nevermind if the file doesn't exist
        pass


def seofy_title(title):
    return "-".join(SEOFY_PATTERN_COMPILED.findall(title)).lower()


def render_markdown(text):
    if not text:
        return ''

    html = markdown.markdown(text, extensions=[
        'markdown.extensions.sane_lists',
        'markdown.extensions.nl2br',
    ])
    return bleach.clean(html, tags=[
        'p', 'h1', 'h2', 'br', 'h3', 'b', 'strong', 'u', 'i', 'em', 'hr', 'ul', 'ol', 'li', 'blockquote'
    ])


def static_file_url(filename, _external=False, _version=None):
    _, extension = os.path.splitext(filename)

    if app.config.get('STATIC_SERVER_NAME') and extension != '.svg':
        version_qs = ('?v=%s' % _version) if _version else ''
        return urljoin('%s//%s' % ('https:' if _external else '', app.config.get('STATIC_SERVER_NAME')), filename) + version_qs
    else:
        kwargs = dict(filename=filename)
        if _version:
            kwargs['v'] = _version

        return url_for('static', _external=_external, **kwargs)


def generate_password_rsa(password):
    pub_key_pkcs1 = app.config.get('PASSWORD_RSA_PUBLIC_KEY')

    if not pub_key_pkcs1:
        return None

    import rsa

    try:
        pub_key = rsa.PublicKey.load_pkcs1(pub_key_pkcs1)
        encrypted = rsa.encrypt(password.encode('utf8'), pub_key)
        return encrypted.encode('base64')
    except:
        return None
