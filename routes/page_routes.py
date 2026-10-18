from flask import Blueprint, request, render_template, redirect, url_for, flash
from flask_login import login_required
from services.domain.page_service import PageService
from services.domain.laboratory_service import LaboratoryService

pages_bp = Blueprint('pages', __name__, url_prefix='/pages')
 
@pages_bp.route('/')
@login_required
def list_pages():
    page_service = PageService()
    pages, _ = page_service.get_all_pages()
    return render_template('pages/list.html', pages=pages)

@pages_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_page():
    page_service = PageService()
    platforms, _ = page_service.get_all_platforms()

    if request.method == 'POST':
        platform_id = request.form.get('platform_id')
        page_id = request.form.get('page_id')
        token = request.form.get('token')
        laboratory_id = LaboratoryService().get_current_laboratory_id()

        page, msg = page_service.create_page(laboratory_id=laboratory_id, platform_id=platform_id, page_id=page_id, token=token)
        if page:
            flash(msg, 'success')
            return redirect(url_for('pages.list_pages'))
        flash(msg, 'error')

    return render_template('pages/create.html', platforms=platforms)

@pages_bp.route('/<int:platform_id>/<page_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_page(platform_id, page_id):
    page_service = PageService(platform_id=platform_id, page_id=page_id)
    page, msg = page_service.get_page()
    if not page:
        flash(msg, 'error')
        return redirect(url_for('pages.list_pages'))

    if request.method == 'POST':
        token = request.form.get('token')
        updated, msg = page_service.update_page_token(token)
        if updated:
            flash(msg, 'success')
            return redirect(url_for('pages.list_pages'))
        flash(msg, 'error')

    return render_template('pages/edit.html', page=page)

@pages_bp.route('/<int:platform_id>/<page_id>/delete', methods=['POST'])
@login_required
def delete_page(platform_id, page_id):
    page_service = PageService(platform_id=platform_id, page_id=page_id)
    page, msg = page_service.delete_page()
    flash(msg, 'success' if page else 'error')
    return redirect(url_for('pages.list_pages'))