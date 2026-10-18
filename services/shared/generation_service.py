import logging

from llm.llm import get_gemini
from schemas.generation import TestGenerationResult

logger = logging.getLogger(__name__)


def _generate(prompt: str) -> TestGenerationResult:
    structured_llm = get_gemini().with_structured_output(TestGenerationResult)
    try:
        return structured_llm.invoke(prompt)
    except Exception:
        logger.exception("Test knowledge generation failed")
        raise


def generate_test(
    name: str,
    description: str | None = None,
    instructions: str | None = None,
) -> TestGenerationResult:
    """يولّد بيانات خدمة تحليل جديدة من الاسم (والوصف/التعليمات لو موجودين)."""

    prompt = f"""
You are an expert laboratory services assistant.

Generate structured information for the following laboratory service.

Laboratory service name:
{name}

Existing description:
{description or "Not provided"}

Existing instructions:
{instructions or "Not provided"}

Your task:
1. Generate a clear and medically appropriate description (in English).
2. Generate appropriate patient/sample instructions (in Arabic).
3. Generate relevant search keywords (in English).
4. Generate alternative names and aliases (in Arabic and English).
5. Determine the precise sample type (in Arabic).
6. Estimate the duration (in hours).

--- STRICT GUIDELINES ---

"aliases":
- An array of real and commonly used alternative names and abbreviations.
- These may include:
  - Official abbreviations (e.g., "AST", "CBC", "ALT").
  - Alternative clinical names (e.g., "Serum Glutamic-Oxaloacetic Transaminase").
  - Commonly searched Arabic translations (e.g., "إنزيم الكبد AST").
- Never invent aliases. If no additional aliases are commonly known, return an empty array [].

"sample_type":
- A single, short, clear value for the sample required in Arabic ONLY (e.g., دم, سيرم, بول, براز, مسحة, بلازما).

"patient_instructions":
- Provide clear, direct, and simple instructions for the patient (in Arabic).
- If fasting is required, specify the exact number of hours accurately (e.g., 8-10 hours for Fasting Blood Sugar, 12-14 hours for Lipid Profile).
- If NO special preparation is required, explicitly state: "لا توجد تحضيرات خاصة".
- Keep it concise and easy for a layperson to understand.

"keywords":
- Include meaningful search keywords related to this test (in lowercase).
- Keywords may include: Substance measured, Organ or body system, Disease names, Medical terminology.
- Do NOT include generic words such as: (تحليل, فحص, معمل, تحاليل طبية).
- Do not invent keywords simply to increase their number.

"duration":
- Estimate the typical turnaround time for this test result in hours (as an integer).
- If the test is a routine chemistry/hematology test, it is usually 24 hours. Cultures may take 72. If unsure, default to 24.

GENERAL RULES:
- If an existing description or instructions are provided, improve them when necessary, preserve their original meaning, and do not remove useful information.
- Generate knowledge only if you are reasonably confident.
- Never fabricate medical facts. Do not invent highly specific medical facts that cannot reasonably be inferred from the service name.
- Make the output strictly useful for semantic search and retrieval.
"""

    return _generate(prompt)


def regenerate_test(
    name: str,
    previous_output: TestGenerationResult,
) -> TestGenerationResult:
    """يولّد نسخة بديلة من بيانات التحليل بناءً على النسخة السابقة."""

    prompt = f"""
You are an expert laboratory services assistant.

Generate a NEW alternative version for this laboratory service.

Laboratory service name:
{name}

Previous generated version:

Description:
{previous_output.description}

Instructions:
{previous_output.patient_instructions or previous_output.instructions}

Keywords:
{", ".join(previous_output.keywords) if previous_output.keywords else "None"}

Aliases:
{", ".join(previous_output.alias_name or previous_output.aliases) if (previous_output.alias_name or previous_output.aliases) else "None"}

Duration:
{previous_output.duration}

Sample Type:
{previous_output.sample_type}

Your task:
Generate a meaningfully different alternative version.

Requirements:
1. Keep the laboratory service medically relevant and accurate.
2. Do not simply repeat the previous version. Improve or vary the wording naturally (in Arabic).
3. Generate alternative relevant keywords (in English).
4. Generate alternative aliases when appropriate (in Arabic and English).
5. Keep medically important information accurate. Do not invent unsupported medical facts.

--- STRICT GUIDELINES ---

"aliases":
- An array of real and commonly used alternative names and abbreviations.
- Never invent aliases. If no additional aliases are commonly known, return an empty array [].

"sample_type":
- A single, short, clear value for the sample required in Arabic ONLY (e.g., دم, سيرم, بول, براز, مسحة, بلازما). Ensure it is medically correct for this test.

"patient_instructions":
- Provide clear, direct, and simple instructions for the patient (in Arabic).
- If fasting is required, specify the exact number of hours accurately.
- If NO special preparation is required, explicitly state: "لا توجد تحضيرات خاصة".

"keywords":
- Include meaningful search keywords (lowercase) like substance, organ, or disease names.
- Do NOT include generic words such as: (تحليل, فحص, معمل, تحاليل طبية).

"duration":
- Estimate the typical turnaround time in hours (as an integer). Routine is usually 24, cultures 72. Default to 24 if unsure.

GENERAL RULES:
- Make the output strictly useful for semantic search and retrieval.
- Generate knowledge only if you are reasonably confident. Never fabricate medical facts.
"""

    return _generate(prompt)