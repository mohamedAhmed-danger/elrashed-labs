import logging
import os
import platform
import shutil
import sys
import time
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, render_template
from flask_login import login_required
from sqlalchemy import text

from models.models import db, User, Booking, Inquiry, Complaint, Laboratory, LabService

try:
    import psutil
except ImportError:  # psutil is optional; every metric below has a fallback
    psutil = None

logger = logging.getLogger(__name__)

health_bp = Blueprint('health', __name__, url_prefix='/system-health')

APP_START_TIME = datetime.now(timezone.utc)

MB = 1024 * 1024
GB = 1024 * 1024 * 1024


# ── Small file helpers ────────────────────────────────────────────────────────

def _read_text(path: str):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def _read_kv(path: str) -> dict:
    """Parse 'key value' lines (cgroup memory.stat, /proc/meminfo style) into ints."""
    result = {}
    raw = _read_text(path)
    if not raw:
        return result
    for line in raw.splitlines():
        parts = line.replace(":", " ").split()
        if len(parts) >= 2:
            try:
                result[parts[0]] = int(parts[1])
            except ValueError:
                continue
    return result


# ── SERVER metrics (the whole machine) ────────────────────────────────────────

def _server_cpu_percent() -> float:
    if psutil:
        return round(psutil.cpu_percent(interval=0.1), 1)
    try:
        load1 = os.getloadavg()[0]
        return round(min(load1 / (os.cpu_count() or 1) * 100, 100), 1)
    except Exception:
        return 0.0


def _server_memory():
    """Returns (percent, used_bytes, total_bytes) for the whole machine."""
    if psutil:
        mem = psutil.virtual_memory()
        return round(mem.percent, 1), mem.used, mem.total

    info = _read_kv("/proc/meminfo")  # values are in kB
    total = info.get("MemTotal", 0) * 1024
    available = info.get("MemAvailable", 0) * 1024
    if total:
        used = total - available
        return round(used / total * 100, 1), used, total
    return 0.0, 0, 0


def _server_disk():
    """Returns (percent, free_bytes, total_bytes) for the partition mounted at '/'."""
    try:
        total, used, free = shutil.disk_usage("/")
        return round(used / total * 100, 1), free, total
    except Exception:
        return 0.0, 0, 0


def get_system_metrics() -> dict:
    uptime_delta = datetime.now(timezone.utc) - APP_START_TIME
    hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    mem_percent, mem_used, mem_total = _server_memory()
    disk_percent, disk_free, disk_total = _server_disk()

    return {
        "cpu_usage": _server_cpu_percent(),
        "memory_percent": mem_percent,
        "memory_used_mb": round(mem_used / MB, 1),
        "memory_total_mb": round(mem_total / MB, 1),
        "disk_percent": disk_percent,
        "disk_free_gb": round(disk_free / GB, 1),
        "disk_total_gb": round(disk_total / GB, 1),
        "python_version": sys.version.split()[0],
        "os_info": f"{platform.system()} {platform.release()}",
        "uptime_str": f"{hours}h {minutes}m {seconds}s",
    }


# ── PROJECT metrics (this container / app only) ───────────────────────────────

def _container_memory():
    """
    Memory used by this container only, as (used_bytes, limit_bytes_or_None).
    Reads the cgroup files (v2 first, then v1) and subtracts reclaimable page cache,
    which is how `docker stats` reports it. Returns None if cgroup info is unavailable.
    """
    # cgroup v2
    current = _read_text("/sys/fs/cgroup/memory.current")
    if current and current.isdigit():
        used = int(current) - _read_kv("/sys/fs/cgroup/memory.stat").get("inactive_file", 0)
        raw_limit = _read_text("/sys/fs/cgroup/memory.max")
        limit = int(raw_limit) if raw_limit and raw_limit.isdigit() else None
        return max(used, 0), limit

    # cgroup v1
    usage = _read_text("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if usage and usage.isdigit():
        used = int(usage) - _read_kv("/sys/fs/cgroup/memory/memory.stat").get("total_inactive_file", 0)
        raw_limit = _read_text("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        limit = int(raw_limit) if raw_limit and raw_limit.isdigit() else None
        if limit is not None and limit > 1 << 50:  # v1 reports a huge number when unlimited
            limit = None
        return max(used, 0), limit

    return None


def _process_rss_bytes() -> int:
    """Resident memory of the current worker process only."""
    if psutil:
        return psutil.Process().memory_info().rss
    try:
        pages = int(_read_text("/proc/self/statm").split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except Exception:
        return 0


_uploads_cache = {"time": 0.0, "size": 0, "files": 0}
_UPLOADS_CACHE_TTL = 60  # seconds, avoids re-scanning a growing folder on every refresh


def _uploads_stats(uploads_dir: str):
    """Returns (total_size_bytes, file_count) of the uploads folder, cached for a minute."""
    now = time.time()
    if now - _uploads_cache["time"] < _UPLOADS_CACHE_TTL:
        return _uploads_cache["size"], _uploads_cache["files"]

    size = 0
    files = 0
    try:
        with os.scandir(uploads_dir) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False):
                    size += entry.stat(follow_symlinks=False).st_size
                    files += 1
    except Exception:
        logger.exception("[HEALTH] uploads scan failed")

    _uploads_cache.update({"time": now, "size": size, "files": files})
    return size, files


def get_app_metrics(uploads_dir: str) -> dict:
    cg = _container_memory()
    used_mb = limit_mb = percent = None
    if cg:
        used, limit = cg
        used_mb = round(used / MB, 1)
        if limit:
            limit_mb = round(limit / MB, 1)
            percent = round(used / limit * 100, 1)

    uploads_size, uploads_files = _uploads_stats(uploads_dir)

    return {
        "memory_used_mb": used_mb,          # None when cgroup info is unavailable
        "memory_limit_mb": limit_mb,        # None when the container has no memory limit
        "memory_percent": percent,          # None when there is no limit to compare against
        "process_rss_mb": round(_process_rss_bytes() / MB, 1),
        "uploads_size_mb": round(uploads_size / MB, 2),
        "uploads_files": uploads_files,
        "psutil_available": psutil is not None,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@health_bp.route('/')
@login_required
def health_dashboard():
    """Render the System Health Dashboard HTML page."""
    return render_template('system_health.html')


def _safe_count(model):
    """Count rows for one model. Returns None (not 0) on failure so it isn't mistaken for an empty table."""
    try:
        return model.query.count()
    except Exception:
        logger.exception("[HEALTH] count failed for %s", model.__name__)
        db.session.rollback()
        return None


@health_bp.route('/api/status')
@login_required
def health_api_status():
    """JSON endpoint returning live system health diagnostic info."""
    start_time = time.time()
    db_status = "offline"
    db_latency_ms = 0
    db_engine_name = "unknown"

    # Database connectivity & latency test
    try:
        db.session.execute(text("SELECT 1"))
        db_latency_ms = round((time.time() - start_time) * 1000, 2)
        db_status = "online"
        db_engine_name = db.engine.name
    except Exception:
        logger.exception("[HEALTH] DB check failed")
        db_status = "error"

    counts = {
        "users": _safe_count(User),
        "bookings": _safe_count(Booking),
        "inquiries": _safe_count(Inquiry),
        "complaints": _safe_count(Complaint),
        "laboratories": _safe_count(Laboratory),
        "services": _safe_count(LabService),
    }

    # Uploads directory (resolved from the Flask app, not from the working directory)
    static_folder = current_app.static_folder or os.path.join(current_app.root_path, "static")
    uploads_dir = os.path.join(static_folder, "uploads")
    uploads_exists = os.path.exists(uploads_dir)
    uploads_writable = os.access(uploads_dir, os.W_OK) if uploads_exists else False

    system_metrics = get_system_metrics()
    app_metrics = get_app_metrics(uploads_dir)

    app_mem_ok = app_metrics["memory_percent"] is None or app_metrics["memory_percent"] < 95
    is_overall_healthy = (
        db_status == "online"
        and system_metrics["memory_percent"] < 95
        and app_mem_ok
    )

    return jsonify({
        "overall_status": "healthy" if is_overall_healthy else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": {
            "status": db_status,
            "latency_ms": db_latency_ms,
            "engine": db_engine_name,
        },
        "system": system_metrics,   # the whole server
        "app": app_metrics,         # this project / container only
        "counts": counts,
        "storage": {
            "uploads_dir_exists": uploads_exists,
            "uploads_writable": uploads_writable,
        },
    })