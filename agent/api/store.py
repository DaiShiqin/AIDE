from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from agent.models import AgentEvent, SessionState


@dataclass
class SessionRecord:
    state: SessionState
    queue: asyncio.Queue[AgentEvent] = field(default_factory=asyncio.Queue)
    running: bool = False
    loop: asyncio.AbstractEventLoop | None = None


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, SessionRecord] = {}

    def create(self) -> SessionRecord:
        record = SessionRecord(state=SessionState())
        self._sessions[record.state.id] = record
        return record

    def get(self, session_id: str) -> SessionRecord:
        if session_id not in self._sessions:
            raise KeyError(session_id)
        return self._sessions[session_id]

    def emit(self, event: AgentEvent) -> None:
        record = self.get(event.session_id)
        if record.loop and record.loop.is_running():
            record.loop.call_soon_threadsafe(record.queue.put_nowait, event)
        else:
            record.queue.put_nowait(event)


store = SessionStore()
