import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from io import BytesIO

import openpyxl
from sqlalchemy.exc import IntegrityError

from models.models import Booking, Status, db
from services.domain.ticket_service import generate_booking_img
from utils.text_utils import make_reference_id
from utils.excel_utils import format_excel_sheet

logger = logging.getLogger(__name__)


@dataclass
class BookingSaveResult:
    reference_id: str
    image_bytes: bytes
    booking_id: int


class BookingService:
    def __init__(self, booking_id=None, reference_id=None, booking=None):
        """Initialize the service with a booking ID, reference ID, or loaded booking."""
        self.booking_id = booking_id
        self.reference_id = reference_id
        self._booking = booking

        if booking:
            self.booking_id = booking.id
            self.reference_id = booking.reference_id

    @property
    def booking(self):
        """Lazily load the booking by ID or reference ID."""
        if self._booking is None:
            if self.booking_id is not None:
                self._booking = db.session.get(Booking, self.booking_id)
            elif self.reference_id is not None:
                self._booking = Booking.query.filter_by(
                    reference_id=self.reference_id
                ).first()

        return self._booking

    def display_bookings(
        self,
        page=1,
        per_page=10,
        search=None,
        status=None,
        date_from=None,
        date_to=None,
    ):
        """
        Fetch paginated bookings using the provided filters.

        Without search or date filters, only the last 30 days are returned.
        Date filters apply to the appointment date, not booking creation time.
        """
        query = Booking.query

        # Apply the default 30-day window only when no explicit filters are provided.
        if not date_from and not date_to and not search:
            before_30_days = datetime.now(timezone.utc) - timedelta(days=30)
            query = query.filter(Booking.booking_time >= before_30_days)

        if search:
            query = query.filter(
                db.or_(
                    Booking.name.ilike(f"%{search}%"),
                    Booking.phone_number.ilike(f"%{search}%"),
                )
            )

        if status:
            try:
                query = query.filter(Booking.status == Status(status))
            except ValueError:
                pass

        if date_from:
            query = query.filter(Booking.date >= date_from)

        if date_to:
            query = query.filter(Booking.date <= date_to)

        pagination = query.order_by(
            Booking.booking_time.desc()
        ).paginate(
            page=page,
            per_page=per_page,
            error_out=False,
        )

        return pagination, "تم العثور على الحجوزات"

    def update_booking_status(self, new_status: Status, booking_id=None):
        """Update a booking's status and return the updated booking."""
        # Support the historical reversed argument order: (booking_id, status).
        if isinstance(new_status, int) or isinstance(booking_id, Status):
            actual_booking_id, actual_status = new_status, booking_id
        else:
            actual_booking_id = booking_id or self.booking_id
            actual_status = new_status

        booking = None

        if self._booking and (
            not actual_booking_id or self._booking.id == actual_booking_id
        ):
            booking = self._booking
        elif actual_booking_id:
            booking = db.session.get(Booking, actual_booking_id)

        if not booking:
            return None, "الحجز غير موجود"

        try:
            booking.status = actual_status
            db.session.commit()

            self._booking = booking
            self.booking_id = booking.id

            return booking, "تم تحديث الحالة"

        except Exception:
            db.session.rollback()
            logger.exception("[BookingService.update_booking_status] Error")
            return None, "حدث خطأ أثناء تحديث الحالة"

    def save_booking(
        self,
        name: str,
        phone: str,
        date: str,
        details: str,
        comes_from: str,
        time: str,
        address: str,
    ) -> BookingSaveResult:
        """
        Save a booking, generate its reference ID, and create its confirmation image.

        Reference ID collisions are handled by the database constraint and re-raised.
        """
        reference_id = make_reference_id()

        while Booking.query.filter_by(
            reference_id=reference_id
        ).first() is not None:
            reference_id = make_reference_id()

        booking = Booking(
            name=name,
            phone_number=phone,
            date=date,
            details=details,
            comes_from=comes_from,
            reference_id=reference_id,
            booking_time=datetime.now(timezone.utc),
            time=time,
            address=address,
        )

        db.session.add(booking)

        try:
            db.session.commit()

        except IntegrityError:
            db.session.rollback()
            logger.exception(
                "[BookingService.save_booking] IntegrityError committing booking "
                "(reference_id=%s)",
                reference_id,
            )
            raise

        except Exception:
            db.session.rollback()
            logger.exception(
                "[BookingService.save_booking] Error committing booking"
            )
            raise

        self._booking = booking
        self.booking_id = booking.id
        self.reference_id = reference_id

        image_bytes = generate_booking_img(
            name=name,
            phone=phone,
            date=date,
            details=details,
            reference_id=reference_id,
            time=time,
            address=address,
        )

        return BookingSaveResult(
            reference_id=reference_id,
            image_bytes=image_bytes,
            booking_id=booking.id,
        )

    def export_to_excel(self, search, status, date_from, date_to):
        """Generate an in-memory Excel workbook using the booking filters with premium formatting."""
        pagination, _ = self.display_bookings(
            page=1,
            per_page=99999,
            search=search,
            status=status,
            date_from=date_from,
            date_to=date_to,
        )

        wb = openpyxl.Workbook()
        ws = wb.active

        headers = [
            "الرقم المرجعي",
            "الاسم",
            "رقم الهاتف",
            "العنوان",
            "التفاصيل",
            "تاريخ الزيارة",
            "الوقت",
            "المنصة",
            "وقت الإنشاء",
            "الحالة",
        ]

        rows = []
        for booking in pagination.items:
            rows.append([
                booking.reference_id or f"#{booking.id}",
                booking.name,
                booking.phone_number,
                booking.address,
                booking.details,
                booking.date,
                booking.time,
                booking.comes_from or "غير محدد",
                (
                    booking.booking_time.strftime("%Y-%m-%d %H:%M")
                    if booking.booking_time
                    else ""
                ),
                booking.status.value if booking.status else "",
            ])

        format_excel_sheet(
            ws,
            title="الحجوزات المنزلية",
            headers=headers,
            rows=rows,
            status_col_idx=10,  # 10th column is Status
        )

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        return output

    @staticmethod
    def get_total_bookings_count() -> int:
        """Return the total number of bookings."""
        try:
            return Booking.query.count()
        except Exception:
            logger.exception("[BookingService.get_total_bookings_count] Error")
            return 0

    @staticmethod
    def get_booking_by_ref(reference_id: str):
        """Get a booking by its reference ID."""
        if not reference_id:
            return None

        try:
            return Booking.query.filter_by(
                reference_id=reference_id
            ).first()
        except Exception:
            logger.exception("[BookingService.get_booking_by_ref] Error")
            return None