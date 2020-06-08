from functools import wraps

from flask import abort, request, url_for, redirect
from flask_login import current_user, login_required 

from models import Variable
from app import app


def admin_required(func):
    @login_required
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user or not current_user.is_admin:
            abort(403)
        return func(*args, **kwargs)
    return decorated_view


def seller_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user:
            abort(403)

        if not current_user.seller_fee_paid:
            if request.is_xhr:
                abort(403)
            else:
                return redirect(url_for('become_seller'))

        return func(*args, **kwargs)
    return decorated_view


def xhr_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not request.is_xhr:
            abort(403)
        return func(*args, **kwargs)
    return decorated_view
