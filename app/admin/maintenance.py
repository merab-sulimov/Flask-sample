from flask import request, url_for, g, abort, json, render_template
from datetime import datetime, timedelta
from sqlalchemy.sql import func

from . import admin
from app.decorators import admin_required, xhr_required
from app.models import db, isoformat, EmailMessage


@admin.route('/admin/maintenance')
@admin_required
def maintenance():


    application_data = dict()

    return render_template('admin/maintenance.html', application_data=application_data)


@admin.route('/admin/maintenance/api/email_today')
@admin_required
@xhr_required
def api_email_today():
    messages = EmailMessage.query.filter(
        func.DATE(EmailMessage.created_on) == func.CURDATE()
    ).order_by(EmailMessage.created_on.desc())

    messages_prepared = list()

    for message in messages:
        message_prepared = dict()
        message_prepared['subject'] = message.subject
        message_prepared['created_on'] = isoformat(message.created_on)
        message_prepared['recipient'] = message.recipient
        message_prepared['is_sent'] = message.is_sent
        messages_prepared.append(message_prepared)

    return json.jsonify(dict(data=messages_prepared))


@admin.route('/admin/maintenance/api/email_failed')
@admin_required
@xhr_required
def api_email_failed():
    messages = EmailMessage.query.filter(
        EmailMessage.is_sent != True,
        EmailMessage.created_on < datetime.utcnow() - timedelta(seconds=3600)
    ).order_by(EmailMessage.created_on.desc())

    messages_prepared = list()

    for message in messages:
        message_prepared = dict()
        message_prepared['subject'] = message.subject
        message_prepared['created_on'] = isoformat(message.created_on)
        message_prepared['recipient'] = message.recipient
        messages_prepared.append(message_prepared)

    return json.jsonify(dict(data=messages_prepared))
