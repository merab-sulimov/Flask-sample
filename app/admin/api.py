from flask import request, url_for, g, abort, json

from . import admin
from .forms import ServiceUpdateAPIForm
from app.decorators import admin_required
from app.models import db, Product
from app.utils import render_markdown
from app import search


def prepare_service(service):
    service_prepared = service.to_json()

    service_prepared['description'] = service.description
    service_prepared['is_deleted'] = service.is_deleted
    service_prepared['is_approved'] = service.is_approved
    service_prepared['not_approved'] = service.not_approved
    service_prepared['published_on'] = service.published_on

    return service_prepared


@admin.route('/api/admin/service/<custom_id>')
@admin_required
def api_service(custom_id):
    service = Product.get_by_custom_id(custom_id)

    if not service:
        abort(404)

    service_prepared = prepare_service(service)

    return json.jsonify(service_prepared)


@admin.route('/api/admin/service/<custom_id>', methods=['PUT'])
@admin_required
def api_service_edit(custom_id):
    service = Product.get_by_custom_id(custom_id)

    if not service:
        abort(404)

    form = ServiceUpdateAPIForm(csrf_enabled=False)

    if form.validate_on_submit():
        service.title = form.title.data
        service.description = form.description.data

        db.session.add(service)
        db.session.commit()

        if not service.is_private and service.is_approved and service.published_on:
            search.product_updated.send(product=service)
    else:
        abort(400)

    service_prepared = prepare_service(service)

    return json.jsonify(service_prepared)


@admin.route('/api/admin/service/<custom_id>/approve', methods=['POST'])
@admin_required
def api_service_approve(custom_id):
    service = Product.get_by_custom_id(custom_id)

    if not service:
        abort(404)

    service.verification_approve()

    if not service.is_private:
        search.product_updated.send(product=service)

    service_prepared = prepare_service(service)

    return json.jsonify(service_prepared)


@admin.route('/api/admin/service/<unique_id>/description/render', methods=['POST'])
@admin_required
def api_service_description_render(unique_id):
    incoming = request.get_json()
    incoming_text = incoming.get('text')
    
    return render_markdown(incoming_text)


@admin.route('/api/admin/service/<custom_id>/reject', methods=['POST'])
@admin_required
def service_reject(custom_id):
    service = Product.get_by_custom_id(custom_id)

    if not service:
        abort(404)

    service.verification_reject()

    search.product_deleted.send(product=service)

    service_prepared = prepare_service(service)

    return json.jsonify(service_prepared)


@admin.route('/api/admin/products/<int:product_id>/recommend', methods=['POST'])
@admin_required
def product_recommend(product_id):
    incoming = request.get_json()
    if not incoming:
        abort(404)
    incoming_recommend = incoming.get('recommend')
    if not isinstance(incoming, bool):
        abort(404)

    product = Product.query.get_or_404(product_id)
    product.is_recommended = incoming_recommend
    db.session.add(product)
    db.session.commit()

    return json.jsonify({})

