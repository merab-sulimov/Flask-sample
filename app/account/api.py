from datetime import datetime, timedelta
from flask import request, g, abort, json, Response, make_response, redirect, url_for
from flask_login import login_required

from app import app, messaging, cache, email
from app.helpers import timedelta_pretty_print, APIError
from app.decorators import xhr_required
from app.models import db, Order, Feedback, Product, User, FavoriteProduct, Enquiry, \
    UserInvitation, UserSkills, UserLanguages, UserFollowers, Category, CategoryFollowers, isoformat
from sqlalchemy.exc import IntegrityError
from app.utils import UploadException
from app.utils.storage import Storage, ImagePresets
from app.utils.tz import get_local_datetime
from .forms import InviteAPIForm, EndorseAPIForm, SkillAPIForm, LanguageAPIForm
from . import account


@account.route('/api/account/feedback/<int:feedback_id>/reply', methods=['POST'])
@login_required
@xhr_required
def api_feedback_reply(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)

    if feedback.type == Feedback.ON_SELLER and g.user.id != feedback.order.product.seller_id:
        # User can't reply on this feedback
        abort(403)

    if feedback.type == Feedback.ON_BUYER and g.user.id != feedback.order.buyer_id:
        # User can't reply on this feedback
        abort(403)

    data = request.get_json()
    reply = data.get('reply')

    if reply:
        feedback.reply = reply
        db.session.add(feedback)
        db.session.commit()

    return json.jsonify(dict())


@account.route('/api/account/service/<custom_id>/favorite/toggle', methods=['POST'])
@login_required
@xhr_required
def api_service_favorite_toggle(custom_id):
    product = Product.get_by_custom_id(custom_id)

    # Check if the product is found, is approved, isn't deleted and seller is active
    if not product or not product.published_on or not product.is_approved or product.is_deleted or product.seller.is_deleted or product.seller.is_disabled:
        abort(404)

    FavoriteProduct.toggle(g.user, product)

    return json.jsonify(dict())


@account.route('/api/account/messaging/auth', methods=['POST'])
@login_required
@xhr_required
def api_messaging_auth():
    data = request.get_json()
    messaging.auth(g.user, data)

    return json.jsonify(dict())


@account.route('/api/account/messaging/enquiry/record_time', methods=['POST'])
@login_required
@xhr_required
def api_messaging_record_time():
    incoming = request.get_json()
    incoming_id = incoming.get('id')

    if not incoming_id:
        abort(404)

    enquiry = Enquiry.query.get_or_404(incoming_id)

    if enquiry.response_on:
        # Time has been recorded already
        return json.jsonify(dict())

    if enquiry.product_id:
        product = Product.query.get_or_404(enquiry.product_id)
        seller_id = product.seller_id
    else:
        seller_id = enquiry.seller_id

    if g.user.id != seller_id:
        # Only seller is allowed to call this method
        return json.jsonify(dict())

    enquiry.response_on = datetime.utcnow()
    db.session.add(enquiry)
    db.session.commit()

    return json.jsonify(dict())


@account.route('/api/account/messaging/enquiry/search', methods=['POST'])
@login_required
@xhr_required
def api_messaging_enquiry_search():
    incoming = request.get_json()
    incoming_seller = incoming.get('seller')

    if not incoming_seller:
        abort(404)

    seller = User.query.filter_by(username=incoming_seller).first()

    if not seller or not seller.seller_fee_paid or seller.is_disabled or seller.is_deleted:
        abort(404)

    enquiry = Enquiry.search(g.user, seller=seller)

    if enquiry:
        return json.jsonify(dict(id=enquiry.id))

    # Existing enquiry not found, send just seller metadata

    meta = dict(seller=dict(id=seller.id, username=seller.username))
    return json.jsonify(dict(meta=meta))


@account.route('/api/account/messaging/upload', methods=['POST'])
@login_required
def api_messaging_upload():
    storage = Storage()
    try:
        attachment_id, filename = storage.upload_attachment(request.files['file'])
    except UploadException, e:
        return make_response(json.jsonify(dict(error=e.message)), 400)

    return json.jsonify(dict(filename=filename, attachmentId=attachment_id))


@account.route('/api/account/messaging/upload/delete', methods=['POST'])
@login_required
@xhr_required
def api_messaging_upload_delete():
    data = request.get_json()

    storage = Storage()

    try:
        storage.delete_attachment(data['attachmentId'], data['filename'])
    except:
        pass

    return json.jsonify(dict())


@account.route('/api/account/messaging/download/<attachment_id>/<filename>', methods=['GET'])
@login_required
def api_messaging_download(attachment_id, filename):
    url = Storage.get_attachment_aws_url(attachment_id, filename)
    return redirect(url)


@app.route('/api/user/<username>/<any(follow,unfollow):action>')
@xhr_required
@login_required
def api_user_relations(username, action):
    user = User.get_active_by_username(username)
    if not user:
        # user not found
        abort(404)

    if g.user.id == user.id:
        # can't follow self
        abort(404)

    if not user.seller_fee_paid:
        # it's not seller
        abort(404)

    relation = UserFollowers.query.filter_by(user_id=user.id, follower_id=g.user.id).scalar()

    if action == 'follow' and not relation:
        relation = UserFollowers(
            user_id=user.id,
            follower_id=g.user.id,
        )
        db.session.add(relation)
    if action == 'unfollow':
        db.session.delete(relation)
    db.session.commit()

    return json.jsonify({})


@app.route('/api/subcategory/<int:category_id>/<any(follow,unfollow):action>')
@xhr_required
@login_required
def api_user_category_relations(category_id, action):
    category = Category.query.get_or_404(category_id)

    if not category.parent_id:
        # only subcategories following allowed
        abort(404)

    relation = CategoryFollowers.query.filter_by(category_id=category.id,
                                                  follower_id=g.user.id).scalar()

    if action == 'follow' and not relation:
        relation = CategoryFollowers(
            category_id=category.id,
            follower_id=g.user.id,
        )
        db.session.add(relation)
    if action == 'unfollow':
        db.session.delete(relation)
    db.session.commit()

    return json.jsonify({})


@app.route('/api/user/<int:user_id>')
@xhr_required
@login_required
def api_user(user_id):
    user = User.query.get_or_404(user_id)

    incoming_room = request.args.get('room')
    response_time = None
    seller = False

    if incoming_room:
        try:
            room_type, entity_id = incoming_room.split(':')
            if room_type == 'enquiry':
                enquiry = Enquiry.query.get(entity_id)
                if enquiry:
                    seller = (enquiry.get_seller_id() == user_id)

                    if enquiry.user_id == g.user.id:
                        response_time_seconds = user.get_average_response_time()
                        response_time = timedelta_pretty_print(timedelta(seconds=int(response_time_seconds))) if response_time_seconds else None
        except:
            pass

    user_prepared = user.to_json()
    user_prepared['_url'] = url_for('user', username=user.username)
    user_prepared['_photo_url'] = user.get_photo_url(ImagePresets.USER_PRIMARY)
    user_prepared['is_online'] = user.is_online
    user_prepared['last_logged_on'] = isoformat(user.last_logged_on)
    user_prepared['local_time'] = get_local_datetime(datetime.now(), user.tz).strftime('%I:%M %p')
    user_prepared['_response_time'] = response_time
    user_prepared['_seller'] = seller
    user_prepared['registered_on'] = user.registered_on
    user_prepared['country'] = user.country
    user_prepared['_country_printable'] = user.get_country_printable()

    if seller:
        user_prepared['is_followed'] = user.is_followed_by(g.user.id)
        user_prepared['followers_count'] = len(user.followers)

        rating, counts = user.get_rating()
        user_prepared['_feedbacks_rating_int'] = int(round(rating))
        user_prepared['_feedbacks_count'] = sum(counts)

    return json.jsonify(user_prepared)


@app.route('/api/user/status')
@xhr_required
@login_required
def api_user_status():
    incoming_ids = request.args.get('ids')
    ids = map(int, incoming_ids.split(','))

    data = cache.is_user_online_multiple(ids)

    return json.jsonify(data)


@account.route('/api/account/invite', methods=['POST'])
@login_required
@xhr_required
def api_invite_create():
    form = InviteAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        is_invited = is_existing = False

        if User.query.filter(User.email == form.email.data).first():
            is_existing = True
        elif UserInvitation.query.filter(UserInvitation.email == form.email.data, UserInvitation.user_id != g.user.id).first():
            is_invited = True
        elif UserInvitation.query.filter(UserInvitation.email == form.email.data, UserInvitation.user_id == g.user.id).first():
            raise APIError('You\'ve already invited user with this email address')

        if UserInvitation.query.filter_by(user_id=g.user.id, is_manual=True).count() >= 50:
            raise APIError('You reached a limit of 50 users you are allowed to invite manually')

        user_contact = UserInvitation(
            uuid=UserInvitation.get_uuid(),
            user_id=g.user.id,
            email=form.email.data,
            is_manual=True
        )

        if is_existing:
            user_contact.state = UserInvitation.EXISTING
        elif is_invited:
            user_contact.state = UserInvitation.ALREADY_INVITED

        db.session.add(user_contact)
        db.session.commit()

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/invite/<int:invitation_id>/resend', methods=['POST'])
@login_required
@xhr_required
def api_invite_resend(invitation_id):
    invitation = UserInvitation.query.get(invitation_id)
    if not invitation or invitation.user_id != g.user.id:
        abort(404)

    if invitation.state != UserInvitation.SENT or invitation.sent_on > datetime.utcnow() - timedelta(days=1):
        abort(403)

    invitation.state = UserInvitation.PENDING
    invitation.sent_on = None

    db.session.add(invitation)
    db.session.commit()

    return json.jsonify(dict())


@account.route('/api/account/invite/import/<platform>/urls')
@login_required
@xhr_required
def api_invite_import_urls(platform):
    if platform not in ('google', 'yahoo', 'outlook', 'aol'):
        abort(404)

    url = contacts_url = None

    if platform == 'google':
        url = url_for('contacts_google.login', _external=True)
        contacts_url = url_for('contacts_google.get_contacts')
    elif platform == 'aol':
        url = url_for('contacts_aol.login', _external=True)
        contacts_url = url_for('contacts_aol.get_contacts')
    elif platform == 'yahoo':
        url = url_for('contacts_yahoo.login', _external=True)
        contacts_url = url_for('contacts_yahoo.get_contacts')
    elif platform == 'outlook':
        url = url_for('contacts_outlook.login', _external=True)
        contacts_url = url_for('contacts_outlook.get_contacts')

    # TODO: remove this workaround for dev server:
    if app.config['DEVELOPMENT']:
        url = url.replace('//localhost', '//localhost:5002')

    return json.jsonify(dict(url=url, contacts_url=contacts_url))


@account.route('/api/account/invite/import', methods=['POST'])
@login_required
@xhr_required
def api_invite_import():
    incoming = request.get_json()
    incoming_emails = incoming.get('emails')

    for email in incoming_emails:
        is_invited = is_existing = False

        if User.query.filter(User.email == email).first():
            is_existing = True
        elif UserInvitation.query.filter(UserInvitation.email == email, UserInvitation.user_id != g.user.id).first():
            is_invited = True
        elif UserInvitation.query.filter(UserInvitation.email == email, UserInvitation.user_id == g.user.id).first():
            continue

        user_contact = UserInvitation(
            uuid=UserInvitation.get_uuid(),
            user_id=g.user.id,
            email=email,
            is_manual=False
        )

        if is_existing:
            user_contact.state = UserInvitation.EXISTING
        elif is_invited:
            user_contact.state = UserInvitation.ALREADY_INVITED

        db.session.add(user_contact)

    db.session.commit()
    return json.jsonify(dict())


@account.route('/api/account/invite/contacts')
@login_required
@xhr_required
def api_invite_contacts():
    incoming_limit = request.args.get('limit', 10, type=int)
    incoming_offset = request.args.get('offset', 0, type=int)

    invites_query = UserInvitation.query \
                               .filter(UserInvitation.user_id == g.user.id) \
                               .order_by(UserInvitation.created_on.desc())

    invites_count = invites_query.count()
    # invites_query = invites_query.limit(incoming_limit).offset(incoming_offset)

    invites_prepared = list()

    for invite in invites_query.all():
        invite_prepared = dict(
            id=invite.id,
            email=invite.email,
            state=invite.state
        )
        invites_prepared.append(invite_prepared)

    return json.jsonify(
        data=invites_prepared,
        meta=dict(
            total=invites_count
        )
    )


@account.route('/api/account/<int:user_id>/skill')
@login_required
@xhr_required
def api_show_skills(user_id):
    skills_query = UserSkills.query.filter(UserSkills.user_id == user_id)
    skills_count = skills_query.count()
    skills = list()
    for skill in skills_query.all():
        skills.append(dict(
            id=skill.id,
            skill_name=skill.skill_name
        ))
    return json.jsonify(
        data=skills,
        meta=dict(
            total=skills_count
        )
    )

@account.route('/api/account/skill', methods=['POST'])
@login_required
@xhr_required
def api_create_skill():
    form = SkillAPIForm(csrf_enabled=False)
    if form.validate_on_submit():
        query = UserSkills.query.filter(UserSkills.user_id == g.user.id,
                                        UserSkills.skill_name == form.skill_name.data)
        if db.session.query(query.exists()).scalar():
            raise APIError('You already have this skill')
        skill = UserSkills(
            user_id=g.user.id,
            skill_name=form.skill_name.data
        )

        db.session.add(skill)
        db.session.commit()

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/skill/delete', methods=['POST'])
@login_required
@xhr_required
def api_delete_skill():
    incoming = request.get_json()
    incoming_id = incoming.get('id')

    if not incoming_id:
        abort(404)

    skill = UserSkills.query.get_or_404(incoming_id)

    if skill.user_id != g.user.id:
        abort(404)

    db.session.delete(skill)
    db.session.commit()

    return json.jsonify(dict())


@account.route('/api/account/<int:user_id>/language')
@login_required
@xhr_required
def api_show_languages(user_id):
    languages_query = UserLanguages.query.filter(UserLanguages.user_id == user_id)
    languages_count = languages_query.count()
    languages = list()
    for language in languages_query.all():
        languages.append(dict(
            id=language.id,
            language_name=language.language_name,
            language_level=language.language_level
        ))
    return json.jsonify(
        data=languages,
        meta=dict(
            total=languages_count,
            levels=LanguageAPIForm.LEVELS
        )
    )

@account.route('/api/account/language', methods=['POST'])
@login_required
@xhr_required
def api_create_language():
    form = LanguageAPIForm(csrf_enabled=False)
    if form.validate_on_submit():
        query = UserLanguages.query.filter(UserLanguages.user_id == g.user.id,
                                           UserLanguages.language_name == form.language_name.data)
        if db.session.query(query.exists()).scalar():
            raise APIError('You already have this language')
        language = UserLanguages(
            user_id=g.user.id,
            language_name=form.language_name.data,
            language_level=form.language_level.data
        )

        db.session.add(language)
        db.session.commit()

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))


@account.route('/api/account/language/delete', methods=['POST'])
@login_required
@xhr_required
def api_delete_language():
    incoming = request.get_json()
    incoming_id = incoming.get('id')

    if not incoming_id:
        abort(404)

    language = UserLanguages.query.get_or_404(incoming_id)

    if language.user_id != g.user.id:
        abort(404)

    db.session.delete(language)
    db.session.commit()

    return json.jsonify(dict())



@account.route('/api/account/endorse', methods=['POST'])
@login_required
@xhr_required
def api_endorse_create():
    form = EndorseAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        token = '%d:%s' % (g.user.id, form.email.data)

        if cache.search_token(cache.TokenType.ENDORSEMENT, token, destroy_token=False):
            # Do not allow to send email more than once per day
            raise APIError('You\'ve already sent request to this e-mail address')

        email.send_endorsement(form.email.data, g.user, form.text.data)

        cache.add_token(cache.TokenType.ENDORSEMENT, token, 1, expire=86400)

        return json.jsonify(dict())
    else:
        raise APIError('Please make sure you have specified all the fields properly', payload=dict(fields=form.errors))
