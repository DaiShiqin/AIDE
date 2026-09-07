from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent.config import AgentConfig
from agent.models import ToolResult


MAX_READ_CHARS = 12000


def get_current_time(config: AgentConfig) -> ToolResult:
    now = datetime.now().astimezone()
    display = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    return ToolResult(
        tool="current_time",
        ok=True,
        summary=f"当前时间为 {display}。",
        data={
            "iso": now.isoformat(),
            "display": display,
            "timezone": str(now.tzinfo or ""),
        },
    )


def read_file(
    path: str,
    config: AgentConfig,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = MAX_READ_CHARS,
) -> ToolResult:
    if not path.strip():
        return ToolResult(tool="read_file", ok=False, summary="文件路径不能为空。")

    try:
        resolved = _resolve_project_path(path, config)
    except ValueError as exc:
        return ToolResult(tool="read_file", ok=False, summary=str(exc), data={"path": path})

    if not resolved.exists():
        return ToolResult(tool="read_file", ok=False, summary=f"文件不存在：{resolved}", data={"path": str(resolved)})
    if not resolved.is_file():
        return ToolResult(tool="read_file", ok=False, summary=f"路径不是文件：{resolved}", data={"path": str(resolved)})

    content = resolved.read_text(encoding="utf-8", errors="replace")
    excerpt, line_range = _slice_content(content, start_line=start_line, end_line=end_line)
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rstrip() + "\n...\n"

    line_text = f" 行 {line_range[0]}-{line_range[1]}" if line_range else ""
    return ToolResult(
        tool="read_file",
        ok=True,
        summary=f"已读取文件 {resolved.name}{line_text}。",
        data={
            "path": str(resolved),
            "content": excerpt,
            "line_start": line_range[0] if line_range else None,
            "line_end": line_range[1] if line_range else None,
        },
    )


def _resolve_project_path(path: str, config: AgentConfig) -> Path:
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (config.project_root / candidate).resolve()
    project_root = config.project_root.resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"只允许读取项目目录内的文件：{project_root}") from exc
    return resolved


def _slice_content(content: str, start_line: int | None, end_line: int | None) -> tuple[str, tuple[int, int] | None]:
    if start_line is None and end_line is None:
        return content, None

    lines = content.splitlines()
    start = max((start_line or 1) - 1, 0)
    end = min(end_line or len(lines), len(lines))
    if start >= end:
        return "", (start + 1, end)
    return "\n".join(lines[start:end]), (start + 1, end)
