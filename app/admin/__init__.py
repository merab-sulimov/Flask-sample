from flask import Blueprint

admin = Blueprint('admin', __name__)

from . import api
from . import views
from . import maintenance