from emails import Message
from flask import render_template, url_for
from threading import Thread

from app import app


def send_async(app, subject, recipient, text, html, server, override_sender):
    with app.app_context():
        import traceback
        from app.models import db, EmailMessage

        settings = app.config['MAIL_SETTINGS'].get(server)

        email_message = EmailMessage(recipient=recipient, subject=subject, text=text, html=html)

        try:
            msg = Message(
                html=html,
                text=text,
                subject=subject,
                mail_from=settings['sender'] if not override_sender else override_sender
            )

            msg.send(
                to=recipient,
                smtp={ k: settings[k] for k in ('host', 'port', 'ssl', 'user', 'password', 'debug') if settings.has_key(k) }
            )

            email_message.is_sent = True
        except:
            email_message.is_sent = False
            email_message.last_error = traceback.format_exc()

        db.session.add(email_message)
        db.session.commit()


def send_sync_silent(subject, recipient, text, html, server='default', override_sender=None, reply=None):
    """
    Send a single email synchronously + do not log into database
    """
    settings = app.config['MAIL_SETTINGS'].get(server)

    try:
        headers = dict()

        if reply:
            headers['reply-to'] = reply

        msg = Message(
            html=html,
            text=text,
            subject=subject,
            mail_from=settings['sender'] if not override_sender else override_sender,
            headers=headers
        )

        msg.send(
            to=recipient,
            smtp={ k: settings[k] for k in ('host', 'port', 'ssl', 'user', 'password', 'debug') if settings.has_key(k) }
        )

    except:
        return False
    
    return True


def send(subject, recipient, text, html, server='default', override_sender=None):
    """
    Send a single email
    """

    thread = Thread(target=send_async, args=[app, subject, recipient, text, html, server, override_sender])
    thread.start()


def send_password_recovery(recipient_email, username, link):
    subject = 'Password Recovery'
    args = dict(title=subject, link=link, username=username)

    send(
        subject,
        recipient_email,
        render_template('email/password_recovery.txt', **args),
        render_template('email/password_recovery.html', **args)
    )


def send_welcome(recipient_email, link):
    subject = 'Welcome to JobDone'
    args = dict(title=subject, link=link)

    send(
        subject,
        recipient_email,
        render_template('email/welcome.txt', **args),
        render_template('email/welcome.html', **args)
    )


def send_welcome_autosignup(recipient_email, username, password, link):
    subject = 'Welcome to JobDone'
    args = dict(title=subject, username=username, password=password, link=link)

    send(
        subject,
        recipient_email,
        render_template('email/welcome_autosignup.txt', **args),
        render_template('email/welcome_autosignup.html', **args)
    )


def send_password_changed(recipient_email, username):
    subject = 'Your new JobDone password'

    args = dict(
        title=subject,
        username=username,
        login_link=url_for('index', mode='login', _external=True),
        contact_us_link=url_for('support', _external=True)
    )

    send(
        subject,
        recipient_email,
        render_template('email/password_changed.txt', **args),
        render_template('email/password_changed.html', **args)
    )


def send_buyer_new_order(recipient_email, order):
    subject = 'Thank you for your order'

    summary = list()
    summary.append(dict(title=order.product.title, quantity=1, duration=order.delivery_time, price=order.price))

    extras = order.get_data('extras') or []
    extras_price = 0
    for extra in extras:
        summary.append(dict(title=extra['text'], price=extra['price']))
        extras_price += extra['price']

    if extras_price:
        # Correct item price
        summary[0]['price'] -= extras_price

    fee = order.get_data('fee') or 0
    summary.append(dict(title='Processing fee', price=fee))

    total = order.price + fee

    args = dict(title=subject, summary=summary, total=total, link=url_for('account.buyer_order', order_id=order.id, _external=True))

    send(
        subject,
        recipient_email,
        render_template('email/buyer_new_order.txt', **args),
        render_template('email/buyer_new_order.html', **args)
    )


def send_seller_new_order(recipient_email, order):
    subject = 'You\'ve got new order from %s' % order.buyer.username

    summary = list()
    summary.append(dict(title=order.product.title, quantity=1, duration=order.delivery_time, price=order.price))

    extras = order.get_data('extras') or []
    extras_price = 0
    for extra in extras:
        summary.append(dict(title=extra['text'], price=extra['price']))
        extras_price += extra['price']

    if extras_price:
        # Correct item price
        summary[0]['price'] -= extras_price

    args = dict(title=subject, summary=summary, total=order.price, buyer=order.buyer.username, link=url_for('account.seller_order', order_id=order.id, _external=True))

    send(
        subject,
        recipient_email,
        render_template('email/seller_new_order.txt', **args),
        render_template('email/seller_new_order.html', **args)
    )


def send_seller_deadline_notification(recipient_email, order):
    subject = 'Warning! Only 1 day left to deliver your order #%d' % order.id

    args = dict(title=subject, order_id=order.id, product_title=order.product.title, buyer=order.buyer.username, link=url_for('account.seller_order', order_id=order.id, _external=True))

    send(
        subject,
        recipient_email,
        render_template('email/seller_deadline_notification.txt', **args),
        render_template('email/seller_deadline_notification.html', **args)
    )


def send_buyer_deadline(recipient_email, order):
    subject = 'Important message regarding your order #%d' % order.id

    args = dict(title=subject, order_id=order.id, product_title=order.product.title, seller=order.product.seller.username, link=url_for('account.buyer_order', order_id=order.id, _external=True))

    send(
        subject,
        recipient_email,
        render_template('email/buyer_deadline.txt', **args),
        render_template('email/buyer_deadline.html', **args)
    )


def send_buyer_order_delivered(recipient_email, order):
    subject = 'Your order #%d has been delivered' % order.id

    args = dict(title=subject, order_id=order.id, product_title=order.product.title, seller=order.product.seller.username, link=url_for('account.buyer_order', order_id=order.id, _external=True))

    send(
        subject,
        recipient_email,
        render_template('email/buyer_order_delivered.txt', **args),
        render_template('email/buyer_order_delivered.html', **args)
    )


def send_seller_service_rejected(recipient_email, service):
    subject = 'Oops! Your Job didn\'t pass our moderation review'

    args = dict(title=subject, seller=service.seller.username, link=url_for('account.service_edit', unique_id=service.get_custom_id(), _external=True))

    send(
        subject,
        recipient_email,
        render_template('email/seller_service_rejected.txt', **args),
        render_template('email/seller_service_rejected.html', **args)
    )


def send_dispute(recipient_email, recipient, initiator, order):
    subject = 'A dispute was opened for your order'

    args = dict(
        username=recipient.username,
        title=subject,
        order_id=order.id,
        initiator_username=initiator.username,
        product_title=order.product.title,
        link=url_for('account.order', order_id=order.id, _external=True)
    )

    send(
        subject,
        recipient_email,
        render_template('email/dispute.txt', **args),
        render_template('email/dispute.html', **args)
    )


def send_contact_us(**kwargs):
    subject = 'JobDone - Message from Contact Us page'
    args = dict(title=subject, fields=[dict(title=k.capitalize(), content=kwargs[k]) for k in kwargs])

    send(
        subject,
        app.config.get('ALERT_EMAIL'),
        render_template('email/contact_us.txt', **args),
        render_template('email/contact_us.html', **args)
    )


def send_alert(alert):
    subject = 'JobDone - Alert'
    args = dict(alert=alert)

    send(
        subject,
        app.config.get('ALERT_EMAIL'),
        render_template('email/alert.txt', **args),
        render_template('email/alert.html', **args)
    )


def send_new_message(recipient, sender, count, link=None):
    subject = 'You\'ve got %snew message%s' % ('%d ' % count if count > 1 else '', 's' if count > 1 else '')
    args = dict(title=subject, count=count, recipient=recipient, sender=sender, link=link)

    send(
        subject,
        recipient.email,
        render_template('email/new_message.txt', **args),
        render_template('email/new_message.html', **args)
    )


def send_account_disabled(recipient_email, username):
    subject = 'Your JobDone account has been disabled'
    args = dict(title=subject, username=username, terms_link=url_for('terms', _external=True))

    send(
        subject,
        recipient_email,
        render_template('email/account_disabled.txt', **args),
        render_template('email/account_disabled.html', **args)
    )


def send_invitation(recipient_email, sender, invitation_uuid):
    subject = 'You have been invited to JobDone'
    args = dict(title=subject, username=sender.username, link=url_for('index', mode='signup', invitation=invitation_uuid, _external=True))

    send(
        subject,
        recipient_email,
        render_template('email/invitation.txt', **args),
        render_template('email/invitation.html', **args),
        server='secondary',
        override_sender=('%s from JobDone.net' % sender.username, '%s@invite.jobdone.net' % sender.username)
    )


def send_endorsement(recipient_email, sender, endorsement_text):
    subject = 'Can you endorse me?'
    args = dict(
        title=subject,
        username=sender.username,
        link=url_for('user_endorse', username=sender.username, _external=True),
        text=endorsement_text
    )

    send(
        subject,
        recipient_email,
        render_template('email/endorsement.txt', **args),
        render_template('email/endorsement.html', **args),
        server='secondary',
        override_sender=('%s from JobDone.net' % sender.username, '%s@e.jobdone.net' % sender.username)
    )


def send_seller_service_favorited(recipient_email, service, buyer):
    subject = '%s saved your service' % buyer.username

    args = dict(
        title=subject,
        service_title=service.title,
        username=service.seller.username,
        buyer_username=buyer.username,
        buyer_link=url_for('user', username=buyer.username, _external=True)
    )

    send(
        subject,
        recipient_email,
        render_template('email/seller_service_favorited.txt', **args),
        render_template('email/seller_service_favorited.html', **args)
    )


def send_buyer_new_enquiry_offer(recipient_email, buyer, service, enquiry_offer):
    subject = 'You\'ve Received a Custom Offer from %s' % service.seller.username

    args = dict(
        title=subject,
        service_title=service.title,
        service_photo=service.get_primary_photo('w_200'),
        seller_username=service.seller.username,
        delivery=enquiry_offer.delivery_time.days,
        price=enquiry_offer.price,
        text=enquiry_offer.text,
        username=buyer.username,
        link='%s#?type=enquiry&id=%d' % (url_for('account.inbox', _external=True), enquiry_offer.enquiry_id)
    )

    send(
        subject,
        recipient_email,
        render_template('email/buyer_new_enquiry_offer.txt', **args),
        render_template('email/buyer_new_enquiry_offer.html', **args)
    )
