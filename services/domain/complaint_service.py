import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Optional
import openpyxl

from models.models import Complaint, Status, db
from utils.excel_utils import format_excel_sheet

logger = logging.getLogger(__name__)


@dataclass
class ComplaintSaveResult:
    success: bool
    complaint: Optional[Complaint] = None
    message: str = ""


class ComplaintService:
    def __init__(self, complaint_id=None, complaint=None):
        """Initialize with a complaint_id or a pre-loaded Complaint instance."""
        self.complaint_id = complaint_id
        self._complaint = complaint
        if complaint:
            self.complaint_id = complaint.id

    @property
    def complaint(self):
        """Lazily load and cache the Complaint tied to self.complaint_id."""
        if self._complaint is None and self.complaint_id is not None:
            self._complaint = db.session.get(Complaint, self.complaint_id)
        return self._complaint

    def get_all_complaints(self, page=1, per_page=10, search=None, status=None):
        """Fetch paginated complaints filtered by search text and status. Returns (Pagination, message)."""
        query = Complaint.query

        if search:
            query = query.filter(
                db.or_(
                    Complaint.phone_number.ilike(f'%{search}%'),
                    Complaint.complaint_text.ilike(f'%{search}%'),
                )
            )

        if status:
            try:
                query = query.filter(Complaint.status == Status(status))
            except ValueError:
                pass

        query = query.order_by(Complaint.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        return pagination, "تم العثور على الشكاوى"

    def update_complaint_status(self, new_status: Status, complaint_id=None):
        """
        Update a complaint's status. Returns (Complaint or None, message string).

        Legacy note: same reversed-argument safety net as
        BookingService.update_booking_status. A project-wide grep found no
        live caller using the reversed shape — the only current call site
        (routes/complaint_routes.py) passes update_complaint_status(status_enum)
        with complaint_id defaulting to None. Kept as a harmless no-op since
        Status is a plain Enum (not IntEnum).
        """
        if isinstance(new_status, int) or isinstance(complaint_id, Status):
            actual_complaint_id, actual_status = new_status, complaint_id
        else:
            actual_complaint_id = complaint_id or self.complaint_id
            actual_status = new_status

        complaint = None
        if self._complaint and (not actual_complaint_id or self._complaint.id == actual_complaint_id):
            complaint = self._complaint
        elif actual_complaint_id:
            complaint = db.session.get(Complaint, actual_complaint_id)

        if not complaint:
            return None, "الشكوى غير موجودة"
        try:
            complaint.status = actual_status
            db.session.commit()
            self._complaint = complaint
            self.complaint_id = complaint.id
            return complaint, "تم تحديث الحالة"
        except Exception:
            db.session.rollback()
            logger.exception("[ComplaintService.update_complaint_status] Error")
            return None, "حدث خطأ أثناء تحديث الحالة"

    def save_complaint(self, phone_number: str, complaint_text: str, comes_from: str = "unknown") -> ComplaintSaveResult:
        """
        Register a new complaint. Returns a ComplaintSaveResult.

        On failure, the returned message is a generic Arabic message — never
        the raw exception text — because this can be relayed directly to the
        customer via save_complaint_tool. Technical details go to the log only.
        """
        try:
            complaint = Complaint(
                phone_number=phone_number,
                complaint_text=complaint_text,
                comes_from=comes_from,
            )
            db.session.add(complaint)
            db.session.commit()
            self._complaint = complaint
            self.complaint_id = complaint.id
            return ComplaintSaveResult(
                success=True,
                complaint=complaint,
                message=(
                    f"تم تسجيل شكواك بنجاح\n"
                    f"رقم هاتفك: {phone_number}\n"
                    f"سيتواصل معك فريقنا في أقرب وقت ممكن."
                ),
            )
        except Exception:
            db.session.rollback()
            logger.exception("[ComplaintService.save_complaint] Error saving complaint")
            return ComplaintSaveResult(
                success=False,
                complaint=None,
                message="حدث خطأ أثناء حفظ الشكوى، حاول مرة أخرى.",
            )

    def export_to_excel(self, search, status):
        """Generate an in-memory Excel workbook of complaints matching the filter criteria."""
        pagination, _ = self.get_all_complaints(
            page=1, per_page=99999, search=search, status=status
        )

        wb = openpyxl.Workbook()
        ws = wb.active

        headers = ["رقم الهاتف", "الشكوى", "تاريخ الإنشاء", "المنصة", "الحالة"]
        rows = []

        for complaint in pagination.items:
            rows.append([
                complaint.phone_number,
                complaint.complaint_text,
                complaint.created_at.strftime('%Y-%m-%d %H:%M') if complaint.created_at else '',
                complaint.comes_from or 'غير محدد',
                complaint.status.value if complaint.status else 'Pending'
            ])

        format_excel_sheet(
            ws,
            title="سجل الشكاوى",
            headers=headers,
            rows=rows,
            status_col_idx=5
        )

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output