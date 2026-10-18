import time
import uuid
import logging
import contextvars
from contextlib import contextmanager
from typing import Optional, Dict, Any

logger = logging.getLogger("elsadara.profiler")

_active_profiler: contextvars.ContextVar[Optional["RequestProfiler"]] = contextvars.ContextVar(
    "active_profiler", default=None
)


class RequestProfiler:
    """
    End-to-End Request Performance Profiler using time.perf_counter().
    Thread-safe and context-safe via contextvars.
    """

    def __init__(self, request_id: Optional[str] = None, user_id: Optional[str] = None, start_time: Optional[float] = None):
        self.request_id = request_id or str(uuid.uuid4())[:8]
        self.user_id = user_id or "unknown"
        self.start_time = start_time if start_time is not None else time.perf_counter()
        self.end_time: Optional[float] = None
        self.total_wall_time: float = 0.0

        # Primary Stages
        self.timings: Dict[str, float] = {}

        # Search Breakdown
        self.fuzzy_breakdown: Dict[str, float] = {
            "prepare": 0.0,
            "db_load": 0.0,
            "candidate_prep": 0.0,
            "comparisons": 0.0,
            "sort": 0.0,
        }

        # LLM Breakdown
        self.llm_timings: Dict[str, float] = {}

        # External Integrations Breakdown
        self.external_timings: Dict[str, float] = {}

        # Metadata
        self.metadata: Dict[str, Any] = {}

    @classmethod
    def get_active(cls) -> Optional["RequestProfiler"]:
        return _active_profiler.get()

    @classmethod
    def set_active(cls, profiler: Optional["RequestProfiler"]):
        _active_profiler.set(profiler)

    @classmethod
    def record_stage(cls, stage_name: str, duration: float):
        profiler = cls.get_active()
        if profiler:
            profiler.add_timing(stage_name, duration)

    @classmethod
    @contextmanager
    def measure_stage(cls, stage_name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            dt = time.perf_counter() - t0
            cls.record_stage(stage_name, dt)

    @classmethod
    def record_fuzzy(cls, substage: str, duration: float):
        profiler = cls.get_active()
        if profiler:
            profiler.record_fuzzy_substage(substage, duration)

    @classmethod
    def record_llm(cls, name: str, duration: float):
        profiler = cls.get_active()
        if profiler:
            profiler.record_llm_call(name, duration)

    @classmethod
    def record_external(cls, name: str, duration: float):
        profiler = cls.get_active()
        if profiler:
            profiler.record_external_op(name, duration)

    @contextmanager
    def measure(self, stage_name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            dt = time.perf_counter() - t0
            self.add_timing(stage_name, dt)

    def add_timing(self, stage_name: str, duration: float):
        self.timings[stage_name] = self.timings.get(stage_name, 0.0) + duration

    def record_fuzzy_substage(self, substage: str, duration: float):
        self.fuzzy_breakdown[substage] = self.fuzzy_breakdown.get(substage, 0.0) + duration

    def record_llm_call(self, name: str, duration: float):
        self.llm_timings[name] = self.llm_timings.get(name, 0.0) + duration

    def record_external_op(self, name: str, duration: float):
        self.external_timings[name] = self.external_timings.get(name, 0.0) + duration

    def finish(self) -> float:
        self.end_time = time.perf_counter()
        self.total_wall_time = self.end_time - self.start_time
        return self.total_wall_time

    def format_summary(self) -> str:
        if self.end_time is None:
            self.finish()

        lines = [
            "",
            "========== AGENT PERFORMANCE ==========",
            "",
            f"request_id = {self.request_id}",
            f"user_id    = {self.user_id}",
            f"total      = {self.total_wall_time:.3f}s",
            "",
        ]

        # Stage order
        stage_order = [
            ("webhook_receive", "webhook_receive"),
            ("message_parsing", "message_parsing"),
            ("debounce", "debounce"),
            ("client_lookup", "client_lookup"),
            ("chat_history_load", "chat_history_load"),
            ("intent", "intent"),
            ("query_refinement", "query_refinement"),
            ("search_total", "search_total"),
            ("fuzzy_search", "fuzzy_search"),
            ("embedding", "embedding"),
            ("qdrant", "qdrant"),
            ("merge", "merge"),
            ("db_fetch", "db_fetch"),
            ("context_building", "context_building"),
            ("final_llm", "final_llm"),
            ("db_save", "db_save"),
            ("response_formatting", "response_formatting"),
            ("send_response", "send_response"),
        ]

        # Grouping for clean output
        for key, label in stage_order:
            if key in self.timings:
                val = self.timings[key]
                lines.append(f"{label:<20} = {val:.3f}s")
                if key == "fuzzy_search" and any(self.fuzzy_breakdown.values()):
                    lines.append(f"  ├── prepare         = {self.fuzzy_breakdown['prepare']:.3f}s")
                    lines.append(f"  ├── db_load         = {self.fuzzy_breakdown['db_load']:.3f}s")
                    lines.append(f"  ├── candidate_prep  = {self.fuzzy_breakdown['candidate_prep']:.3f}s")
                    lines.append(f"  ├── comparisons     = {self.fuzzy_breakdown['comparisons']:.3f}s")
                    lines.append(f"  └── sort            = {self.fuzzy_breakdown['sort']:.3f}s")
                if key in ["chat_history_load", "query_refinement", "merge", "context_building", "final_llm"]:
                    lines.append("")

        # Add any other stages measured not in the main list
        other_keys = [k for k in self.timings if k not in dict(stage_order)]
        if other_keys:
            lines.append("--- Other Stages ---")
            for k in other_keys:
                lines.append(f"{k:<20} = {self.timings[k]:.3f}s")
            lines.append("")

        # LLMs
        if self.llm_timings:
            lines.append("--- LLM Calls ---")
            for name, dur in self.llm_timings.items():
                lines.append(f"{name:<20} = {dur:.3f}s")
            lines.append("")

        # External Integrations
        if self.external_timings:
            lines.append("--- External Integrations ---")
            for name, dur in self.external_timings.items():
                lines.append(f"{name:<20} = {dur:.3f}s")
            lines.append("")

        lines.append("========================================")
        lines.append("")
        return "\n".join(lines)

    def log_report(self):
        report = self.format_summary()
        logger.info(report)
