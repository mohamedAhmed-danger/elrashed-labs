"""
bulk_import_tests.py

Script لعمل insert لكل الصفوف اللي في Filtered_Tests_Prices.xlsx (Type / Test Name / Price)
باستخدام نفس الـ pipeline الموجود عندك بالظبط:
    generate_test()  ->  TestsService.create_lab_service()

يعني كل تحليل هياخد وصف + تعليمات + keywords + aliases + sample_type + duration
من الـ AI بالظبط زي لما تعمله يدوي من الفورم، وبعدين يتعمله insert في الداتابيز
وupsert في Qdrant تلقائي (لأن create_lab_service بيعمل ده جوه).

--------------------------------------------------------------------------
قبل ما تشغله:
1) عدّل الـ import بتاع الـ Flask app تحت (IMPORT الخاص بالـ app/db) على حسب
   شكل app.py عندك بالظبط (create_app() ولا app جاهز).
2) الاسكريبت بياخد أول Laboratory موجود في الداتابيز تلقائي (زي ما قولت
   "أول واحد في الـ db مفيش غيره"). لو حبيت تحدد لاب معين غيّر GET_LAB_STRATEGY.
3) جرب الأول بعدد صغير: 
       python bulk_import_tests.py --limit 5
   وبعدين لما تتأكد إنه شغال صح شغله كامل:
       python bulk_import_tests.py

المزايا:
- Resume تلقائي: لو الاسكريبت اتقفل في النص، شغله تاني وهيكمل من غير ما يعيد
  التحاليل اللي خلصت (بيتأكد من الاسم في الداتابيز قبل لما يستهلك AI call).
- بيسجل كل تحليل فشل في ملف failed_tests.csv عشان تراجعه/تعيد تشغيله لوحده.
- بينام delay بسيط بين كل استدعاء AI عشان ميضربش rate limit.
- بيكتب log تفصيلي (import_log.txt افتراضيًا، أو حدده بـ --log-file) فيه لكل
  تحليل: اسمه، نتيجة التوليد من Gemini كاملة، النص اللي اتحول embedding،
  اللي اتحفظ في الداتابيز، والـ metadata اللي راحت (أو حاولت تروح) لـ Qdrant.
"""

import argparse
import csv
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import openpyxl

# --------------------------------------------------------------------------
# 1) IMPORT بتاع الـ Flask app والـ db - عدّل السطرين دول على حسب app.py عندك
# --------------------------------------------------------------------------
try:
    # لو عندك app.py فيه app جاهز (Flask(__name__) على مستوى الملف)
    from app import app  # noqa: E402
except ImportError:
    # لو عندك factory pattern: def create_app(): ...
    from app import create_app  # noqa: E402
    app = create_app()

from models.models import db, Laboratory  # noqa: E402
import services.tests_service as tests_service_module  # noqa: E402
from services.domain.tests_service import TestsService  # noqa: E402
from services.shared.generation_service import generate_test  # noqa: E402
from services.shared.vector_service import upsert_test_vector as _real_upsert_test_vector  # noqa: E402

try:
    from utils.text_utils import build_test_text
except ImportError:
    # fallback بسيط لو اتغير اسم/مكان الدالة - نفس منطق التركيب المتوقع
    def build_test_text(name, description, keywords):
        return f"{name}. {description or ''} {' '.join(keywords or [])}".strip()


# --------------------------------------------------------------------------
# إعدادات
# --------------------------------------------------------------------------
DEFAULT_EXCEL_PATH = "Filtered_Tests_Prices.xlsx"
FAILED_LOG_PATH = "failed_tests.csv"
DEFAULT_DETAIL_LOG_PATH = "import_log.txt"
SLEEP_BETWEEN_CALLS = 1.0  # ثانية بين كل نداء AI - زوّدها لو حصل rate limit


def get_target_laboratory():
    """
    بيرجع أول Laboratory موجود في الداتابيز.
    (حسب كلامك: مفيش غيره دلوقتي)
    """
    lab = Laboratory.query.order_by(Laboratory.id.asc()).first()
    if not lab:
        raise RuntimeError(
            "مفيش أي Laboratory في الداتابيز خالص. "
            "ضيف معمل واحد على الأقل الأول قبل ما تشغل الاسكريبت."
        )
    return lab


def read_excel_rows(excel_path: str):
    """
    بيقرأ الشيت وبيرجع list of dicts: [{"type":..., "name":..., "price":...}, ...]
    """
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb.active

    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        row_type, name, price = row[0], row[1], row[2]
        if not name or str(name).strip() == "":
            continue
        rows.append(
            {
                "type": (row_type or "").strip() if isinstance(row_type, str) else row_type,
                "name": str(name).strip(),
                "price": float(price) if price not in (None, "") else 0.0,
            }
        )
    return rows


def already_exists(name: str) -> bool:
    from models.models import LabService
    return LabService.query.filter_by(name=name).first() is not None


def log_failure(name: str, price: float, error: str):
    file_exists = Path(FAILED_LOG_PATH).exists()
    with open(FAILED_LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["name", "price", "error"])
        writer.writerow([name, price, error])


def generation_result_to_dict(generated) -> dict:
    """بيحوّل TestGenerationResult (pydantic) لـ dict عادي، متوافق مع pydantic v1 و v2."""
    if hasattr(generated, "model_dump"):
        return generated.model_dump()
    return generated.dict()


def format_list(value) -> str:
    if not value:
        return "[]"
    return "[" + ", ".join(str(v) for v in value) + "]"


def write_detail_log(log_path: str, index: int, total: int, name: str,
                      generated_dict: dict | None,
                      embed_text: str | None,
                      db_fields: dict | None,
                      db_status: str,
                      qdrant_payload: dict | None,
                      qdrant_status: str):
    """
    بيكتب في ملف الـ log بلوك واحد واضح لكل تحليل فيه بالظبط:
    1) اسم التحليل
    2) نتيجة التوليد من Gemini
    3) النص اللي هيتحول embedding
    4) اللي هيتحفظ في الداتابيز
    5) الـ metadata اللي راحت (أو مراحتش) لـ Qdrant
    """
    lines = []
    lines.append("=" * 70)
    lines.append(f"[{index}/{total}] {name}")
    lines.append("=" * 70)

    lines.append("🧬 نتيجة التوليد من Gemini:")
    if generated_dict is None:
        lines.append("  (لم يتم التوليد - حصل خطأ قبل الوصول للخطوة دي)")
    else:
        lines.append(f"  description          : {generated_dict.get('description', '')}")
        lines.append(f"  patient_instructions  : {generated_dict.get('patient_instructions', '')}")
        lines.append(f"  keywords              : {format_list(generated_dict.get('keywords'))}")
        lines.append(f"  alias_name            : {format_list(generated_dict.get('alias_name'))}")
        lines.append(f"  duration              : {generated_dict.get('duration')}")
        lines.append(f"  sample_type           : {generated_dict.get('sample_type')}")
    lines.append("")

    lines.append("🧠 النص اللي هيتحول لـ embedding:")
    lines.append(f'  "{embed_text}"' if embed_text else "  (لسه ماتحسبش)")
    lines.append("")

    lines.append("💾 اللي هيتحفظ في الداتابيز (LabService):")
    if db_fields is None:
        lines.append("  (لسه ماتحفظش)")
    else:
        for key, val in db_fields.items():
            if isinstance(val, list):
                val = format_list(val)
            lines.append(f"  {key:<20}: {val}")
    lines.append(f"  الحالة: {db_status}")
    lines.append("")

    lines.append("🔎 الـ metadata اللي بعتت (أو محاولة إرسالها) لـ Qdrant:")
    if qdrant_payload is None:
        lines.append("  (لسه محصلش)")
    else:
        for key, val in qdrant_payload.items():
            if isinstance(val, list):
                val = format_list(val)
            lines.append(f"  {key:<12}: {val}")
    lines.append(f"  الحالة: {qdrant_status}")
    lines.append("")
    lines.append("")

    with open(log_path, "a", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Bulk import lab tests from Excel using the AI generation pipeline")
    parser.add_argument("--excel", default=DEFAULT_EXCEL_PATH, help="Path to the Filtered_Tests_Prices.xlsx file")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N rows (for testing)")
    parser.add_argument("--sleep", type=float, default=SLEEP_BETWEEN_CALLS, help="Seconds to sleep between AI calls")
    parser.add_argument("--dry-run", action="store_true", help="Generate with AI but don't insert into DB/Qdrant")
    parser.add_argument(
        "--skip-vectors",
        action="store_true",
        help="Don't attempt to upsert into Qdrant at all (use this while Qdrant is down/unreachable). "
             "Insert into the SQL DB only, then re-index into Qdrant later once it's back up.",
    )
    parser.add_argument(
        "--log-file",
        default=DEFAULT_DETAIL_LOG_PATH,
        help="Path to the detailed per-test log file (name, Gemini result, embedding text, DB fields, Qdrant metadata)",
    )
    args = parser.parse_args()

    if not Path(args.excel).exists():
        print(f"❌ الملف مش موجود: {args.excel}")
        sys.exit(1)

    # last_qdrant_call بتتحدث في كل مرة الـ wrapper بيتنادي، عشان نقدر نطبعها في الـ log
    last_qdrant_call = {}

    def logged_upsert_test_vector(test_id, test_name, description, keywords):
        try:
            embed_text = build_test_text(test_name, description, keywords)
        except Exception as e:
            embed_text = f"<تعذر بناء نص الـ embedding: {e}>"

        payload = {
            "test_id": test_id,
            "name": test_name,
            "description": description,
            "keywords": keywords or [],
        }

        if args.skip_vectors:
            last_qdrant_call.update(
                {"embed_text": embed_text, "payload": payload, "status": "اتخطي (--skip-vectors)"}
            )
            return

        try:
            _real_upsert_test_vector(test_id, test_name, description, keywords)
            last_qdrant_call.update(
                {"embed_text": embed_text, "payload": payload, "status": "✅ تم الـ upsert بنجاح"}
            )
        except Exception as e:
            last_qdrant_call.update(
                {"embed_text": embed_text, "payload": payload, "status": f"❌ فشل: {e}"}
            )

    # نستبدل الدالة اللي tests_service.py بينادي عليها بالـ wrapper اللي بيسجل كل حاجة
    tests_service_module.upsert_test_vector = logged_upsert_test_vector

    if args.skip_vectors:
        print("⚠️  --skip-vectors مفعّل: مش هيتعمل أي upsert فعلي لـ Qdrant دلوقتي.")

    with app.app_context():
        lab = get_target_laboratory()
        print(f"➡️  هيتم الإدراج على المعمل: {lab.name} (id={lab.id})")

        rows = read_excel_rows(args.excel)
        if args.limit:
            rows = rows[: args.limit]

        total = len(rows)
        print(f"📄 عدد الصفوف اللي هتتعالج: {total}")

        created, skipped, failed = 0, 0, 0

        try:
            for i, row in enumerate(rows, start=1):
                name = row["name"]
                price = row["price"]

                print(f"[{i}/{total}] {name} ...", end=" ")

                if already_exists(name):
                    print("⏭️  موجود بالفعل - skip")
                    skipped += 1
                    continue

                generated_dict = None
                db_fields = None
                db_status = "(لسه ماتحفظش)"
                last_qdrant_call.clear()

                try:
                    # الخطوة اللي بتستخدم الـ AI (نفس زر Generate في الفورم)
                    generated = generate_test(name=name)
                    generated_dict = generation_result_to_dict(generated)

                    db_fields = {
                        "laboratory_id": lab.id,
                        "name": name,
                        "price": price,
                        "description": generated.description,
                        "patient_instructions": generated.patient_instructions,
                        "duration": generated.duration,
                        "sample_type": generated.sample_type,
                        "keywords": generated.keywords,
                        "alias_name": generated.alias_name,
                    }

                    if args.dry_run:
                        db_status = "(dry-run - لسه ماتحطش في الداتابيز)"
                        # بنحسب نص الـ embedding والـ payload للعرض بس من غير ما نبعت حاجة فعلي
                        embed_text = build_test_text(name, generated.description, generated.keywords)
                        last_qdrant_call.update(
                            {
                                "embed_text": embed_text,
                                "payload": {
                                    "test_id": None,
                                    "name": name,
                                    "description": generated.description,
                                    "keywords": generated.keywords or [],
                                },
                                "status": "(dry-run - لسه محصلش إرسال)",
                            }
                        )
                        print("✅ (dry-run, لسه ماتحطش في الداتابيز)")
                        created += 1
                        write_detail_log(
                            args.log_file, i, total, name, generated_dict,
                            last_qdrant_call.get("embed_text"), db_fields, db_status,
                            last_qdrant_call.get("payload"), last_qdrant_call.get("status"),
                        )
                        time.sleep(args.sleep)
                        continue

                    tests_service = TestsService(laboratory_id=lab.id)
                    new_test, message = tests_service.create_lab_service(
                        name=name,
                        price=price,
                        description=generated.description,
                        patient_instructions=generated.patient_instructions,
                        duration=generated.duration,
                        sample_type=generated.sample_type,
                        keywords=generated.keywords,
                        alias_name=generated.alias_name,
                    )

                    if new_test:
                        print("✅ تم الإدراج")
                        db_status = "✅ تم الحفظ بنجاح"
                        created += 1
                    else:
                        print(f"⚠️ فشل: {message}")
                        db_status = f"❌ فشل: {message}"
                        log_failure(name, price, message)
                        failed += 1

                    write_detail_log(
                        args.log_file, i, total, name, generated_dict,
                        last_qdrant_call.get("embed_text"), db_fields, db_status,
                        last_qdrant_call.get("payload"), last_qdrant_call.get("status", "(لسه محصلش)"),
                    )

                except KeyboardInterrupt:
                    # نسيبها تتفلتر لبره عشان تتلقط في الـ except الخارجي وتطبع ملخص نظيف
                    raise
                except Exception as e:
                    print(f"❌ Exception: {e}")
                    log_failure(name, price, str(e))
                    write_detail_log(
                        args.log_file, i, total, name, generated_dict,
                        last_qdrant_call.get("embed_text"), db_fields, f"❌ Exception: {e}",
                        last_qdrant_call.get("payload"), last_qdrant_call.get("status", "(لسه محصلش)"),
                    )
                    failed += 1

                time.sleep(args.sleep)

        except KeyboardInterrupt:
            print("\n\n⏹️  تم إيقاف الاسكريبت يدويًا (Ctrl+C).")
            print("   اللي اتعمله لحد دلوقتي محفوظ في الداتابيز - شغّل نفس الأمر تاني وهو هيكمل من نفس النقطة.")

        print("\n----------------------------------------")
        print(f"تم:      {created}")
        print(f"اتخطى:   {skipped}")
        print(f"فشل:     {failed}")
        if failed:
            print(f"راجع التفاصيل في: {FAILED_LOG_PATH}")
        print(f"تفاصيل كل تحليل (التوليد + الـ embedding + الداتابيز + Qdrant) في: {args.log_file}")
        print("----------------------------------------")


if __name__ == "__main__":
    main()