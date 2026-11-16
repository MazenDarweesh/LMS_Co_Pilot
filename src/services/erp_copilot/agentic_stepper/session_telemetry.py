"""
Session Telemetry & Black-Box Event Logging Service.
Appends structured JSONL execution traces to session-specific files and the unified debug ledger,
with thread-safe locking, log rotation, retention cleanup, sensitive key redaction, and legacy .log read fallback.
"""

from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, Optional
import structlog

from src.core.config import settings

logger = structlog.get_logger()

ERP_LOGS_DIR = Path(settings.ERP_LOGS_DIR)
ERP_TEST_LOGS_DIR = Path(settings.ERP_TEST_LOGS_DIR)
SHARED_LOGS_DIR = (
    Path(settings.ERP_SHARED_LOGS_DIR)
    if settings.ERP_SHARED_LOGS_DIR
    else Path("e:/Mazen/shared_logs/erp_sessions")
)

_WRITE_LOCK = threading.Lock()
_LAST_CLEANUP_TS = 0.0
_CLEANUP_INTERVAL_SECONDS = 3600.0

_SENSITIVE_KEYS = {
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
}

_LEGACY_LINE_PATTERN = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\s+\[(?P<level>[^\]]+)\]\s+\[(?P<stage>[^\]]+)\]\s+(?P<message>[^|]*)(?:\s*\|\s*(?P<details>.*))?$"
)
_LEGACY_TRACE_PATTERN = re.compile(r"\[trc:(?P<trace_id>[^\]]+)\]")


class TelemetryStage(str, Enum):
    """
    ثوابت المراحل الهرمية للأحداث (Hierarchical Stage Taxonomy).
    تربط كل سطر في اللوج بالموديول البرمجي المسؤول بدقة 100%.
    """
    # 1. Stepper Subsystem (src/services/agentic_stepper/)
    STEPPER_ENGINE = "STEPPER.ENGINE"
    STEPPER_RESOLVER = "STEPPER.RESOLVER"
    STEPPER_EXTRACTOR = "STEPPER.EXTRACTOR"
    STEPPER_VERIFY = "STEPPER.VERIFY"

    # 2. CDP Subsystem (src/services/cdp/)
    CDP_CONNECT = "CDP.CONNECT"
    CDP_NAVIGATOR = "CDP.NAVIGATOR"
    CDP_FORM_BRIDGE = "CDP.FORM_BRIDGE"
    CDP_VISUAL = "CDP.VISUAL"
    CDP_DISPATCHER = "CDP.DISPATCHER"

    # 3. In-Browser / Angular Driver Subsystem (via /telemetry endpoint)
    BROWSER_USER_QUERY = "BROWSER.USER_QUERY"
    BROWSER_BRIDGE = "BROWSER.BRIDGE"
    BROWSER_SCAN = "BROWSER.SCAN"
    BROWSER_FILL = "BROWSER.FILL"
    BROWSER_GRID = "BROWSER.GRID"
    BROWSER_GENERAL = "BROWSER.GENERAL"


def normalize_session_base_id(session_id: str) -> str:
    """Normalize session_id and strip redundant leading `session_` prefixes."""
    clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id.strip())
    while clean_id.lower().startswith("session_"):
        clean_id = clean_id[len("session_"):]
    return clean_id or "unknown"


def _is_test_session(session_id: str, base_id: str) -> bool:
    raw_clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id.strip()).lower()
    return raw_clean.startswith(("test_", "unit_test_")) or base_id.lower().startswith(("test_", "unit_test_"))


def _redact_details(obj: Any) -> Any:
    """Recursively mask sensitive credential keys inside telemetry payloads."""
    if isinstance(obj, dict):
        sanitized: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).strip().lower() in _SENSITIVE_KEYS:
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = _redact_details(v)
        return sanitized
    if isinstance(obj, list):
        return [_redact_details(item) for item in obj]
    return obj


def _resolve_target_dirs(is_test: bool) -> list[Path]:
    if is_test:
        return [ERP_TEST_LOGS_DIR]
    dirs = [ERP_LOGS_DIR]
    if settings.ERP_SHARED_LOGS_DIR or SHARED_LOGS_DIR.exists():
        dirs.append(SHARED_LOGS_DIR)
    return dirs


def _rotate_file_if_needed(file_path: Path, max_bytes: int, backup_count: int) -> None:
    """Rotate file to .1 .. .backup_count when size reaches max_bytes."""
    if max_bytes <= 0 or backup_count <= 0 or not file_path.exists():
        return
    if file_path.stat().st_size < max_bytes:
        return

    oldest = Path(f"{file_path}.{backup_count}")
    if oldest.exists():
        oldest.unlink()
    for idx in range(backup_count - 1, 0, -1):
        src = Path(f"{file_path}.{idx}")
        if src.exists():
            src.replace(Path(f"{file_path}.{idx + 1}"))
    file_path.replace(Path(f"{file_path}.1"))


def _cleanup_expired_sessions(target_dirs: list[Path], retention_days: int) -> None:
    """Opportunistically delete expired session log files at most once per hour."""
    global _LAST_CLEANUP_TS
    if retention_days <= 0:
        return
    now = time.time()
    if now - _LAST_CLEANUP_TS < _CLEANUP_INTERVAL_SECONDS:
        return
    _LAST_CLEANUP_TS = now
    cutoff = now - (retention_days * 86400)

    for target_dir in target_dirs:
        if not target_dir.exists():
            continue
        for pattern in ("session_*.jsonl", "session_*.log"):
            for path in target_dir.glob(pattern):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError as exc:
                    logger.warning("Failed to remove expired session log", path=str(path), error=str(exc))


def append_session_event(
    session_id: Optional[str],
    level: str,
    stage: str | TelemetryStage,
    message: str,
    details: Optional[dict[str, Any]] = None,
    *,
    trace_id: Optional[str] = None,
    screen_key: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> None:
    """
    تسجيل حدث تفصيلي بصيغة JSONL في ملف الجلسة المستقل وفي السجل الجامع الموحد.
    """
    if not session_id or not session_id.strip():
        return

    base_id = normalize_session_base_id(session_id)
    is_test = _is_test_session(session_id, base_id)
    session_filename = f"session_{base_id}.jsonl"
    unified_filename = "agent_unified_debug.jsonl"

    iso_now = timestamp or datetime.now(timezone.utc).isoformat()
    stage_str = str(stage.value if isinstance(stage, Enum) else stage).upper()
    details_dict = dict(details) if isinstance(details, dict) else {}
    eff_trace_id = trace_id or details_dict.get("traceId") or details_dict.get("trace_id")

    record: dict[str, Any] = {
        "timestamp": iso_now,
        "session_id": base_id,
        "level": level.upper(),
        "stage": stage_str,
        "message": message,
        "details": _redact_details(details_dict),
    }
    if eff_trace_id:
        record["trace_id"] = str(eff_trace_id)
    if screen_key:
        record["screen_key"] = str(screen_key)

    serialized_line = json.dumps(record, ensure_ascii=False) + "\n"
    target_dirs = _resolve_target_dirs(is_test)

    with _WRITE_LOCK:
        for target_dir in target_dirs:
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                session_path = target_dir / session_filename
                unified_path = target_dir / unified_filename

                _rotate_file_if_needed(
                    unified_path,
                    settings.ERP_TELEMETRY_MAX_BYTES,
                    settings.ERP_TELEMETRY_BACKUP_COUNT,
                )

                with open(session_path, "a", encoding="utf-8") as sf:
                    sf.write(serialized_line)
                with open(unified_path, "a", encoding="utf-8") as uf:
                    uf.write(serialized_line)
            except Exception as exc:
                logger.warning(
                    "Failed to append session telemetry event",
                    session_id=base_id,
                    dir=str(target_dir),
                    error=str(exc),
                )
        if not is_test:
            _cleanup_expired_sessions(target_dirs, settings.ERP_TELEMETRY_RETENTION_DAYS)


def _find_session_file(session_id: str) -> tuple[Optional[Path], bool]:
    """Locate session telemetry file, preferring JSONL over legacy .log files."""
    raw_clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id.strip())
    base_id = normalize_session_base_id(session_id)
    is_test = _is_test_session(session_id, base_id)

    candidate_dirs = (
        [ERP_TEST_LOGS_DIR, ERP_LOGS_DIR, SHARED_LOGS_DIR]
        if is_test
        else [ERP_LOGS_DIR, SHARED_LOGS_DIR, ERP_TEST_LOGS_DIR]
    )
    candidate_names = [
        (f"session_{base_id}.jsonl", True),
        (f"session_{raw_clean}.jsonl", True),
        (f"session_{raw_clean}.log", False),
        (f"session_{base_id}.log", False),
    ]

    for d in candidate_dirs:
        for name, is_jsonl in candidate_names:
            p = d / name
            if p.exists():
                return p, is_jsonl
    return None, True


def _matches_filters(
    ev_level: str,
    ev_stage: str,
    ev_trace: Optional[str],
    ev_details: dict[str, Any],
    level_filter: Optional[str],
    prefix_str: str,
    trace_filter: Optional[str],
) -> bool:
    if level_filter and ev_level != level_filter:
        return False
    if prefix_str and not ev_stage.startswith(prefix_str):
        return False
    if trace_filter:
        candidate_trace = ev_trace or ev_details.get("traceId") or ev_details.get("trace_id")
        if str(candidate_trace or "") != trace_filter:
            return False
    return True


def read_session_events(
    session_id: str,
    stage_prefix: Optional[str | TelemetryStage] = None,
    level: Optional[str] = None,
    limit: int = 300,
    trace_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    قراءة وتحليل أحداث جلسة محددة من الصندوق الأسود مع دعم الفلترة بـ stage_prefix و level و trace_id.
    يدعم ملفات JSONL الحديثة وملفات .log القديمة تلقائياً.
    """
    if not session_id or not session_id.strip():
        return []

    file_path, is_jsonl = _find_session_file(session_id)
    if file_path is None:
        return []

    prefix_str = str(stage_prefix.value if isinstance(stage_prefix, Enum) else (stage_prefix or "")).upper()
    level_filter = level.upper() if level else None
    trace_filter = trace_id.strip() if trace_id else None

    events: list[dict[str, Any]] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line_text = line.strip()
                if not line_text:
                    continue

                if is_jsonl:
                    try:
                        parsed = json.loads(line_text)
                    except json.JSONDecodeError:
                        events.append({"raw": line_text})
                        continue
                    ev_level = str(parsed.get("level", "")).upper()
                    ev_stage = str(parsed.get("stage", "")).upper()
                    ev_trace = parsed.get("trace_id")
                    ev_details = parsed.get("details") if isinstance(parsed.get("details"), dict) else {}
                    if not _matches_filters(ev_level, ev_stage, ev_trace, ev_details, level_filter, prefix_str, trace_filter):
                        continue
                    ev_out: dict[str, Any] = {
                        "timestamp": parsed.get("timestamp", ""),
                        "level": ev_level,
                        "stage": ev_stage,
                        "message": parsed.get("message", ""),
                        "details": ev_details,
                    }
                    if ev_trace:
                        ev_out["trace_id"] = ev_trace
                    if parsed.get("screen_key"):
                        ev_out["screen_key"] = parsed["screen_key"]
                    events.append(ev_out)
                else:
                    match = _LEGACY_LINE_PATTERN.match(line_text)
                    if not match:
                        events.append({"raw": line_text})
                        continue
                    ev_level = match.group("level").strip().upper()
                    ev_stage = match.group("stage").strip().upper()
                    ev_time = match.group("timestamp").strip()
                    ev_msg = match.group("message").strip()
                    ev_det_raw = (match.group("details") or "").strip()

                    trace_match = _LEGACY_TRACE_PATTERN.search(ev_msg)
                    ev_trace = trace_match.group("trace_id") if trace_match else None

                    ev_details = {}
                    if ev_det_raw:
                        try:
                            ev_details = json.loads(ev_det_raw)
                        except Exception:
                            ev_details = {"raw_details": ev_det_raw}

                    if not _matches_filters(ev_level, ev_stage, ev_trace, ev_details, level_filter, prefix_str, trace_filter):
                        continue

                    ev_out = {
                        "timestamp": ev_time,
                        "level": ev_level,
                        "stage": ev_stage,
                        "message": ev_msg,
                        "details": ev_details,
                    }
                    if ev_trace:
                        ev_out["trace_id"] = ev_trace
                    events.append(ev_out)

                if len(events) >= limit:
                    break
    except Exception as exc:
        logger.warning("Failed to read session telemetry events", path=str(file_path), error=str(exc))

    return events


# Backward-compatible alias
_append_session_event = append_session_event
