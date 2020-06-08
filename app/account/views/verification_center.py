import random
from flask import url_for, redirect, render_template, g, json, request, session, abort
from flask_login import login_required, current_user

from app import app
from app.decorators import xhr_required, seller_required
from app.utils.storage import Storage
from app.models import db, User, UserVerification, UserVerificationPhoto
from app.helpers import APIError

from .. import account
from ..helpers import prepare_application_data
from ..forms import VerifyCountrySelector, VerifyIDForm, VerifyAddressForm, VerifyKeycodeForm, ValidateImageForm


def check_verification(verification):
    if verification.state not in (UserVerification.DRAFT, UserVerification.REJECTED):
        raise APIError("Verification can't be edited.")


@account.route('/verification', methods=('GET',))
@login_required
def verification_center():
    application_data = prepare_application_data()

    verification = UserVerification.query.filter(UserVerification.user_id == current_user.id).first()
    if verification is None:
        # create and save and use it to check state
        verification = UserVerification(user_id=current_user.id)
        verification.random_code = random.randint(1000000000, 9999999999)
        db.session.add(verification)
        db.session.commit()

    return render_template(
        'new/account/verification-center.html',
        application_data=application_data,
        verification=verification
    )


@account.route('/verification/step/0', methods=('POST',))
@login_required
def verification_center_step_0():
    verification = UserVerification.query.filter(UserVerification.user_id == current_user.id).first()
    check_verification(verification)
    form = VerifyCountrySelector(csrf_enabled=False)
    form.validate_or_raise()
    if verification.state == UserVerification.DRAFT:
        verification.country_code = form.country_code.data
        db.session.add(verification)
        db.session.commit()
    return json.jsonify(verification.to_json())  # success


@account.route('/verification/step/1', methods=('POST',))
@login_required
def verification_center_step_1():
    verification = UserVerification.query.filter(UserVerification.user_id == current_user.id).first()
    check_verification(verification)
    form = VerifyIDForm(csrf_enabled=False)
    form.validate_or_raise()
    if verification.state == UserVerification.DRAFT:
        verification.first_name = form.first_name.data
        verification.last_name = form.last_name.data
        verification.birthdate = form.birthdate.data
        verification.id_issuing_country = form.id_issuing_country.data
        verification.id_expire_date = form.id_expire_date.data
        db.session.add(verification)
        db.session.commit()
    return json.jsonify(verification.to_json())


@account.route('/verification/step/2', methods=('POST',))
@login_required
def verification_center_step_2():
    form = VerifyKeycodeForm(csrf_enabled=False)
    form.validate_or_raise()
    verification = UserVerification.query.filter(UserVerification.user_id == current_user.id).first()
    check_verification(verification)
    return json.jsonify(verification.to_json())


@account.route('/verification/step/3', methods=('POST',))
@login_required
def verification_center_step_3():
    verification = UserVerification.query.filter(UserVerification.user_id == current_user.id).first()
    check_verification(verification)
    form = VerifyAddressForm(csrf_enabled=False)
    form.validate_or_raise()
    if verification.state == UserVerification.DRAFT:
        verification.address_line_1 = form.address_line_1.data
        verification.address_line_2 = form.address_line_2.data

        verification.city = form.city.data
        verification.country_state = form.country_state.data
        verification.postal_code = form.postal_code.data

        verification.institution_name = form.institution_name.data
        verification.document_type = form.document_type.data
        verification.document_date_issued = form.document_date_issued.data

        verification.state = UserVerification.PENDING  # change STATE
        db.session.add(verification)
        db.session.commit()
    return json.jsonify(verification.to_json())  # success


@account.route('/verification/image_upload/', methods=('POST',))
@login_required
def verification_upload_image():
    verification = UserVerification.query.filter(UserVerification.user_id == current_user.id).first()
    if verification.state not in (UserVerification.DRAFT, UserVerification.REJECTED):
        raise APIError("Verification can't be edited.")
    form = ValidateImageForm(csrf_enabled=False)
    form.validate_or_raise()
    img = UserVerificationPhoto(user_id=current_user.id, step=form.step.data)
    db.session.add(img)
    db.session.commit()  # to get the id
    storage = Storage()
    key, clouinary_key = storage.upload_verification_photo(form.photo.data, img.id, )
    img.filename = key
    img.cloudinary_key = clouinary_key
    db.session.add(img)
    db.session.commit()
    return json.jsonify(img.to_json())


@account.route('/verification/images/<int:step>/', methods=('GET',))
@login_required
def verification_images(step):
    rows = UserVerification.query.filter(
        UserVerificationPhoto.user_id == current_user.id,
        UserVerificationPhoto.hidden == False,
        UserVerificationPhoto.step == step).all()
    rows_json = tuple(row.to_json() for row in rows)
    data = {'rows': rows_json}
    return json.jsonify(data)

