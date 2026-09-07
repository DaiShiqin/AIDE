from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from agent.config import AgentConfig
from agent.models import ToolResult


SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
]


def extract_memory_note(text: str) -> str | None:
    triggers = ["记住", "以后", "我喜欢", "我的习惯", "优先"]
    if not any(trigger in text for trigger in triggers):
        return None
    note = text.strip()
    if len(note) > 240:
        note = note[:240] + "..."
    return note


def _safe_note(note: str) -> bool:
    if any(pattern.search(note) for pattern in SENSITIVE_PATTERNS):
        return False
    banned_delete = ["del /s", "rd /s", "rmdir /s", "Remove-Item -Recurse", "rm -rf"]
    return not any(item.lower() in note.lower() for item in banned_delete)


def record_memory(note: str, config: AgentConfig, auto_update_agent_md: bool = True) -> ToolResult:
    if not _safe_note(note):
        return ToolResult(tool="memory", ok=False, summary="记忆内容包含敏感信息或危险操作，已拒绝写入。")

    config.memory_dir.mkdir(parents=True, exist_ok=True)
    memory_file = config.memory_dir / "memory.jsonl"
    if memory_file.exists():
        existing = memory_file.read_text(encoding="utf-8")
        if f'"note": "{note}"' in existing:
            if auto_update_agent_md:
                _append_agent_memory(note, config.agent_memory_file)
            return ToolResult(
                tool="memory",
                ok=True,
                summary="该用户工作习惯已存在，未重复写入。",
                data={"memory_file": str(memory_file.resolve()), "note": note},
            )
    entry = {"created_at": datetime.now(timezone.utc).isoformat(), "note": note}
    with memory_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if auto_update_agent_md:
        _append_agent_memory(note, config.agent_memory_file)

    return ToolResult(
        tool="memory",
        ok=True,
        summary="已记录用户工作习惯。",
        data={"memory_file": str(memory_file.resolve()), "note": note},
    )


def read_memory(config: AgentConfig, limit: int = 10) -> ToolResult:
    memory_file = config.memory_dir / "memory.jsonl"
    if not memory_file.exists():
        return ToolResult(tool="read_memory", ok=True, summary="当前还没有记录用户工作习惯。", data={"notes": []})

    notes: list[str] = []
    for line in memory_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        note = str(entry.get("note", "")).strip()
        if note:
            notes.append(note)

    recent_notes = notes[-limit:]
    if not recent_notes:
        return ToolResult(tool="read_memory", ok=True, summary="当前还没有记录用户工作习惯。", data={"notes": []})
    summary = "最近的用户工作习惯：\n" + "\n".join(f"- {note}" for note in recent_notes)
    return ToolResult(tool="read_memory", ok=True, summary=summary, data={"notes": recent_notes})


def _append_agent_memory(note: str, path: Path) -> None:
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = "# 成都污染分析智能体项目记忆\n\n## 用户工作习惯\n"

    section = "## 用户工作习惯"
    line = f"- {note}"
    if line in content:
        return
    if section not in content:
        content = content.rstrip() + f"\n\n{section}\n"
    content = content.rstrip() + f"\n{line}\n"
    path.write_text(content, encoding="utf-8")
