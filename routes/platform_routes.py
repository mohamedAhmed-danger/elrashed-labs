from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from services.shared.platform_service import PlatformService

platforms_bp = Blueprint('platforms', __name__, url_prefix='/platforms')


@platforms_bp.route('/')
@login_required
def list_platforms():
    platform_service = PlatformService()
    platforms, _ = platform_service.get_all_platforms()
    return render_template('platform/list.html', platforms=platforms)


@platforms_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_platform():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        platform_service = PlatformService()
        platform, msg = platform_service.create_platform(name)
        if platform:
            flash(msg, 'success')
            return redirect(url_for('platforms.list_platforms'))
        flash(msg, 'error')

    return render_template('platform/create.html')


@platforms_bp.route('/<int:platform_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_platform(platform_id):
    platform_service = PlatformService(platform_id=platform_id)
    platform, msg = platform_service.get_platform()
    if not platform:
        flash(msg, 'error')
        return redirect(url_for('platforms.list_platforms'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        updated, msg = platform_service.update_platform(name=name)
        if updated:
            flash(msg, 'success')
            return redirect(url_for('platforms.list_platforms'))
        flash(msg, 'error')

    return render_template('platform/edit.html', platform=platform)