from jinja2 import evalcontextfilter, Markup, escape
from datetime import datetime, timedelta
from flask import url_for, jsonify
from utils import static_file_url

from app import app, app_versions


class SearchPagination:
    def __init__(self, items, page, total, per_page=20):
        self.items = items
        self.page = page
        self.total = total
        self.per_page = per_page

        self.next_page = self.page + 1
        self.prev_page = self.page - 1

    @property
    def has_next(self):
        return len(self.items) + (self.page - 1) * self.per_page < self.total

    @property
    def has_prev(self):
        return self.page > 1


@app.template_filter()
@evalcontextfilter
def nl2br(eval_ctx, value):
    """Newline-to-br filter for Jinja"""
    result = escape(value).replace('\n', Markup('<br />\n'))
    if eval_ctx.autoescape:
        result = Markup(result)
    return result


@app.template_filter()
def timedelta_from_now(value, use_date=False):
    """Pretty-print timedelta in the past"""
    if type(value) != datetime:
        return ""

    delta = datetime.utcnow() - value
    if delta.days > 0:
        if not use_date:
            return "%d day%s ago" % (delta.days, 's' if delta.days > 1 else '')
        else:
            return value.strftime()

    hours, minutes = delta.seconds // 3600, (delta.seconds // 60) % 60

    if hours > 0:
        return "%d hour%s ago" % (hours, 's' if hours > 1 else '')

    if minutes > 0:
        return "%d minute%s ago" % (minutes, 's' if minutes > 1 else '')

    return "now"


@app.template_filter()
def timedelta_pretty_print(delta, now=False):
    """Pretty-print timedelta value"""
    if type(delta) != timedelta:
        return ""

    if delta.total_seconds() <= 0 and now:
        return "now"

    if delta.days > 0:
        return "%d day%s" % (delta.days, 's' if delta.days > 1 else '')

    hours, minutes = delta.seconds // 3600, (delta.seconds // 60) % 60

    if hours > 0:
        return "%d hour%s" % (hours, 's' if hours > 1 else '')

    if minutes > 0:
        return "%d minute%s" % (minutes, 's' if minutes > 1 else '')

    return "N/A"


@app.template_filter()
def format_price(value):
    if not value:
        value = 0

    return "{0:.2f}".format(long(value) / 100.0)


@app.template_filter()
def format_percents(value):
    return str(int(value * 100))


@app.context_processor
def static_file():
    def static_file(filename, _external=False, include_version=False):
        version = app_versions['frontend'] if 'frontend' in app_versions else None
        result = static_file_url(filename, _external=_external, _version=version)
        return result
    return dict(static_file=static_file)


class APIError(Exception):
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        data = dict(self.payload or ())
        data['message'] = self.message
        return dict(error=data)


@app.errorhandler(APIError)
def handle_api_error(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response
