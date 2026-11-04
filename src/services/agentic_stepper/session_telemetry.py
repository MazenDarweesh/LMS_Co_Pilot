"""
Session Telemetry & Black-Box Event Logging Service.
Appends structured execution traces to session-specific log files and the unified debug ledger.
"""

from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
from typing import Any, Optional

ERP_LOGS_DIR = Path("logs/erp_sessions")
SHARED_LOGS_DIR = Path("e:/Mazen/shared_logs/erp_sessions")


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


def append_session_event(
    session_id: Optional[str],
    level: str,
    stage: str | TelemetryStage,
    message: str,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """
    تسجيل حدث تفصيلي في ملف الجلسة الأسود المستقل وفي السجل الجامع الموحد (AI Agent Unified Debug Ledger).
    """
    if not session_id:
        return
    clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id)
    filename = f"session_{clean_id}.log"
    iso_now = datetime.now(timezone.utc).isoformat()
    det_str = json.dumps(details or {}, ensure_ascii=False) if details else ""
    stage_str = str(stage.value if isinstance(stage, Enum) else stage).upper()
    line = f"[{iso_now}] [{level.upper()}] [{stage_str}] {message} | {det_str}\n"

    unified_filename = "agent_unified_debug.log"
    unified_line = f"[{iso_now}] [{clean_id}] [{level.upper()}] [{stage_str}] {message} | {det_str}\n"

    for target_dir in [ERP_LOGS_DIR, SHARED_LOGS_DIR]:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            # 1. ملف الجلسة المنفصل (للأرشفة المستقلة)
            with open(target_dir / filename, "a", encoding="utf-8") as f:
                f.write(line)
            # 2. ملف السجل الجامع الموحد لوكيل الذكاء الاصطناعي (AI Agent Unified Debug Ledger)
            with open(target_dir / unified_filename, "a", encoding="utf-8") as uf:
                uf.write(unified_line)
        except Exception:
            pass


def read_session_events(
    session_id: str,
    stage_prefix: Optional[str | TelemetryStage] = None,
    level: Optional[str] = None,
    limit: int = 300,
) -> list[dict[str, Any]]:
    """
    قراءة وتحليل أحداث جلسة محددة من الصندوق الأسود مع إمكانية الفلترة الهرمية.

    Args:
        session_id: معرف الجلسة.
        stage_prefix: بادئة المرحلة للفلترة (مثلاً: 'CDP' أو 'STEPPER.VERIFY').
        level: مستوى الخطورة للفلترة (INFO, WARN, ERROR).
        limit: الحد الأقصى للأحداث المسترجعة.

    Returns:
        قائمة من كائنات الأحداث المنظمة.
    """
    if not session_id:
        return []
    clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id)
    filename = f"session_{clean_id}.log"
    file_path = ERP_LOGS_DIR / filename
    if not file_path.exists():
        file_path = SHARED_LOGS_DIR / filename
        if not file_path.exists():
            return []

    prefix_str = str(stage_prefix.value if isinstance(stage_prefix, Enum) else (stage_prefix or "")).upper()
    level_filter = level.upper() if level else None

    events: list[dict[str, Any]] = []
    line_pattern = re.compile(
        r"^\[(?P<timestamp>[^\]]+)\]\s+\[(?P<level>[^\]]+)\]\s+\[(?P<stage>[^\]]+)\]\s+(?P<message>[^|]*)(?:\s*\|\s*(?P<details>.*))?$"
    )

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line_text = line.strip()
                if not line_text:
                    continue
                match = line_pattern.match(line_text)
                if not match:
                    events.append({"raw": line_text})
                    continue

                ev_level = match.group("level").strip().upper()
                ev_stage = match.group("stage").strip().upper()
                ev_time = match.group("timestamp").strip()
                ev_msg = match.group("message").strip()
                ev_det_raw = (match.group("details") or "").strip()

                if level_filter and ev_level != level_filter:
                    continue

                if prefix_str and not ev_stage.startswith(prefix_str):
                    continue

                ev_details = {}
                if ev_det_raw:
                    try:
                        ev_details = json.loads(ev_det_raw)
                    except Exception:
                        ev_details = {"raw_details": ev_det_raw}

                events.append({
                    "timestamp": ev_time,
                    "level": ev_level,
                    "stage": ev_stage,
                    "message": ev_msg,
                    "details": ev_details,
                })
                if len(events) >= limit:
                    break
    except Exception:
        pass

    return events


# Backward-compatible alias
_append_session_event = append_session_event

