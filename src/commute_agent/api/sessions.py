"""In-memory conversation sessions.

Holds what Streamlit kept in `st.session_state`: the journey intent built up
so far, and the intent behind the most recent plan. HTTP is stateless, so the
frontend passes a session_id and this module supplies the continuity.

Deliberately in-process and non-durable — sessions are short-lived commute
conversations, not user accounts, and a restart losing them is acceptable.
Swapping in Redis would mean reimplementing `get`, `save`, and `reset`; every
caller goes through those three.

Not safe across multiple worker processes: two uvicorn workers each get their
own store, so a commuter's follow-up turn could land on a worker that has
never seen them. Run the API single-worker, or move this to Redis first.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from commute_agent.core.logging import get_logger

logger = get_logger(__name__)

# How long a session survives without activity, and how many we keep at once.
# Both exist to stop an unbounded dict growing forever in a long-running demo.
SESSION_TTL = timedelta(hours=2)
MAX_SESSIONS = 500


@dataclass
class Session:
    """One commuter's in-progress conversation."""

    session_id: str
    intent: dict[str, Any] = field(default_factory=dict)
    """Journey fields collected so far, including `_awaiting` bookkeeping."""

    last_planned_intent: Optional[dict[str, Any]] = None
    """Intent behind the most recent graph run, for change detection."""

    last_state: Optional[dict[str, Any]] = None
    """Most recent full AgentState — lets a reconnecting client recover the
    current plan without replanning."""

    bookings: list[dict[str, Any]] = field(default_factory=list)
    """Simulated ride bookings made during this conversation, oldest first.

    Two jobs. It lets the UI present the journey as "booked leg, then the
    replanned remainder", and it is the guard against re-offering a ride for a
    segment already booked — `booking_tool.segment_key` is the identity.

    Deliberately *not* folded into `intent`, `last_planned_intent` or
    `last_state`: booking a leg does not change what journey the commuter
    asked for, and the intake state machine's change detection reads those
    three. Keeping bookings beside them means the conversational flow behaves
    exactly as it did before this field existed."""

    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def is_expired(self) -> bool:
        return datetime.now() - self.updated_at > SESSION_TTL


class SessionStore:
    """Thread-safe session map.

    The lock guards the dict itself, not the Session objects inside it —
    handlers mutate a session then call `save()`, and concurrent turns within
    one session would interleave regardless. That's fine here: a single
    commuter doesn't send two messages at once.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: Optional[str] = None) -> Session:
        """Fetch a live session, or start one. Always returns a usable session.

        An unknown or expired id yields a fresh session under *that same id*
        rather than an error — a commuter whose session aged out during lunch
        should just get a clean slate, not a failed request.
        """
        with self._lock:
            self._evict_expired()

            if session_id:
                existing = self._sessions.get(session_id)
                if existing and not existing.is_expired:
                    return existing

            new_id = session_id or uuid.uuid4().hex
            session = Session(session_id=new_id)
            self._sessions[new_id] = session
            self._enforce_capacity()
            logger.info("Session %s created (%d active).", new_id[:8], len(self._sessions))
            return session

    def save(self, session: Session) -> None:
        session.updated_at = datetime.now()
        with self._lock:
            self._sessions[session.session_id] = session

    def reset(self, session_id: str) -> Session:
        """Clear a session's journey, keeping the id so the client can carry on."""
        with self._lock:
            session = Session(session_id=session_id)
            self._sessions[session_id] = session
            logger.info("Session %s reset.", session_id[:8])
            return session

    def _evict_expired(self) -> None:
        """Drop timed-out sessions. Caller must hold the lock."""
        stale = [sid for sid, s in self._sessions.items() if s.is_expired]
        for sid in stale:
            del self._sessions[sid]
        if stale:
            logger.info("Evicted %d expired session(s).", len(stale))

    def _enforce_capacity(self) -> None:
        """Trim oldest sessions past the cap. Caller must hold the lock."""
        overflow = len(self._sessions) - MAX_SESSIONS
        if overflow <= 0:
            return
        oldest = sorted(self._sessions.values(), key=lambda s: s.updated_at)[:overflow]
        for session in oldest:
            del self._sessions[session.session_id]
        logger.warning("Session cap reached — evicted %d oldest session(s).", overflow)


# Process-wide store. See the module docstring on multi-worker deployments.
_store = SessionStore()


def get_store() -> SessionStore:
    return _store
