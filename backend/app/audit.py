"""In-memory audit trail of the decisions this service returned.

Each entry records which model produced an answer, from which inputs, and a summary of the
output, so a result shown on screen can be traced. Entries hold only hashed public IDs, the
scenario inputs and output summaries: never free text the customer typed, never source IDs.
The trail lives in process memory, is capped, and is lost on restart (prototype scope).
"""
from __future__ import annotations

import re
import threading
from collections import deque
from datetime import datetime, timezone

from . import schemas as s

MAX_ENTRIES = 2000
SESSION_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

_lock = threading.Lock()
_entries: deque[s.AuditEntry] = deque(maxlen=MAX_ENTRIES)
_seq = 0


def session_of(header: str | None) -> str | None:
    """The caller's session id if it is well formed; anything else is not recorded."""
    return header if header and SESSION_RE.match(header) else None


def record(session: str | None, endpoint: str, premise_id: str | None, inputs: dict, outputs: dict,
           model: str) -> None:
    global _seq
    if session is None:
        return
    with _lock:
        _seq += 1
        _entries.append(s.AuditEntry(seq=_seq, at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                     session=session, endpoint=endpoint, premise_id=premise_id,
                                     inputs=inputs, outputs=outputs, model=model))


def for_session(session: str) -> list[s.AuditEntry]:
    with _lock:
        return [e for e in _entries if e.session == session]


def clear() -> None:
    with _lock:
        _entries.clear()
