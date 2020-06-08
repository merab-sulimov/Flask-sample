from flask import Blueprint, session
from flask_login import user_logged_in


auth = Blueprint('auth', __name__)

from . import api
from . import views

def user_logged_in_handler(app, user):
    app.session_interface.ensure_single_session(user.get_id(), session.sid)

user_logged_in.connect(user_logged_in_handler)