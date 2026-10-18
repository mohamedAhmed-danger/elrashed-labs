import os
import sys
import json

# التأكد من مسار المشروع
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app
from graph.graph import get_agent_graph


def print_box(step_title, content, color="36", icon="🔍"):
    """دالة لتنسيق الطباعة في التيرمينال بألوان ومربعات واضحة"""
    print(f"\033[{color}m" + "=" * 90)
    print(f"{icon} {step_title}")
    print("=" * 90 + "\033[0m")

    if isinstance(content, (dict, list)):
        print(json.dumps(content, ensure_ascii=False, indent=2))
    else:
        print(content if content else "( فارغ / لا يوجد بيانات )")
    print("\n")


def get_valid_page():
    """
    بيجيب (page_id, platform_id) حقيقيين وموجودين فعلاً في جدول pages،
    عشان ميحصلش IntegrityError لما الـ graph يحاول يعمل/يجيب client مرتبط بيهم.

    ملاحظة: السطر اللي بيعمل import لـ db لازم يتظبط حسب مكان تعريفه
    الفعلي عندك في المشروع (ممكن يكون from app import db, أو من extensions.py، إلخ).
    """
    try:
        from app import db  # <-- عدّل ده لو الـ db بتاعتك متعرفة في مكان تاني
    except ImportError:
        print("❌ مقدرتش أعمل import لـ db من app. عدّل السطر ده في get_valid_page() "
              "بمكان تعريف db الصحيح عندك.")
        sys.exit(1)

    from sqlalchemy import text

    with app.app_context():
        row = db.session.execute(
            text("SELECT page_id, platform_id FROM pages LIMIT 1")
        ).fetchone()

    if not row:
        print("❌ مفيش ولا صف واحد في جدول pages. لازم تعمل insert لصفحة حقيقية "
              "(page_id + platform_id) قبل ما تشغل التيست، عشان جدول clients "
              "مربوط بيهم بـ Foreign Key ومش هيقبل قيم وهمية.")
        sys.exit(1)

    return row[0], row[1]


def run_interactive_test():
    # بدل الـ hardcoded values، بنجيب page/platform حقيقيين من الداتابيز
    page_id, platform_id = get_valid_page()
    sender_id = "test_user_tracer"

    print("🚀 [PIPELINE TRACER] Initialization Complete.")
    print(f"📌 هيتم التست على page_id='{page_id}' / platform_id='{platform_id}'")
    print("💡 اكتب رسالتك لمراقبة دورة حياتها بالكامل. اكتب 'exit' أو 'quit' للخروج.\n")

    graph = get_agent_graph()

    current_summary = ""
    current_last_bot_message = ""

    with app.app_context():
        while True:
            try:
                user_input = input("\033[1;32m👤 [المريض]: \033[0m").strip()
                if user_input.lower() in ["exit", "quit", "خروج"]:
                    print("👋 مع السلامة! تم إنهاء المراقبة.")
                    break

                if not user_input:
                    continue

                state = {
                    "user_message": user_input,
                    "platform_id": platform_id,
                    "page_id": page_id,
                    "sender_id": sender_id,
                    "summary": current_summary,
                    "last_bot_message": current_last_bot_message,
                }

                print("\n⏳ جاري تتبع مسار الرسالة عبر الـ Pipeline...")

                final_state = graph.invoke(state)

                current_summary = final_state.get("summary", current_summary)
                current_last_bot_message = final_state.get("response", "")

                trace = final_state.get("pipeline_trace") or {}

                # --- مسح الشاشة للتركيز على مسار الرسالة الحالية ---
                #os.system('cls' if os.name == 'nt' else 'clear')
                print(f"🎯 \033[1;37mالرسالة المستهدفة:\033[0m {user_input}\n")

                # 1. INTENT & REFINED QUERIES
                refined = [
                    r.model_dump() if hasattr(r, "model_dump") else r
                    for r in final_state.get("refined_queries", [])
                ]
                print_box("STEP 1: INTENT & QUERY PROCESSING", {
                    "Intent": final_state.get("intent"),
                    "Top Score": final_state.get("top_score", 0.0),
                    "Refined Queries": refined
                }, "33", "🧠")

                # 2. SEARCH ENGINE (INPUTS & OUTPUTS)
                print_box("STEP 2: SEARCH ENGINE (Fuzzy vs Semantic)", {
                    "A. Fuzzy Pipeline": {
                        "INPUTS": trace.get("fuzzy_inputs", []),
                        "OUTPUTS": trace.get("fuzzy_raw", [])
                    },
                    "B. Semantic Pipeline": {
                        "INPUTS": trace.get("semantic_inputs", []),
                        "OUTPUTS": trace.get("semantic_raw", [])
                    }
                }, "35", "⚙️")

                # 3. MERGE & RANKING
                print_box("STEP 3: MERGER & RANKING (Applying BOOST)", {
                    "Merged Results (Sorted)": trace.get("merged_ranked", [])
                }, "31", "🏆")

                # 4. DATABASE FETCH
                print_box("STEP 4: DATABASE RETRIEVAL (Fetching Full Lab Details)", {
                    "Pulled from DB": trace.get("db_retrieved_labs", [])
                }, "34", "🗄️")

                # 5. RAG CONTEXT
                print_box("STEP 5: FINAL BUILT RAG CONTEXT (What LLM sees)",
                          final_state.get("rag_context"), "36", "📄")

                # 6. MEMORY, REASONING & FINAL RESPONSE
                print_box("STEP 6: MEMORY, REASONING & FINAL OUTPUT", {
                    "Previous Summary": state["summary"],
                    "Updated Summary": current_summary,
                    "Response to Patient": current_last_bot_message
                }, "32", "💬")

                print("\n💡 الـ Flow انتهى! تقدر تكتب رسالة تانية (تكملة للمحادثة) أو تكتب exit للخروج.\n")

            except KeyboardInterrupt:
                print("\n👋 تم إيقاف الاختبار بواسطة المستخدم.")
                break
            except Exception as e:
                print(f"\n❌ [ERROR] حدث خطأ أثناء التنفيذ: {e}")
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    run_interactive_test()