import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

def format_excel_sheet(ws, title="البيانات", headers=None, rows=None, status_col_idx=None):
    """
    Format an openpyxl Worksheet with premium styling:
    - Right-to-left layout for Arabic text
    - Sleek Navy/Slate Header with bold white text
    - Zebra striping on data rows
    - Status badge conditional highlighting
    - Clean thin grid borders
    - Auto column width adjustments
    """
    # 1. Enable RTL layout for Arabic
    ws.views.sheetView[0].rightToLeft = True
    ws.title = title

    # Styles definitions
    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    
    even_row_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    odd_row_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0')
    )

    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    center_alignment = Alignment(horizontal="center", vertical="center")
    right_alignment = Alignment(horizontal="right", vertical="center")

    # Status color fills & fonts map
    status_styles = {
        "Pending": (PatternFill(start_color="FEF3C7", fill_type="solid"), Font(name="Segoe UI", size=10, bold=True, color="92400E")),
        "قيد الانتظار": (PatternFill(start_color="FEF3C7", fill_type="solid"), Font(name="Segoe UI", size=10, bold=True, color="92400E")),
        "Reviewed": (PatternFill(start_color="DBEAFE", fill_type="solid"), Font(name="Segoe UI", size=10, bold=True, color="1E40AF")),
        "تمت المراجعة": (PatternFill(start_color="DBEAFE", fill_type="solid"), Font(name="Segoe UI", size=10, bold=True, color="1E40AF")),
        "Attended": (PatternFill(start_color="DCFCE7", fill_type="solid"), Font(name="Segoe UI", size=10, bold=True, color="166534")),
        "تم الحضور": (PatternFill(start_color="DCFCE7", fill_type="solid"), Font(name="Segoe UI", size=10, bold=True, color="166534")),
        "No Show": (PatternFill(start_color="FEE2E2", fill_type="solid"), Font(name="Segoe UI", size=10, bold=True, color="991B1B")),
        "لم يحضر": (PatternFill(start_color="FEE2E2", fill_type="solid"), Font(name="Segoe UI", size=10, bold=True, color="991B1B")),
    }

    # Write headers if provided
    if headers:
        ws.append(headers)

    # Write rows if provided
    if rows:
        for row in rows:
            ws.append(row)

    # Style Header (Row 1)
    ws.row_dimensions[1].height = 28
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment
        cell.border = thin_border

    # Style Data Rows
    max_row = ws.max_row
    max_col = ws.max_column

    for r in range(2, max_row + 1):
        ws.row_dimensions[r].height = 22
        row_fill = even_row_fill if r % 2 == 0 else odd_row_fill

        for c in range(1, max_col + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = thin_border
            cell.fill = row_fill
            cell.font = Font(name="Segoe UI", size=10, color="1E293B")
            cell.alignment = right_alignment

            # Center alignment for numbers, dates, phone numbers, reference IDs
            val_str = str(cell.value or '')
            if c == status_col_idx or any(char.isdigit() for char in val_str[:4]) and len(val_str) < 25:
                cell.alignment = center_alignment

            # Check if this cell is a status column
            if status_col_idx and c == status_col_idx:
                val = str(cell.value) if cell.value is not None else ""
                if val in status_styles:
                    s_fill, s_font = status_styles[val]
                    cell.fill = s_fill
                    cell.font = s_font
                    cell.alignment = center_alignment

    # Auto-adjust column widths
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            val = str(cell.value or '')
            # Handle unicode/arabic length estimation
            max_len = max(max_len, len(val))
        
        adjusted_width = min(max(max_len + 5, 14), 50)
        ws.column_dimensions[col_letter].width = adjusted_width

    return ws
