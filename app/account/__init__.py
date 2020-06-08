from flask import Blueprint


account = Blueprint('account', __name__)


import views
import views.buyer
import views.service
import views.seller
import views.verification_center

from . import api