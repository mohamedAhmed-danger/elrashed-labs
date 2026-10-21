"""
tools/seed_laboratories_and_users.py

اسكريبت لتجهيز المعامل الثلاثة ومستخدميها وشعاراتها في قاعدة البيانات على سيرفر لينكس (Linux Server).
ينشئ المعامل الثلاثة ومستخدم لكل معمل + مستخدم الأدمن العام إذا لم يكونوا موجودين بالفعل.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from app import app
except ImportError:
    from app import create_app
    app = create_app()

from models.models import db, Laboratory, User


LABORATORIES_DATA = [
    {
        "name": "معمل الخبراء للتحاليل الطبية",
        "location": "الفرع الرئيسي - مصر",
        "description": "معمل تشخيصي متكامل يقدم أدق الفحوصات والتحاليل الطبية الشاملة بأحدث الأجهزة.",
        "logo_path": "images/elkhobra.png",
        "support_phone": "01000000001",
        "notification_email": "info@elkhobra.com",
        "username": "elkhobra_user",
        "password": "password123",
    },
    {
        "name": "معامل الراشد – مختبر الأمل",
        "location": "الفرع الرئيسي - مصر",
        "description": "معامل الراشد ومختبر الأمل للتحاليل الطبية المتقدمة والتشخيص الدقيق.",
        "logo_path": "images/alrashed_alamal.png",
        "support_phone": "01000000002",
        "notification_email": "info@elrashed-alamal.com",
        "username": "elrashed_user",
        "password": "password123",
    },
    {
        "name": "معمل نجمة الخبر (Al-Khabar Star)",
        "location": "الفرع الرئيسي",
        "description": "فحوصات طبية متميزة وتحاليل دورية بجودة ودقة عالية.",
        "logo_path": "images/alkhabar_star.png",
        "support_phone": "01000000003",
        "notification_email": "info@alkhabarstar.com",
        "username": "alkhabar_user",
        "password": "password123",
    },
]


def seed_laboratories_and_users():
    with app.app_context():
        print("🚀 بدء تهيئة المعامل والمستخدمين...")

        # 1. إنشاء حساب Admin عام إذا لم يكن موجوداً
        admin = User.query.filter_by(role="admin").first()
        if not admin:
            admin = User(
                name="admin",
                password="admin123",
                role="admin",
                laboratory_id=None
            )
            db.session.add(admin)
            db.session.commit()
            print("👑 تم إنشاء حساب المدير العام (Admin): username: admin / password: AdminPassword123!")
        else:
            print(f"ℹ️  حساب المدير العام موجود بالفعل: {admin.name}")

        # 2. إنشاء المعامل الثلاثة ومستخدميها
        for item in LABORATORIES_DATA:
            lab = Laboratory.query.filter_by(name=item["name"]).first()
            if not lab:
                lab = Laboratory(
                    name=item["name"],
                    location=item["location"],
                    description=item["description"],
                    logo_path=item["logo_path"],
                    support_phone=item["support_phone"],
                    notification_email=item["notification_email"],
                )
                db.session.add(lab)
                db.session.commit()
                print(f"🏥 تم إنشاء المعمل: {lab.name} (id={lab.id})")
            else:
                # تحديث مسار اللوجو إذا كان ناقصاً
                if not lab.logo_path or lab.logo_path != item["logo_path"]:
                    lab.logo_path = item["logo_path"]
                    db.session.commit()
                print(f"ℹ️  المعمل موجود بالفعل: {lab.name} (id={lab.id})")

            # التحقق من مستخدم المعمل
            user = User.query.filter_by(name=item["username"]).first()
            if not user:
                user = User(
                    name=item["username"],
                    password=item["password"],
                    role="lab_user",
                    laboratory_id=lab.id
                )
                db.session.add(user)
                db.session.commit()
                print(f"   👤 تم إنشاء المستخدم للمعمل: username: {user.name} (lab_id={lab.id})")
            else:
                if user.laboratory_id != lab.id:
                    user.laboratory_id = lab.id
                    db.session.commit()
                print(f"   ℹ️  المستخدم موجود بالفعل: {user.name}")

        print("\n🎉 اكتملت عملية التهيئة بنجاح على قاعدة البيانات!")


if __name__ == "__main__":
    seed_laboratories_and_users()
