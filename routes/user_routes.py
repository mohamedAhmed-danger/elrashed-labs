from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from services.domain.user_service import UserService

users_bp = Blueprint('users', __name__, url_prefix='/users')


@users_bp.route('/')
@login_required
def list_users():
    user_service = UserService()
    all_users = user_service.get_all_users()
    return render_template('user/user.html', users=all_users)


@users_bp.route('/new', methods=['GET', 'POST'])
@login_required
def create_user():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        password = request.form.get('password', '').strip()

        user_service = UserService()
        user, message = user_service.create_user(name, password)
        flash(message, 'success' if user else 'error')
        
        if user:
            return redirect(url_for('users.list_users'))

    return render_template('user/edit_user.html', user=None)


@users_bp.route('/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    user_service = UserService(user_id=user_id)
    user, message = user_service.get_user()

    if not user:
        flash(message, 'error')
        return redirect(url_for('users.list_users'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        password = request.form.get('password', '').strip()
        
        updated_user, message = user_service.update_user(name=name, password=password)
        flash(message, 'success' if updated_user else 'error')

        if updated_user:
            return redirect(url_for('users.list_users'))

    return render_template('user/edit_user.html', user=user)