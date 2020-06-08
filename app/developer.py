from zipfile import ZipFile
from flask import request, json, g, abort
from distutils.dir_util import copy_tree
from functools import wraps
from tempfile import mkdtemp
from os import path

from app import app


def create_template_directory():
    return mkdtemp()


def copy_templates(src, dest):
    copy_tree(src, dest)


def developer_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not g.developer:
            abort(403)

        return func(*args, **kwargs)
    return decorated_view


@app.route('/api/developer/templates', methods=['POST'])
@developer_required
def api_developer_templates():
    MAX_TEMPLATE_FILE_SIZE = 200 * 1024  # Allow max. 200 KB

    file = request.files['file']

    zip_ref = ZipFile(file, 'r')
    for zip_info in zip_ref.infolist():
        if zip_info.file_size > MAX_TEMPLATE_FILE_SIZE:
            abort(500)

    zip_ref.extractall(app.template_folder)
    zip_ref.close()

    print "Extracted templates into %s" % app.template_folder

    return json.jsonify(dict())
