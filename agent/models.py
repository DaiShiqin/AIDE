from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Message(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class TodoStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    blocked = "blocked"


class Todo(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    status: TodoStatus = TodoStatus.pending


class PlanStep(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    tool_hint: str | None = None
    skill_hint: str | None = None
    status: TodoStatus = TodoStatus.pending


class Plan(BaseModel):
    objective: str
    steps: list[PlanStep] = Field(default_factory=list)
    rationale: str = ""
    context_variables: dict[str, Any] = Field(default_factory=dict)


class Artifact(BaseModel):
    kind: Literal["image", "csv", "json", "text", "file"]
    path: str
    label: str


class ToolResult(BaseModel):
    step_id: str | None = None
    tool: str
    ok: bool
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)


class Interrupt(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    reason: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    options: list[str] = Field(default_factory=lambda: ["approve", "edit", "reject"])


class AgentEvent(BaseModel):
    type: str
    session_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class SessionState(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    messages: list[Message] = Field(default_factory=list)
    plan: Plan | None = None
    todos: list[Todo] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    memory_notes: list[str] = Field(default_factory=list)
    context_variables: dict[str, Any] = Field(default_factory=dict)
    interrupt: Interrupt | None = None
    final_answer: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
