import logging

logger = logging.getLogger(__name__)

# أسعار التوكن — لو اتغيرت من الـ provider، هنا بس المكان اللي تعدل فيه
OCR_INPUT_COST_PER_TOKEN   = 0.30 / 1_000_000
OCR_OUTPUT_COST_PER_TOKEN  = 2.5 / 1_000_000

FLASH_INPUT_COST_PER_TOKEN  = 0.25 / 1_000_000
FLASH_OUTPUT_COST_PER_TOKEN = 1.5  / 1_000_000


def calc_total_usage(result: dict, ocr_usage: dict = None) -> dict:
    """يجمع استهلاك التوكنز من كل الـ nodes (intent, booking, complaint...)
    ويحسب التكلفة الإجمالية بالدولار.

    Returns dict بالمفاتيح:
        breakdown: تفاصيل كل node على حدة (input/output/total/cost_usd)
        total_input, total_output, total_tokens: الإجمالي الكلي
        total_cost_usd, total_cost_cents: التكلفة الإجمالية
        req_per_dollar: تقدير تقريبي لعدد الـ requests لكل دولار (0 لو التكلفة صفر)
    """

    nodes = [
        ("ocr_vision_usage", ocr_usage),
        ("intent_usage", result.get("intent_usage")),
        ("lab_info_usage", result.get("lab_info_usage")),
        ("booking_usage", result.get("booking_usage")),
        ("complaint_usage", result.get("complaint_usage")),
        ("direct_usage", result.get("direct_usage")),
        ("inquiry_usage", result.get("inquiry_usage")),
    ]

    total_input_tokens = total_output_tokens = total_tokens = 0
    total_cost_usd = 0.0
    breakdown = {}

    for node_key, node_usage in nodes:
        if not node_usage:
            continue

        try:
            input_tokens  = int(node_usage.get("input_tokens", 0) or 0)
            output_tokens = int(node_usage.get("output_tokens", 0) or 0)
            node_total_tokens = int(
                node_usage.get("total_tokens", 0) or (input_tokens + output_tokens)
            )
        except (TypeError, ValueError):
            logger.exception("قيم توكن غير صالحة في node: %s", node_key)
            continue

        if not (input_tokens or output_tokens or node_total_tokens):
            continue

        if node_key == "ocr_vision_usage":
            in_rate, out_rate = OCR_INPUT_COST_PER_TOKEN, OCR_OUTPUT_COST_PER_TOKEN
        else:
            in_rate, out_rate = FLASH_INPUT_COST_PER_TOKEN, FLASH_OUTPUT_COST_PER_TOKEN

        node_cost = (input_tokens * in_rate) + (output_tokens * out_rate)

        breakdown[node_key] = {
            "input": input_tokens,
            "output": output_tokens,
            "total": node_total_tokens,
            "cost_usd": node_cost,
        }

        total_input_tokens  += input_tokens
        total_output_tokens += output_tokens
        total_tokens        += node_total_tokens
        total_cost_usd      += node_cost

    total_cost_cents = total_cost_usd * 100
    req_per_dollar = int(1.0 / total_cost_usd) if total_cost_usd > 0 else 0

    return {
        "breakdown":        breakdown,
        "total_input":      total_input_tokens,
        "total_output":     total_output_tokens,
        "total_tokens":     total_tokens,
        "total_cost_usd":   total_cost_usd,
        "total_cost_cents": total_cost_cents,
        "req_per_dollar":   req_per_dollar,
    }


def check_and_alert_high_token_usage(usage: dict, context: dict = None, threshold: int = 40000) -> bool:
    """
    Checks if total LLM tokens for a request/session exceed the specified threshold (default: 40,000).
    If threshold is reached or exceeded, sends a production email alert via NotificationCenter.
    """
    if not usage or not isinstance(usage, dict):
        return False

    total_tokens = usage.get("total_tokens", 0)
    if total_tokens >= threshold:
        try:
            from notification_center import send_production_alert
            alert_context = {
                "total_tokens": f"{total_tokens:,}",
                "total_input": f"{usage.get('total_input', 0):,}",
                "total_output": f"{usage.get('total_output', 0):,}",
                "estimated_cost_usd": f"${usage.get('total_cost_usd', 0.0):.4f}",
                "token_threshold": f"{threshold:,}",
            }
            if context and isinstance(context, dict):
                alert_context.update(context)

            send_production_alert(
                subject=f"⚠️ High LLM Token Consumption Alert ({total_tokens:,} Tokens)",
                body_or_error=f"A request execution consumed {total_tokens:,} LLM tokens, exceeding the alert threshold of {threshold:,} tokens.",
                context=alert_context,
                level="WARNING",
            )
            logger.warning("[HighTokenAlert] Exceeded threshold (%d >= %d) | Alert sent", total_tokens, threshold)
            return True
        except Exception as err:
            logger.exception("[HighTokenAlert] Failed to send high token alert: %s", err)
            return False
    return False