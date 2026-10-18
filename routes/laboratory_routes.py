from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from services.domain.laboratory_service import LaboratoryService

laboratory_bp = Blueprint('laboratory', __name__, url_prefix='/laboratories')

@laboratory_bp.route('/')
@login_required
def list_laboratories():
    lab_service = LaboratoryService()
    laboratories, _ = lab_service.get_all_laboratories()
    return render_template('laboratory/list.html', laboratories=laboratories or [])

@laboratory_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_laboratory():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()

        lab_service = LaboratoryService()
        lab, msg = lab_service.create_laboratory(name, location, description)
        
        if lab:
            flash(msg, 'success')
            return redirect(url_for('laboratory.list_laboratories'))
        
        flash(msg, 'error') 

    return render_template('laboratory/create.html')

@laboratory_bp.route('/<int:lab_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_laboratory(lab_id):
    lab_service = LaboratoryService(lab_id=lab_id)
    lab, msg = lab_service.get_laboratory()
    if not lab:
        flash(msg, 'error')
        return redirect(url_for('laboratory.list_laboratories'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()

        updated_lab, update_msg = lab_service.update_laboratory(name=name, location=location, description=description)
        if updated_lab:
            flash(update_msg, 'success')
            return redirect(url_for('laboratory.list_laboratories'))
        
        flash(update_msg, 'error')

    return render_template('laboratory/edit.html', laboratory=lab)