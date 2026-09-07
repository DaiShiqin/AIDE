from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any

from agent.config import AgentConfig


@dataclass
class MiddlewareStatus:
    name: str
    enabled: bool
    reason: str


def build_langchain_middleware(config: AgentConfig) -> tuple[list[Any], list[MiddlewareStatus]]:
    try:
        from langchain.agents.middleware import (  # type: ignore
            FilesystemFileSearchMiddleware,
            LLMToolEmulator,
            SummarizationMiddleware,
        )
    except Exception as exc:  # pragma: no cover - optional dependency
        reason = f"LangChain middleware 不可用：{exc}"
        names = [
            "SummarizationMiddleware",
            "FilesystemFileSearchMiddleware",
            "LLMToolEmulator",
        ]
        return [], [MiddlewareStatus(name=name, enabled=False, reason=reason) for name in names]

    middleware: list[Any] = []
    statuses: list[MiddlewareStatus] = []

    def add(name: str, factory) -> None:
        try:
            middleware.append(factory())
            statuses.append(MiddlewareStatus(name=name, enabled=True, reason="enabled"))
        except Exception as exc:  # pragma: no cover - version specific
            statuses.append(MiddlewareStatus(name=name, enabled=False, reason=str(exc)))

    model = create_deepseek_model(config)
    if model is None:
        statuses.append(
            MiddlewareStatus(
                name="SummarizationMiddleware",
                enabled=False,
                reason="DEEPSEEK_API_KEY 未配置，无法启用基于模型的会话压缩。",
            )
        )
        statuses.append(
            MiddlewareStatus(
                name="LLMToolSelectorMiddleware",
                enabled=False,
                reason="DEEPSEEK_API_KEY 未配置，无法启用基于模型的工具筛选。",
            )
        )
    else:
        add(
            "SummarizationMiddleware",
            lambda: SummarizationMiddleware(model=model, trigger=("messages", 12), keep=("messages", 6)),
        )
        statuses.append(
            MiddlewareStatus(
                name="LLMToolSelectorMiddleware",
                enabled=False,
                reason="当前已禁用：ChatDeepSeek 与该中间件组合下会间歇返回 None，导致工具执行前中断。",
            )
        )

    if platform.system() == "Windows":
        statuses.append(
            MiddlewareStatus(
                name="FilesystemFileSearchMiddleware",
                enabled=False,
                reason="当前已禁用：Windows 环境下该中间件会触发路径模式和子进程编码兼容问题，改用内置 read_file 工具。",
            )
        )
    else:
        add(
            "FilesystemFileSearchMiddleware",
            lambda: FilesystemFileSearchMiddleware(
                root_path=str(config.project_root),
                use_ripgrep=True,
                max_file_size_mb=10,
            ),
        )

    if config.tool_emulation:
        add("LLMToolEmulator", lambda: LLMToolEmulator())
    else:
        statuses.append(MiddlewareStatus(name="LLMToolEmulator", enabled=False, reason="AGENT_TOOL_EMULATION=false"))

    return middleware, statuses


def create_deepseek_model(config: AgentConfig):
    try:
        from langchain_deepseek import ChatDeepSeek  # type: ignore
    except Exception:
        return None
    if not config.deepseek_api_key:
        return None
    return ChatDeepSeek(model=config.deepseek_model, api_key=config.deepseek_api_key)
