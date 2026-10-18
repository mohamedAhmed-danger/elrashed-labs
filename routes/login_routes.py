from flask import Blueprint, jsonify, redirect, url_for, request, flash, render_template
from flask_login import current_user, login_user, logout_user, login_required
from services.domain.dashboard_service import DashboardService
from services.domain.user_service import UserService

main_bp = Blueprint('main', __name__)

@main_bp.route('/health')
def health():
    return jsonify(status="ok"), 200

@main_bp.route('/')
def index():
    return redirect(url_for('main.login'))

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        user_service = UserService()
        user = user_service.authenticate(username, password)
        if user:
            login_user(user)
            return redirect(url_for('main.dashboard'))
            
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'error')
        
    return render_template('login.html')

@main_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))

@main_bp.route('/dashboard')
@login_required
def dashboard():
    # كل الداتا بتاعت الداشبورد بتيجي من سيرفيس واحدة بتلم كل حاجة
    dashboard_service = DashboardService()
    dashboard_data = dashboard_service.get_summary_data()

    return render_template(
        'dashboard.html',
        subscription=dashboard_data.get('subscription'),
        subscription_status=dashboard_data.get('subscription_status'),
        usage_percentage=dashboard_data.get('usage_percentage'),
        remaining_messages=dashboard_data.get('remaining_messages'),
        clients_count=dashboard_data.get('clients_count', 0),
        booking_stats=dashboard_data.get('booking_stats', {'total': 0}),
        pending_inquiries_count=dashboard_data.get('pending_inquiries_count', 0),
        tests_count=dashboard_data.get('tests_count', 0),
    )