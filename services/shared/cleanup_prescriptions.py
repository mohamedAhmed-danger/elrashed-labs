"""
Cleanup job لصور الروشتات المرفوعة (Inquiry.prescription_img).

الاستخدام:
    python -m jobs.cleanup_prescriptions

يفضل تشغيله من cron مرة يوميًا، مش من جوه Flask/Gunicorn worker:
    0 3 * * * docker exec your_container python -m jobs.cleanup_prescriptions
"""

import os
from datetime import datetime, timezone, timedelta

from app import app
from models.models import db, Inquiry


DEFAULT_MIN_AGE_HOURS_FOR_EMERGENCY = 48


def _get_config(app):
    return {
        "age_limit_days": app.config.get("PRESCRIPTION_AGE_LIMIT_DAYS", 8),
        "quota_mb": app.config.get("PRESCRIPTION_FOLDER_QUOTA_MB", 5000),
        "target_mb": app.config.get("PRESCRIPTION_FOLDER_TARGET_MB", 4000),
        "batch_size": app.config.get("CLEANUP_BATCH_SIZE", 200),
        "min_age_hours_emergency": app.config.get(
            "PRESCRIPTION_MIN_AGE_HOURS_EMERGENCY", DEFAULT_MIN_AGE_HOURS_FOR_EMERGENCY
        ),
    }


def _safe_file_path(app, filename):
    """
    بيتأكد إن الملف اللي هنمسحه فعلاً جوه UPLOAD_FOLDER، ومش عنده أي path
    traversal (زي "../../../app.py" أو path مطلق). لو الاسم فيه أي شبهة،
    بيرجع None ومنمسحش حاجة.
    """
    if not filename:
        return None

    upload_folder = os.path.abspath(app.config["UPLOAD_FOLDER"])

    # نشيل أي directory components، نسيب اسم الملف بس (بيقفل ثغرة "../")
    safe_name = os.path.basename(filename)

    candidate_path = os.path.abspath(os.path.join(upload_folder, safe_name))

    # اتأكد إن الملف النهائي لسه جوه upload_folder فعلاً بعد الـ resolve
    if not candidate_path.startswith(upload_folder + os.sep):
        return None

    return candidate_path


def _delete_image_file(app, inquiry):
    """يمسح الملف الفعلي من الـ disk لو موجود وآمن. بيرجع حجم الملف اللي اتمسح (MB) أو None لو فشل."""
    if not inquiry.prescription_img:
        return 0.0

    file_path = _safe_file_path(app, inquiry.prescription_img)

    if file_path is None:
        app.logger.error(
            f"Unsafe/suspicious prescription_img for inquiry {inquiry.id}: "
            f"{inquiry.prescription_img!r} - skipping deletion."
        )
        return None

    try:
        if os.path.exists(file_path):
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            os.remove(file_path)
            return size_mb
        return 0.0
    except OSError as e:
        app.logger.error(f"Failed to remove file for inquiry {inquiry.id}: {e}")
        return None


def _mark_deleted(app, inquiry, reason):
    """
    يمسح الصورة، يحدث الـ audit fields، ويعمل commit فوري لهذه الريكورد لوحدها.
    بيرجع حجم الملف اللي اتمسح (MB) لو نجح، أو None لو فشل.
    """
    freed_mb = _delete_image_file(app, inquiry)
    if freed_mb is None:
        return None

    inquiry.prescription_img = None
    inquiry.deleted_at = datetime.now(timezone.utc)
    inquiry.deletion_reason = reason

    try:
        db.session.commit()
        return freed_mb
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to commit deletion for inquiry {inquiry.id}: {e}")
        return None


def cleanup_expired_by_age(app, cfg):
    """
    المسار العادي: امسح أي صورة عدت X يوم، بس لو الـ OCR فعلاً استخرج منها
    بيانات (ocr_extracted_text موجود). أي حاجة الـ OCR لسه ما عالجهاش
    بنسيبها زي ما هي مهما كبر عمرها - عشان منمسحش صورة لسه محتاجينها.
    """
    expiration_date = datetime.now(timezone.utc) - timedelta(days=cfg["age_limit_days"])
    total_deleted = 0

    while True:
        batch = (
            Inquiry.query.filter(
                Inquiry.created_at < expiration_date,
                Inquiry.prescription_img.isnot(None),
                Inquiry.ocr_extracted_text.isnot(None),
            )
            .limit(cfg["batch_size"])
            .all()
        )

        if not batch:
            break

        for inquiry in batch:
            if _mark_deleted(app, inquiry, reason="age_expired") is not None:
                total_deleted += 1

    app.logger.info(f"[cleanup] Age-based cleanup done. Deleted {total_deleted} images.")
    return total_deleted


def _get_folder_size_mb(path):
    """بيتحسب مرة واحدة بس في بداية الـ emergency cleanup، مش بعد كل حذف."""
    total_bytes = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total_bytes += os.path.getsize(fp)
    return total_bytes / (1024 * 1024)


def cleanup_emergency_by_folder_quota(app, cfg):
    """
    Safety net: لو فولدر الروشتات نفسه (مش الـ disk كله) وصل لحجم معين،
    امسح أقدم الصور (اللي الـ OCR خلص معالجتها بس) حتى لو لسه ماكملتش X يوم.

    التحسين هنا: بنحسب حجم الفولدر مرة واحدة بس في الأول، وبعد كل حذف
    بنطرح حجم الملف اللي اتمسح من الرقم في الميموري - مش بنعيد مسح
    الفولدر كله تاني (ده كان أكبر مشكلة أداء في النسخة اللي فاتت).
    """
    upload_folder = app.config["UPLOAD_FOLDER"]
    current_size_mb = _get_folder_size_mb(upload_folder)  # مرة واحدة بس

    if current_size_mb < cfg["quota_mb"]:
        return 0

    app.logger.warning(
        f"[cleanup] Prescriptions folder at {current_size_mb:.0f}MB "
        f"(quota {cfg['quota_mb']}MB) - starting emergency cleanup"
    )

    total_deleted = 0
    min_age_cutoff = datetime.now(timezone.utc) - timedelta(
        hours=cfg["min_age_hours_emergency"]
    )

    while current_size_mb >= cfg["target_mb"]:
        batch = (
            Inquiry.query.filter(
                Inquiry.prescription_img.isnot(None),
                Inquiry.ocr_extracted_text.isnot(None),
                Inquiry.created_at < min_age_cutoff,  # منمسحش صور "سخنة" حتى في emergency
            )
            .order_by(Inquiry.created_at.asc())  # الأقدم الأول
            .limit(cfg["batch_size"])
            .all()
        )

        if not batch:
            app.logger.warning(
                "[cleanup] No more deletable images (respecting min-age), "
                "but folder still over quota."
            )
            break

        for inquiry in batch:
            freed_mb = _mark_deleted(app, inquiry, reason="folder_quota_emergency")
            if freed_mb is not None:
                total_deleted += 1
                current_size_mb -= freed_mb  # تحديث في الميموري، من غير إعادة حساب

            if current_size_mb < cfg["target_mb"]:
                break

    app.logger.info(
        f"[cleanup] Emergency cleanup done. Deleted {total_deleted} images. "
        f"Folder size now ~{current_size_mb:.0f}MB."
    )
    return total_deleted


def run():
    with app.app_context():
        try:
            # UPLOAD_FOLDER مش متسجلة في config الـ app الأساسي (الـ app بيستخدم
            # project_dir/static/uploads مباشرة جوه message_processor.py من غير
            # ما يمر على app.config). فبنحطها هنا يدوي من الـ environment variable
            # عشان نفس القيمة تتستخدم في الـ job من غير ما نلمس باقي الكود.
            app.config["UPLOAD_FOLDER"] = os.environ.get(
                "UPLOAD_FOLDER", "/app/static/uploads"
            )

            cfg = _get_config(app)
            app.logger.info("[cleanup] Starting prescription cleanup job.")
            app.logger.info(f"[cleanup] Using UPLOAD_FOLDER={app.config['UPLOAD_FOLDER']}")

            cleanup_expired_by_age(app, cfg)
            cleanup_emergency_by_folder_quota(app, cfg)

            app.logger.info("[cleanup] Prescription cleanup job finished.")
        except Exception as e:
            app.logger.exception("❌ [cleanup] Prescription cleanup job failed: %s", e)
            from notification_center import send_production_alert
            send_production_alert(
                subject="Prescription Cleanup Job Failure",
                body_or_error=e,
            )


if __name__ == "__main__":
    run()