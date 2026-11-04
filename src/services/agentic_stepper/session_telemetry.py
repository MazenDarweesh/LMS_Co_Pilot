"""
Session Telemetry & Black-Box Event Logging Service.
Appends structured execution traces to session-specific log files and the unified debug ledger.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Optional

ERP_LOGS_DIR = Path("logs/erp_sessions")
SHARED_LOGS_DIR = Path("e:/Mazen/shared_logs/erp_sessions")


def append_session_event(
    session_id: Optional[str],
    level: str,
    stage: str,
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
    line = f"[{iso_now}] [{level.upper()}] [{stage.upper()}] {message} | {det_str}\n"

    unified_filename = "agent_unified_debug.log"
    unified_line = f"[{iso_now}] [{clean_id}] [{level.upper()}] [{stage.upper()}] {message} | {det_str}\n"

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


# Backward-compatible alias
_append_session_event = append_session_event
