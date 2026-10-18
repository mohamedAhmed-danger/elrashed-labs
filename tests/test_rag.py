"""
test_search_queries.py

سكريبت لتجربة search_manager.run_search() على مجموعة كبيرة من الكويريز
المتنوعة (اسم صحيح - اختصار - غلطة إملائية - عربي - وصف بالمعنى من غير
اسم التحليل نفسه) عشان تتأكد إن الـ fuzzy والـ semantic شغالين صح مع بعض.

تشغيل:
    python test_search_queries.py
    python test_search_queries.py --min-score 0.5   (تعرض بس النتايج اللي score أعلى من كده)
"""

import argparse

from app import app
from schemas.intent import RefinedQuery
from search.search_manager import run_search


# --------------------------------------------------------------------------
# 35 كويري تجريبية متنوعة
# --------------------------------------------------------------------------
TEST_CASES = [
    # ── اسم صحيح ومباشر ──────────────────────────────────────────────
    RefinedQuery(query="CBC", aliases=["Complete Blood Count", "صورة دم كاملة"],
                 keywords=["blood", "hemoglobin", "wbc", "rbc"],
                 description="تحليل صورة دم كاملة"),

    RefinedQuery(query="Liver Function Test", aliases=["LFT", "وظائف الكبد"],
                 keywords=["liver", "ast", "alt", "bilirubin"],
                 description="تحليل وظائف الكبد"),

    RefinedQuery(query="Kidney Function Test", aliases=["KFT", "وظائف الكلى"],
                 keywords=["kidney", "creatinine", "urea"],
                 description="تحليل وظائف الكلى"),

    RefinedQuery(query="Fasting Blood Sugar", aliases=["FBS", "سكر صائم"],
                 keywords=["glucose", "sugar", "diabetes"],
                 description="تحليل سكر صائم"),

    RefinedQuery(query="HbA1c", aliases=["Glycated Hemoglobin", "السكر التراكمي"],
                 keywords=["diabetes", "average blood sugar"],
                 description="تحليل السكر التراكمي"),

    RefinedQuery(query="Lipid Profile", aliases=["دهون الدم", "كوليسترول"],
                 keywords=["cholesterol", "triglycerides", "hdl", "ldl"],
                 description="تحليل دهون الدم"),

    RefinedQuery(query="TSH", aliases=["Thyroid Stimulating Hormone", "الغدة الدرقية"],
                 keywords=["thyroid", "hormone"],
                 description="تحليل هرمون الغدة الدرقية"),

    RefinedQuery(query="Vitamin D", aliases=["فيتامين د", "25-OH Vitamin D"],
                 keywords=["vitamin", "bone health"],
                 description="تحليل فيتامين د"),

    RefinedQuery(query="Urine Analysis", aliases=["تحليل بول", "Urinalysis"],
                 keywords=["urine", "kidney", "infection"],
                 description="تحليل بول كامل"),

    RefinedQuery(query="Pregnancy Test", aliases=["تحليل حمل", "Beta HCG"],
                 keywords=["pregnancy", "hcg"],
                 description="تحليل حمل"),

    RefinedQuery(query="PSA", aliases=["Prostate Specific Antigen", "البروستاتا"],
                 keywords=["prostate", "cancer marker"],
                 description="تحليل البروستاتا"),

    RefinedQuery(query="COVID PCR", aliases=["كورونا", "PCR Test"],
                 keywords=["covid", "coronavirus", "pcr"],
                 description="تحليل كورونا PCR"),

    RefinedQuery(query="Stool Analysis", aliases=["تحليل براز", "Stool Exam"],
                 keywords=["stool", "parasites", "digestive"],
                 description="تحليل براز"),

    RefinedQuery(query="ESR", aliases=["Erythrocyte Sedimentation Rate", "سرعة الترسيب"],
                 keywords=["inflammation", "sedimentation"],
                 description="تحليل سرعة الترسيب"),

    RefinedQuery(query="CRP", aliases=["C-Reactive Protein"],
                 keywords=["inflammation", "infection marker"],
                 description="تحليل بروتين سي التفاعلي"),

    # ── اختصارات وأسامي بديلة (اختبار fuzzy/alias) ─────────────────
    RefinedQuery(query="سي بي سي", aliases=["CBC", "عد دم كامل"], keywords=["cbc", "blood count"],
                 description="اسم CBC بالعربي منطوق"),

    RefinedQuery(query="LFT", aliases=["Liver Function Tests", "وظائف كبد"], keywords=["lft", "liver"],
                 description="اختصار وظائف الكبد بس"),

    RefinedQuery(query="سكر", aliases=["Glucose", "سكر صائم"], keywords=["glucose", "sugar"],
                 description="كلمة سكر لوحدها، محتاج يلاقي فاستنج بلود شوجر"),

    RefinedQuery(query="تحليل الكبد", aliases=["LFT", "وظائف الكبد"], keywords=["lft", "liver function"],
                 description="صيغة عربية بديلة لوظائف الكبد"),

    RefinedQuery(query="تحليل الكلى", aliases=["KFT", "وظائف الكلى"], keywords=["kft", "kidney function"],
                 description="صيغة عربية بديلة لوظائف الكلى"),

    # ── غلطات إملائية (اختبار قوة الـ fuzzy) ────────────────────────
    RefinedQuery(query="CBS", aliases=["CBC", "عد دم"], keywords=["cbc", "blood count"],
                 description="غلطة إملائية مقصودة في CBC"),

    RefinedQuery(query="Fasting Blod Sugar", aliases=["FBS", "سكر صائم"], keywords=["glucose", "sugar"],
                 description="غلطة إملائية مقصودة في Blood"),

    RefinedQuery(query="Tyroid test", aliases=["TSH", "غدة درقية"], keywords=["tsh", "thyroid"],
                 description="غلطة إملائية مقصودة في Thyroid"),

    RefinedQuery(query="Vitmin D", aliases=["Vitamin D", "فيتامين د"], keywords=["vitamin", "calciferol"],
                 description="غلطة إملائية مقصودة في Vitamin"),

    RefinedQuery(query="creatinin test", aliases=["Creatinine", "كراتينين"], keywords=["creatinine", "kidney"],
                 description="غلطة إملائية في Creatinine"),

    # ── وصف بالمعنى من غير اسم التحليل (اختبار semantic search) ──────
    RefinedQuery(query="عايز أعرف لو عندي أنيميا أو نقص دم", aliases=["CBC", "أنيميا"],
                 keywords=["anemia", "hemoglobin"],
                 description="سؤال بالمعنى محتاج يوصل لتحليل CBC عن طريق semantic"),

    RefinedQuery(query="هل الكلى بتاعتي شغالة كويس؟", aliases=["KFT", "وظائف كلى"], keywords=["kidney", "renal"],
                 description="سؤال بالمعنى محتاج يوصل لوظائف الكلى"),

    RefinedQuery(query="حاسس إني تعبان وعايز أطمن على الكبد بتاعي", aliases=["LFT", "وظائف كبد"],
                 keywords=["liver", "hepatic"], description="سؤال بالمعنى محتاج يوصل لوظائف الكبد"),

    RefinedQuery(query="عندي عطش زيادة ونزول وزن، ممكن يكون سكر؟", aliases=["FBS", "سكر"],
                 keywords=["diabetes", "glucose"],
                 description="أعراض سكري، محتاج يوصل لتحليل السكر"),

    RefinedQuery(query="عايزة أعرف لو حامل ولا لأ", aliases=["Pregnancy Test", "تحليل حمل"], keywords=["pregnancy", "hcg"],
                 description="سؤال بالمعنى لازم يوصل لتحليل الحمل"),

    RefinedQuery(query="بولي لونه غريب وريحته بايظة", aliases=["Urinalysis", "تحليل بول"], keywords=["urine", "urinalysis"],
                 description="أعراض محتاجة توصل لتحليل البول"),

    # ── كويري فاضي أو ضعيف (اختبار edge cases) ───────────────────────
    RefinedQuery(query=" ", aliases=["empty"], keywords=["empty", "test"],
                 description="كويري فاضي، المفروض يرجع نتيجة فاضية من غير error"),

    RefinedQuery(query="عايز تحليل", aliases=["General Test", "تحليل عام"], keywords=["test", "general"],
                 description="كويري عام جدًا، مش واضح المطلوب"),

    RefinedQuery(query="xyz123nonexistent", aliases=["Unknown", "مجهول"], keywords=["unknown", "nonexistent"],
                 description="اسم تحليل مش موجود خالص، لازم يرجع نتايج ضعيفة أو فاضية"),

    # ── keywords بس من غير query واضح ────────────────────────────────
    RefinedQuery(query="فحص عام", aliases=["Lipid Profile", "دهون"], keywords=["cholesterol", "triglycerides"],
                 description="كويري عام بس الكلمات المفتاحية بتحدد المطلوب (دهون)"),

    RefinedQuery(query="فحص هرمونات", aliases=["TSH", "غدة"], keywords=["thyroid", "tsh"],
                 description="كويري عام بس الكلمات المفتاحية بتحدد الغدة الدرقية"),
]


def run_all(min_score: float = 0.0):

    with app.app_context():

        print(f"عدد الكويريز اللي هيتم اختبارها: {len(TEST_CASES)}\n")
        print("=" * 90)

        for i, refined_query in enumerate(TEST_CASES, start=1):

            result = run_search([refined_query])

            print(f"\n[{i}/{len(TEST_CASES)}] 🔍 الوصف: {refined_query.description}")
            print(f"     الكويري: \"{refined_query.query}\"")
            if refined_query.aliases:
                print(f"     الأسامي البديلة: {refined_query.aliases}")
            if refined_query.keywords:
                print(f"     الكلمات المفتاحية: {refined_query.keywords}")

            filtered = [r for r in result["results"] if r.score >= min_score]

            if not filtered:
                print("     ❌ مفيش نتايج (أو أقل من الحد الأدنى للـ score)")
                continue

            print(f"     ✅ أعلى score: {result['top_score']}")
            for rank, res in enumerate(filtered[:5], start=1):
                print(f"        {rank}. {res.name}  (id={res.id}, score={res.score}, source={res.source})")

        print("\n" + "=" * 90)
        print("خلصت كل الكويريز.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=float, default=0.0,
                         help="متعرضش نتايج أقل من القيمة دي (مثلاً 0.5)")
    args = parser.parse_args()

    run_all(min_score=args.min_score)