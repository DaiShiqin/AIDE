from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent.config import OUTPUT_DIR, PROJECT_ROOT, get_config
from agent.models import AgentEvent
from agent.runtime.graph import PlanAndExecuteGraph

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, StreamingResponse
except Exception as exc:  # pragma: no cover - import guard for unit tests without FastAPI
    FastAPI = None  # type: ignore
    HTTPException = None  # type: ignore
    Query = None  # type: ignore
    CORSMiddleware = None  # type: ignore
    FileResponse = None  # type: ignore
    StreamingResponse = None  # type: ignore
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None

from agent.api.store import store


class MessageRequest(BaseModel):
    content: str


class InterruptRequest(BaseModel):
    action: str
    edited_payload: dict[str, Any] | None = None


def create_app():
    if FastAPI is None:
        raise RuntimeError(f"FastAPI is not installed: {FASTAPI_IMPORT_ERROR}")

    app = FastAPI(title="AIDE: Air-quality Intelligent Decision Expert")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    graph = PlanAndExecuteGraph(get_config())

    @app.get("/api/health")
    def health():
        return {"ok": True, "project_root": str(PROJECT_ROOT), "output_dir": str(OUTPUT_DIR)}

    @app.get("/api/middleware")
    def middleware_status():
        return {"middleware": [status.__dict__ for status in graph.executor.middleware_status]}

    @app.post("/api/sessions")
    def create_session():
        record = store.create()
        return {"session_id": record.state.id, "state": record.state.model_dump()}

    @app.post("/api/sessions/{session_id}/messages")
    async def post_message(session_id: str, request: MessageRequest):
        try:
            record = store.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="session not found")
        if record.running:
            raise HTTPException(status_code=409, detail="session is already running")
        record.running = True
        record.loop = asyncio.get_running_loop()

        async def worker():
            try:
                await asyncio.to_thread(graph.run, record.state, request.content, store.emit)
            except Exception as exc:
                store.emit(
                    AgentEvent(
                        type="final",
                        session_id=session_id,
                        payload={
                            "answer": f"执行失败：{exc}",
                            "artifacts": [],
                            "error": True,
                        },
                    )
                )
            finally:
                record.running = False

        asyncio.create_task(worker())
        return {"accepted": True, "session_id": session_id}

    @app.get("/api/sessions/{session_id}/events")
    async def stream_events(session_id: str):
        try:
            record = store.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="session not found")

        async def event_generator():
            while True:
                try:
                    event = await asyncio.wait_for(record.queue.get(), timeout=20)
                    yield _sse(event)
                    if event.type == "final":
                        break
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/api/sessions/{session_id}/interrupts/{interrupt_id}")
    def resolve_interrupt(session_id: str, interrupt_id: str, request: InterruptRequest):
        try:
            record = store.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="session not found")
        if not record.state.interrupt or record.state.interrupt.id != interrupt_id:
            raise HTTPException(status_code=404, detail="interrupt not found")
        record.state.interrupt = None
        event = AgentEvent(
            type="interrupt_resolved",
            session_id=session_id,
            payload={"interrupt_id": interrupt_id, "action": request.action, "edited_payload": request.edited_payload},
        )
        store.emit(event)
        return {"ok": True}

    @app.get("/api/artifacts")
    def get_artifact(path: str = Query(...)):
        resolved = Path(path).resolve()
        allowed_roots = [OUTPUT_DIR.resolve()]
        if not any(_is_relative_to(resolved, root) for root in allowed_roots):
            raise HTTPException(status_code=403, detail="artifact path is outside allowed directories")
        if not resolved.exists() or not resolved.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(str(resolved))

    return app


def _sse(event: AgentEvent) -> str:
    payload = event.model_dump(mode="json")
    return f"event: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


app = create_app() if FastAPI is not None else None
