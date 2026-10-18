"""
utils/trace_logger.py

Centralized Developer Tracing & Observability Utility for Elsadara-Agent.

Provides a unified, human-readable terminal/Docker logging system across all layers:
- Communication / Webhooks (Facebook, WAHA)
- Agent / LangGraph & Agent Context Snapshots
- Search & Hybrid Retrieval (Fuzzy, Semantic, Merger, Context Building)
- OCR Pipeline (Prescription intake, multimodal Gemini)
- Knowledge & Test Generation / Insertion
- Infrastructure (Database, Qdrant, LLM, Services)

Features:
- Single shared implementation for all pipelines.
- Correlation Trace ID via contextvars (zero state modification).
- Native support for nested pipelines with indentation hierarchy.
- Rich visual ASCII formatting for developer terminal & Docker logs.
- Safe truncation and sensitive data masking (phone numbers, tokens, passwords).
- Log-level awareness (DEBUG for deep steps, INFO for high-level boundaries).
- Observational only: ZERO change to application behavior or return values.
"""

import contextvars
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple, Union

# ── Ensure UTF-8 Console Encoding (Windows / Cross-Platform Safety) ───────────

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Log Level Resolution ───────────────────────────────────────────────────────

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "DEBUG").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.DEBUG)

# ── Logger Setup & Persistent File Handlers ─────────────────────────────────────

LOGGER_NAME = "elsadara.trace"
_logger = logging.getLogger(LOGGER_NAME)
_logger.setLevel(LOG_LEVEL)

# Ensure logs directory exists
LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Stream handler for stdout
if not _logger.handlers and not logging.getLogger().handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setLevel(LOG_LEVEL)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.propagate = False

# File handlers for persistence (elsadara.log & error.log)
_has_file_handler = any(isinstance(h, RotatingFileHandler) for h in _logger.handlers)
if not _has_file_handler:
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "elsadara.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
    _logger.addHandler(file_handler)

    err_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "error.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    err_handler.setLevel(logging.WARNING)
    err_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
    _logger.addHandler(err_handler)

# ── Context Variables for Request & Pipeline State ─────────────────────────────

_current_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_trace_id", default=None
)

_pipeline_stack: contextvars.ContextVar[List[Tuple[str, float]]] = contextvars.ContextVar(
    "pipeline_stack", default=[]
)

# ── Sensitive Data Sanitization ───────────────────────────────────────────────

SENSITIVE_KEY_PATTERNS = re.compile(
    r"(password|token|secret|api[_-]?key|auth|cookie|credential|access[_-]?token|private[_-]?key)",
    re.IGNORECASE,
)

PHONE_PATTERN = re.compile(r"(\+?20|0)?1[0125]\d{8}")


def mask_phone_number(phone: str) -> str:
    """Mask phone number keeping leading prefix and last two digits (e.g. 010******23)."""
    if not phone or not isinstance(phone, str):
        return phone
    clean = phone.strip()
    match = PHONE_PATTERN.search(clean)
    if not match:
        return clean
    matched_phone = match.group(0)
    if len(matched_phone) >= 10:
        masked = matched_phone[:3] + "*" * (len(matched_phone) - 5) + matched_phone[-2:]
        return clean.replace(matched_phone, masked)
    return clean


def sanitize_data(data: Any, max_depth: int = 4) -> Any:
    """Recursively sanitize sensitive keys and mask phone numbers in dictionaries/lists."""
    if max_depth <= 0:
        return "... [max depth]"
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_str = str(k)
            if SENSITIVE_KEY_PATTERNS.search(k_str):
                sanitized[k] = "***MASKED***"
            elif isinstance(v, (dict, list)):
                sanitized[k] = sanitize_data(v, max_depth - 1)
            elif isinstance(v, str) and ("phone" in k_str.lower() or PHONE_PATTERN.search(v)):
                sanitized[k] = mask_phone_number(v)
            else:
                sanitized[k] = v
        return sanitized
    if isinstance(data, (list, tuple, set)):
        return [sanitize_data(item, max_depth - 1) for item in data]
    if isinstance(data, str) and PHONE_PATTERN.search(data):
        return mask_phone_number(data)
    return data


def safe_preview(val: Any, max_len: int = 500) -> str:
    """Create a safe string preview of large objects without memory explosion."""
    if val is None:
        return "None"
    if isinstance(val, (bytes, bytearray)):
        return f"<bytes len={len(val)}>"
    if hasattr(val, "model_dump"):
        try:
            val = val.model_dump()
        except Exception:
            pass
    elif hasattr(val, "__dict__") and not isinstance(val, type):
        try:
            val = {k: v for k, v in val.__dict__.items() if not k.startswith("_")}
        except Exception:
            pass

    sanitized = sanitize_data(val)
    if isinstance(sanitized, (dict, list)):
        try:
            text = json.dumps(sanitized, ensure_ascii=False, indent=2, default=str)
        except Exception:
            text = str(sanitized)
    else:
        text = str(sanitized)

    if len(text) > max_len:
        return f"{text[:max_len]} ... [truncated {len(text) - max_len} chars, total {len(text)}]"
    return text


# ── Trace ID Management ───────────────────────────────────────────────────────

def generate_trace_id() -> str:
    """Generate a lightweight 6-character random hex trace ID."""
    return uuid.uuid4().hex[:6]


def get_trace_id() -> str:
    """Return the active trace ID or generate a default one."""
    tid = _current_trace_id.get()
    if not tid:
        tid = generate_trace_id()
        _current_trace_id.set(tid)
    return tid


def set_trace_id(tid: Optional[str] = None) -> str:
    """Explicitly set or generate the trace ID for current context."""
    final_id = tid if (tid and str(tid).strip()) else generate_trace_id()
    _current_trace_id.set(final_id)
    return final_id


@contextmanager
def trace_scope(tid: Optional[str] = None):
    """Context manager for scoping an entire request with a correlation trace ID."""
    assigned = set_trace_id(tid)
    token = _current_trace_id.set(assigned)
    try:
        yield assigned
    finally:
        _current_trace_id.reset(token)


# ── Formatting & Emission ─────────────────────────────────────────────────────

SEPARATOR_WIDTH = 70


def _indent_prefix() -> str:
    """Generate visual tree indentation based on nested pipeline depth."""
    stack = _pipeline_stack.get()
    depth = len(stack)
    if depth <= 1:
        return ""
    return "│   " * (depth - 1)


def _emit(level: int, msg: str):
    """Emit formatted lines with trace ID and indentation."""
    if not _logger.isEnabledFor(level):
        return

    tid = get_trace_id()
    prefix = _indent_prefix()
    lines = msg.split("\n")
    formatted_lines = []
    for line in lines:
        if line.strip():
            formatted_lines.append(f"[{tid}] {prefix}{line}")
        else:
            formatted_lines.append(f"[{tid}] {prefix}")
    _logger.log(level, "\n".join(formatted_lines))


# ── Pipeline Lifecycle ────────────────────────────────────────────────────────

def start_pipeline(name: str, icon: str = "🚀", **initial_info) -> str:
    """Log the beginning of a pipeline with a clear visual header."""
    stack = list(_pipeline_stack.get())
    stack.append((name, time.time()))
    _pipeline_stack.set(stack)

    banner_title = f"{icon} {name.upper()}"
    sep = "=" * SEPARATOR_WIDTH
    sub_sep = "=" * min(len(banner_title) + 2, SEPARATOR_WIDTH)

    details = []
    for k, v in initial_info.items():
        if v is not None:
            details.append(f"• {k}: {safe_preview(v, max_len=120)}")
    detail_str = ("\n" + "\n".join(details)) if details else ""

    msg = f"\n{sep}\n{banner_title}\n{sub_sep}{detail_str}"
    _emit(logging.INFO, msg)
    return name


def end_pipeline(name: str, status: str = "COMPLETED", icon: str = "✅", **final_info):
    """Log the completion of a pipeline with duration and summary."""
    stack = list(_pipeline_stack.get())
    duration_str = ""
    if stack:
        _, start_t = stack[-1]
        duration = time.time() - start_t
        duration_str = f"duration: {duration:.2f}s"

    banner_title = f"{icon} {name.upper()} {status.upper()}"
    sep = "=" * SEPARATOR_WIDTH
    sub_sep = "=" * min(len(banner_title) + 2, SEPARATOR_WIDTH)

    details = []
    if duration_str:
        details.append(f"• {duration_str}")
    for k, v in final_info.items():
        if v is not None:
            details.append(f"• {k}: {safe_preview(v, max_len=150)}")
    detail_str = ("\n" + "\n".join(details)) if details else ""

    msg = f"{sep}\n{banner_title}\n{sub_sep}{detail_str}\n{sep}\n"
    _emit(logging.INFO, msg)

    if stack:
        stack.pop()
        _pipeline_stack.set(stack)


@contextmanager
def pipeline(name: str, icon: str = "🔄", **initial_info):
    """Context manager for nested pipeline execution with automatic timing and error logging."""
    start_pipeline(name, icon=icon, **initial_info)
    failed = False
    try:
        yield
    except Exception as e:
        failed = True
        log_error(f"{name} Failed", e)
        end_pipeline(name, status="FAILED", icon="❌", error=str(e))
        raise
    finally:
        if not failed:
            end_pipeline(name, status="COMPLETED", icon="✅")


# ── Step Logging ──────────────────────────────────────────────────────────────

def step(
    number_or_name: Union[int, str],
    title: Optional[str] = None,
    input_data: Any = None,
    output_data: Any = None,
    details: Optional[Dict[str, Any]] = None,
    duration: Optional[float] = None,
):
    """
    Log a distinct step in a pipeline.
    Supports:
      step("Step Name", input_data={...})
      step(1, "Step Name", input_data={...})
    """
    if not _logger.isEnabledFor(logging.DEBUG):
        return

    if title is None:
        header = f"[{number_or_name}]"
    elif isinstance(number_or_name, int):
        step_tag = f"[{number_or_name:02d}]"
        header = f"{step_tag} {title.upper()}"
    else:
        step_tag = f"[{number_or_name}]"
        header = f"{step_tag} {title.upper()}"

    lines = [f"\n--- {header} ---"]

    if duration is not None:
        lines.append(f"duration: {duration:.3f}s")

    if details:
        for k, v in details.items():
            lines.append(f"• {k}: {safe_preview(v, max_len=150)}")

    if input_data is not None:
        lines.append("📥 INPUT:")
        lines.append(safe_preview(input_data, max_len=600))

    if output_data is not None:
        lines.append("📤 OUTPUT:")
        lines.append(safe_preview(output_data, max_len=800))

    _emit(logging.DEBUG, "\n".join(lines))


def log_input(label: str = "INPUT", data: Any = None, **kwargs):
    """Log an input block."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return
    payload = data if data is not None else kwargs
    msg = f"📥 [{label}]:\n{safe_preview(payload, max_len=700)}"
    _emit(logging.DEBUG, msg)


def log_output(label: str = "OUTPUT", data: Any = None, **kwargs):
    """Log an output block."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return
    payload = data if data is not None else kwargs
    msg = f"📤 [{label}]:\n{safe_preview(payload, max_len=900)}"
    _emit(logging.DEBUG, msg)


def log_intermediate(label: str, data: Any = None, **kwargs):
    """Log an intermediate processing point."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return
    payload = data if data is not None else kwargs
    msg = f"⚙️ [{label}]:\n{safe_preview(payload, max_len=600)}"
    _emit(logging.DEBUG, msg)


def log_error(title: str, error: Union[Exception, str], context: Optional[Dict[str, Any]] = None):
    """Log an error occurrence with stack trace context."""
    err_str = str(error)
    lines = [
        "\n" + "!" * 50,
        f"❌ ERROR: {title}",
        f"Details: {err_str}",
    ]
    if context:
        lines.append("Context:")
        lines.append(safe_preview(context, max_len=400))
    lines.append("!" * 50)
    _emit(logging.ERROR, "\n".join(lines))


# ── Agent Context Snapshot (Prompt Sections 11 & 12) ───────────────────────────

def log_agent_context_snapshot(
    user_message: str,
    current_summary: Optional[str] = None,
    previous_summary: Optional[str] = None,
    recent_history: Optional[str] = None,
    last_bot_reply: Optional[str] = None,
    rag_context: Optional[str] = None,
    extra_state: Optional[Dict[str, Any]] = None,
):
    """
    Prints a clearly visible Agent Context Snapshot before an important LLM decision.
    Shows exactly what the Agent received and knew at response generation time.
    """
    if not _logger.isEnabledFor(logging.DEBUG):
        return

    sep = "=" * SEPARATOR_WIDTH
    lines = [
        f"\n{sep}",
        "🧠 AGENT CONTEXT SNAPSHOT",
        "=========================",
        "",
        "👤 CURRENT USER MESSAGE",
        "----------------------",
        user_message.strip() if user_message else "(Empty)",
        "",
        "📋 PREVIOUS SUMMARY",
        "-------------------",
        previous_summary.strip() if previous_summary else "previous_summary: None",
        "",
        "📝 CURRENT SUMMARY",
        "------------------",
        current_summary.strip() if current_summary else "current_summary: None",
        "",
        "💬 RECENT CHAT HISTORY",
        "----------------------",
        recent_history.strip() if recent_history else "(No chat history)",
        "",
        "🤖 LAST BOT REPLY",
        "-----------------",
        last_bot_reply.strip() if last_bot_reply else "last_bot_reply: None",
        "",
        "🔎 RAG / RETRIEVED CONTEXT",
        "--------------------------",
        safe_preview(rag_context, max_len=600) if rag_context else "(No RAG context)",
    ]

    if extra_state:
        filtered_extra = {
            k: v for k, v in extra_state.items()
            if k not in ("user_message", "summary", "last_bot_message", "rag_context")
            and v is not None
        }
        if filtered_extra:
            lines.extend([
                "",
                "📊 ADDITIONAL STATE FIELDS",
                "-------------------------",
                safe_preview(filtered_extra, max_len=300),
            ])

    lines.append(f"{sep}\n")
    _emit(logging.DEBUG, "\n".join(lines))


# ── LLM Tracing (Prompt Section 18) ───────────────────────────────────────────

def log_llm_call(
    operation: str,
    provider: str = "Google Gemini",
    model: Optional[str] = None,
    input_data: Any = None,
    output_data: Any = None,
    duration: Optional[float] = None,
    usage: Optional[Dict[str, int]] = None,
    error: Optional[Union[Exception, str]] = None,
):
    """Log an LLM invocation with input preview, output preview, duration, and token usage."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return

    lines = [
        f"🤖 [LLM CALL] {operation.upper()}",
        f"   Provider: {provider} | Model: {model or 'default'}",
    ]
    if duration is not None:
        lines.append(f"   Duration: {duration:.3f}s")
    if usage:
        lines.append(
            f"   Tokens: In={usage.get('input_tokens', 0)} | "
            f"Out={usage.get('output_tokens', 0)} | "
            f"Total={usage.get('total_tokens', 0)}"
        )
    if error:
        lines.append(f"   ❌ Error: {error}")
    if input_data is not None:
        lines.append("   📥 Input Preview:")
        lines.append(safe_preview(input_data, max_len=400))
    if output_data is not None:
        lines.append("   📤 Output Preview:")
        lines.append(safe_preview(output_data, max_len=500))

    _emit(logging.DEBUG, "\n".join(lines))


# ── Database Tracing (Prompt Section 19) ──────────────────────────────────────

def log_db_operation(
    operation: str,
    entity: str,
    criteria: Any = None,
    result: Any = None,
    count: Optional[int] = None,
    duration: Optional[float] = None,
    error: Optional[Union[Exception, str]] = None,
):
    """Log a meaningful database operation, query, or persistence update."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return

    header = f"💾 [DATABASE] {operation.upper()} -> {entity}"
    lines = [header]
    if duration is not None:
        lines.append(f"   Duration: {duration:.3f}s")
    if criteria is not None:
        lines.append(f"   Criteria: {safe_preview(criteria, max_len=150)}")
    if count is not None:
        lines.append(f"   Count: {count}")
    if result is not None:
        lines.append(f"   Result: {safe_preview(result, max_len=200)}")
    if error:
        lines.append(f"   ❌ Error: {error}")

    _emit(logging.DEBUG, "\n".join(lines))


# ── Qdrant Tracing (Prompt Section 20) ────────────────────────────────────────

def log_qdrant_operation(
    operation: str,
    collection: str,
    query_or_id: Any = None,
    count: Optional[int] = None,
    scores: Optional[List[float]] = None,
    payload_summary: Any = None,
    duration: Optional[float] = None,
    error: Optional[Union[Exception, str]] = None,
):
    """Log a Qdrant vector database query, retrieve, or upsert operation."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return

    lines = [
        f"🎯 [QDRANT] {operation.upper()} | Collection: {collection}",
    ]
    if duration is not None:
        lines.append(f"   Duration: {duration:.3f}s")
    if query_or_id is not None:
        lines.append(f"   Target/Query: {safe_preview(query_or_id, max_len=150)}")
    if count is not None:
        lines.append(f"   Points Count: {count}")
    if scores:
        scores_str = ", ".join(f"{s:.3f}" for s in scores[:5])
        lines.append(f"   Scores: [{scores_str}]")
    if payload_summary is not None:
        lines.append(f"   Payload: {safe_preview(payload_summary, max_len=200)}")
    if error:
        lines.append(f"   ❌ Error: {error}")

    _emit(logging.DEBUG, "\n".join(lines))


# ── Service Boundary Tracing (Prompt Section 21) ──────────────────────────────

def log_service_boundary(
    service_name: str,
    method: str,
    input_data: Any = None,
    output_data: Any = None,
    duration: Optional[float] = None,
    error: Optional[Union[Exception, str]] = None,
):
    """Log important service/repository boundary invocations."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return

    lines = [f"⚙️ [SERVICE] {service_name}.{method}"]
    if duration is not None:
        lines.append(f"   Duration: {duration:.3f}s")
    if input_data is not None:
        lines.append(f"   Input: {safe_preview(input_data, max_len=200)}")
    if output_data is not None:
        lines.append(f"   Output: {safe_preview(output_data, max_len=250)}")
    if error:
        lines.append(f"   ❌ Error: {error}")

    _emit(logging.DEBUG, "\n".join(lines))


# ── Standard Log Level Shorthands ─────────────────────────────────────────────

def debug(msg: str, *args, **kwargs):
    """Emit a debug level message with trace correlation."""
    _emit(logging.DEBUG, msg % args if args else msg)


def info(msg: str, *args, **kwargs):
    """Emit an info level message with trace correlation."""
    _emit(logging.INFO, msg % args if args else msg)


def warning(msg: str, *args, **kwargs):
    """Emit a warning level message with trace correlation."""
    _emit(logging.WARNING, msg % args if args else msg)


def error(msg: str, *args, **kwargs):
    """Emit an error level message with trace correlation."""
    _emit(logging.ERROR, msg % args if args else msg)


def is_debug() -> bool:
    """Return True if DEBUG logging is currently enabled."""
    return _logger.isEnabledFor(logging.DEBUG)


# ── TraceLogger Facade (Singleton) ────────────────────────────────────────────
# Allows `from utils.trace_logger import trace_logger` then `trace_logger.step(...)`
#
# Calling convention used by all instrumented nodes:
#   trace_logger.step("Label", input_data={...})
#   trace_logger.log_output({...})
#   trace_logger.error("message")
#   trace_logger.log_llm_call(model=.., duration=.., input_tokens=.., output_tokens=.., call_type=..)
#   trace_logger.log_db_operation(op, table, success=True, error=None, extra={})
#   trace_logger.log_qdrant_operation(operation=.., collection=.., duration=.., results_count=.., top_score=.., error=..)
#   trace_logger.start_pipeline("NAME")
#   trace_logger.end_pipeline("NAME")
#   trace_logger.log_agent_context_snapshot(user_message, previous_summary, current_summary, recent_history, last_bot_message, rag_context)
#   trace_logger.sanitize_phone(value)


class _TraceLogger:
    """
    Singleton facade with adapter methods that match the calling convention
    used by all instrumented agent nodes and services.
    """

    # ── Pipeline Lifecycle ────────────────────────────────────────
    @staticmethod
    def start_pipeline(name: str, **kwargs):
        start_pipeline(name, **kwargs)

    @staticmethod
    def end_pipeline(name: str, **kwargs):
        end_pipeline(name, **kwargs)

    # ── Step Logging (adapted: label as first arg, input_data as kwarg) ───────
    @staticmethod
    def step(label: str, input_data: Any = None, output_data: Any = None):
        """
        Log a named step.
        Usage: trace_logger.step("Step Label", input_data={...})
        Maps label → number_or_name, label → title (same string).
        """
        if not _logger.isEnabledFor(logging.DEBUG):
            return
        step(label, label, input_data=input_data, output_data=output_data)

    # ── Input / Output ────────────────────────────────────────────
    @staticmethod
    def log_input(data: Any = None, label: str = "INPUT", **kwargs):
        log_input(label=label, data=data if data is not None else kwargs)

    @staticmethod
    def log_output(data: Any = None, label: str = "OUTPUT", **kwargs):
        """
        Log an output block.
        Usage: trace_logger.log_output({...})
        """
        log_output(label=label, data=data if data is not None else kwargs)

    @staticmethod
    def log_intermediate(label: str, data: Any = None, **kwargs):
        log_intermediate(label, data=data if data is not None else kwargs)

    # ── Agent Context Snapshot ────────────────────────────────────
    @staticmethod
    def log_agent_context_snapshot(
        user_message: str = "",
        current_summary: Any = None,
        previous_summary: Any = None,
        recent_history: Any = None,
        last_bot_reply: Any = None,
        last_bot_message: Any = None,
        rag_context: Any = None,
        extra_state: Any = None,
        **kwargs,
    ):
        bot_reply = last_bot_reply if last_bot_reply is not None else last_bot_message

        # Normalize recent_history list → string
        if isinstance(recent_history, list):
            parts = []
            for row in recent_history:
                if isinstance(row, dict):
                    u = row.get("user_message", row.get("user", ""))
                    b = row.get("bot_reply", row.get("bot", ""))
                    parts.append(f"User: {u}\nBot: {b}")
                else:
                    parts.append(str(row))
            recent_history = "\n---\n".join(parts)

        log_agent_context_snapshot(
            user_message=user_message,
            current_summary=current_summary,
            previous_summary=previous_summary,
            recent_history=recent_history,
            last_bot_reply=bot_reply,
            rag_context=rag_context,
            extra_state=extra_state,
        )


    # ── LLM Calls ─────────────────────────────────────────────────
    @staticmethod
    def log_llm_call(
        model: str = "",
        duration: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        call_type: str = "",
        **kwargs,
    ):
        """
        Adapter: bridges (model, duration, input_tokens, output_tokens, call_type)
        to real log_llm_call(operation, provider, model, duration, usage).
        """
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        log_llm_call(
            operation=call_type or "llm_call",
            provider="Google Gemini",
            model=model,
            duration=duration,
            usage=usage,
        )

    # ── DB Operations ──────────────────────────────────────────────
    @staticmethod
    def log_db_operation(
        operation: str,
        table: str,
        success: bool = True,
        error: Any = None,
        extra: Any = None,
        **kwargs,
    ):
        """
        Adapter: bridges (operation, table, success, error, extra)
        to real log_db_operation(operation, entity, result, error).
        """
        result_data = {"success": success}
        if extra:
            if isinstance(extra, dict):
                result_data.update(extra)
            else:
                result_data["detail"] = str(extra)
        log_db_operation(
            operation=operation,
            entity=table,
            result=result_data,
            error=error if not success else None,
        )

    # ── Qdrant Operations ─────────────────────────────────────────
    @staticmethod
    def log_qdrant_operation(
        operation: str = "",
        collection: str = "",
        duration: float = 0.0,
        results_count: int = 0,
        top_score: float = 0.0,
        error: Any = None,
        **kwargs,
    ):
        """
        Adapter: bridges (operation, collection, duration, results_count, top_score, error)
        to real log_qdrant_operation(operation, collection, count, scores, duration, error).
        """
        log_qdrant_operation(
            operation=operation,
            collection=collection,
            count=results_count,
            scores=[top_score] if top_score else None,
            duration=duration,
            error=error,
        )


    # ── Service Boundary ──────────────────────────────────────────
    @staticmethod
    def log_service_boundary(service_name: str, method: str, **kwargs):
        log_service_boundary(service_name, method, **kwargs)

    # ── Trace ID Management ───────────────────────────────────────
    get_trace_id = staticmethod(get_trace_id)
    set_trace_id = staticmethod(set_trace_id)

    # ── Log-level Shorthands ──────────────────────────────────────
    debug = staticmethod(debug)
    info = staticmethod(info)
    warning = staticmethod(warning)

    @staticmethod
    def error(msg: str, *args, **kwargs):
        """Emit an error-level trace message."""
        _emit(logging.ERROR, msg % args if args else msg)

    log_error = staticmethod(log_error)

    # ── Utilities ─────────────────────────────────────────────────
    sanitize_phone = staticmethod(mask_phone_number)
    sanitize_data = staticmethod(sanitize_data)
    safe_preview = staticmethod(safe_preview)

    @staticmethod
    def is_debug() -> bool:
        return _logger.isEnabledFor(logging.DEBUG)


def log_production_summary(
    sender_id: str = "",
    platform_name: str = "",
    page_id: str = "",
    user_message: str = "",
    detected_intent: Optional[str] = None,
    chat_summary: Optional[str] = None,
    bot_response: Optional[str] = None,
    usage: Optional[dict] = None,
    ocr_result: Optional[dict] = None,
    duration: float = 0.0,
    **kwargs,
):
    """
    Emits a clean, highly structured UTF-8 ASCII box-drawing summary of a completed request execution,
    including context, intent, conversation exchange, OCR findings, and a token usage/cost table.
    """
    tid = get_trace_id()
    masked_sender = mask_phone_number(sender_id) if sender_id else "N/A"
    platform_str = f"{platform_name or 'N/A'} (Page: {page_id or 'N/A'})"
    
    lines = []
    lines.append("╔══════════════════════════════════════════════════════════════════════════════════════════════╗")
    lines.append("║                     📊 ELSADARA AGENT - PRODUCTION SUMMARY                           ║")
    lines.append("╠══════════════════════════════════════════════════════════════════════════════════════════════╣")
    lines.append("║ 🆔 Request Context                                                                           ║")
    lines.append(f"║   • Trace ID:      {tid}")
    lines.append(f"║   • Sender ID:     {masked_sender}")
    lines.append(f"║   • Platform/Page: {platform_str}")
    if duration > 0:
        lines.append(f"║   • Duration:      {duration:.2f}s")
    
    lines.append("╠══════════════════════════════════════════════════════════════════════════════════════════════╣")
    lines.append("║ 💬 Conversation & Intent Details                                                             ║")
    lines.append(f"║   • User Message:   {safe_preview(user_message, max_len=120) if user_message else 'N/A'}")
    lines.append(f"║   • Detected Intent: {detected_intent or 'N/A'}")
    if chat_summary:
        lines.append(f"║   • Chat Summary:   {safe_preview(chat_summary, max_len=120)}")
    if bot_response:
        lines.append(f"║   • Bot Response:   {safe_preview(bot_response, max_len=150)}")
        
    if ocr_result and isinstance(ocr_result, dict):
        lines.append("╠══════════════════════════════════════════════════════════════════════════════════════════════╣")
        lines.append("║ 👁️ OCR Prescription Results                                                                  ║")
        lines.append(f"║   • OCR Status:     {ocr_result.get('status', 'SUCCESS')}")
        if ocr_result.get("extracted_text"):
            lines.append(f"║   • Extracted Text: {safe_preview(ocr_result['extracted_text'], max_len=120)}")
        if ocr_result.get("recognized_services"):
            services = ocr_result['recognized_services']
            services_str = ", ".join([str(s) for s in services]) if isinstance(services, list) else str(services)
            lines.append(f"║   • Recognized:     {safe_preview(services_str, max_len=120)}")
        if ocr_result.get("confidence_score") is not None:
            lines.append(f"║   • Confidence:     {ocr_result['confidence_score']}%")

    if usage and isinstance(usage, dict) and usage.get("breakdown"):
        lines.append("╠══════════════════════════════════════════════════════════════════════════════════════════════╣")
        lines.append("║ 🧮 Token Usage & Cost Breakdown Table                                                       ║")
        lines.append("║  ┌──────────────────┬──────────────┬───────────────┬──────────────┬────────────────────────┐  ║")
        lines.append("║  │ Pipeline Node    │ Input Tokens │ Output Tokens │ Total Tokens │ Est. Cost (USD)        │  ║")
        lines.append("║  ├──────────────────┼──────────────┼───────────────┼──────────────┼────────────────────────┤  ║")
        
        breakdown = usage.get("breakdown", {})
        for node_key, info in breakdown.items():
            in_t = info.get("input", 0)
            out_t = info.get("output", 0)
            tot_t = info.get("total", 0)
            cost = info.get("cost_usd", 0.0)
            lines.append(f"║  │ {node_key:<16} │ {in_t:>12,} │ {out_t:>13,} │ {tot_t:>12,} │ ${cost:<21.6f} │  ║")
            
        lines.append("║  ├──────────────────┼──────────────┼───────────────┼──────────────┼────────────────────────┤  ║")
        tot_in = usage.get("total_input", 0)
        tot_out = usage.get("total_output", 0)
        tot_all = usage.get("total_tokens", 0)
        tot_cost = usage.get("total_cost_usd", 0.0)
        lines.append(f"║  │ TOTAL            │ {tot_in:>12,} │ {tot_out:>13,} │ {tot_all:>12,} │ ${tot_cost:<21.6f} │  ║")
        lines.append("║  └──────────────────┴──────────────┴───────────────┴──────────────┴────────────────────────┘  ║")
        
    lines.append("╚══════════════════════════════════════════════════════════════════════════════════════════════╝")

    full_msg = "\n" + "\n".join(lines)
    _emit(logging.INFO, full_msg)


_TraceLogger.log_production_summary = staticmethod(log_production_summary)
trace_logger = _TraceLogger()
