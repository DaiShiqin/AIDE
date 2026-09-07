from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from agent.config import AgentConfig, redact_secrets
from agent.models import ToolResult


BANNED_PATTERNS = [
    r"\bdel\s+/s\b",
    r"\brd\s+/s\b",
    r"\brmdir\s+/s\b",
    r"\bRemove-Item\b[^\n\r;|&]*-Recurse\b",
    r"\brm\s+-rf\b",
]


@dataclass(frozen=True)
class ShellPolicy:
    requires_approval: bool
    reason: str


def classify_shell_command(command: str) -> ShellPolicy:
    for pattern in BANNED_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return ShellPolicy(True, "命令包含项目明确禁止的批量删除操作。")

    high_risk_markers = [
        "Remove-Item",
        "del ",
        " rmdir ",
        "Invoke-WebRequest",
        "curl ",
        "pip install",
        "npm install",
        "Set-ExecutionPolicy",
    ]
    if any(marker.lower() in command.lower() for marker in high_risk_markers):
        return ShellPolicy(True, "命令可能修改环境、删除文件或访问外部网络，需要人工确认。")
    return ShellPolicy(False, "低风险只读或普通诊断命令。")


def run_shell(command: str, config: AgentConfig, timeout_seconds: int = 60, approved: bool = False) -> ToolResult:
    policy = classify_shell_command(command)
    if policy.requires_approval and not approved:
        return ToolResult(
            tool="shell",
            ok=False,
            summary=f"需要人工确认：{policy.reason}",
            data={"approval_required": True, "command": command, "reason": policy.reason},
        )

    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=str(config.project_root),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    stdout = redact_secrets(completed.stdout)
    stderr = redact_secrets(completed.stderr)
    return ToolResult(
        tool="shell",
        ok=completed.returncode == 0,
        summary=stdout.strip() or stderr.strip() or f"命令退出码：{completed.returncode}",
        data={"returncode": completed.returncode, "stdout": stdout, "stderr": stderr},
    )
