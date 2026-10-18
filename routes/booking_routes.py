from flask import Blueprint, request, render_template, redirect, url_for, flash, send_file
from flask_login import login_required
from models.models import Status
from services.domain.booking_service import BookingService

bookings_bp = Blueprint('bookings', __name__, url_prefix='/bookings')

@bookings_bp.route('/')
@login_required
def list_bookings():
    page      = request.args.get('page', 1, type=int)
    search    = request.args.get('search', '').strip()
    status    = request.args.get('status', '')
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')

    booking_service = BookingService()
    pagination, _ = booking_service.display_bookings(
        page=page, search=search, status=status, date_from=date_from, date_to=date_to
    )
    return render_template('bookings/list.html', pagination=pagination, bookings=pagination.items,
                           search=search, status=status, date_from=date_from, date_to=date_to, Status=Status)



@bookings_bp.route('/<int:booking_id>')
@login_required
def booking_detail(booking_id):
    booking_service = BookingService(booking_id=booking_id)

    booking = getattr(booking_service, 'booking', None)

    if not booking:
        flash("الحجز غير موجود.", 'danger')
        return redirect(url_for('bookings.list_bookings'))

    return render_template('bookings/detail.html', booking=booking, Status=Status)


@bookings_bp.route('/update_status/<int:booking_id>', methods=['POST'])
@login_required
def update_booking_status(booking_id):
    try:
        status_enum = Status(request.form.get('status_val'))
    except ValueError:
        flash("حالة غير صحيحة", 'danger')
        return redirect(url_for('bookings.list_bookings'))

    booking_service = BookingService(booking_id=booking_id)
    updated, message = booking_service.update_booking_status(status_enum)
    flash(message, 'success' if updated else 'danger')


    return redirect(request.referrer or url_for('bookings.list_bookings'))


@bookings_bp.route('/export')
@login_required
def export_bookings():
    booking_service = BookingService()
    output = booking_service.export_to_excel(
        search=request.args.get('search', '').strip(),
        status=request.args.get('status', ''),
        date_from=request.args.get('date_from', ''),
        date_to=request.args.get('date_to', '')
    )
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='bookings.xlsx')