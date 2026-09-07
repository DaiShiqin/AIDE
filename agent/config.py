from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


DATA_DIR = _env_path("CMAQ_DATA_DIR", PROJECT_ROOT / "data" / "cmaq")
OUTPUT_DIR = _env_path("AGENT_OUTPUT_DIR", PROJECT_ROOT / "outputs")
SKILLS_DIR = PROJECT_ROOT / "skills"
MEMORY_DIR = PROJECT_ROOT / "agent" / "memory"
AGENT_MEMORY_FILE = PROJECT_ROOT / "AGENT.md"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_web_search_provider() -> str:
    provider = os.getenv("WEB_SEARCH_PROVIDER")
    if provider:
        return provider
    if os.getenv("TAVILY_API_KEY") or os.getenv("WEB_SEARCH_API_KEY"):
        return "tavily"
    if os.getenv("SERPAPI_API_KEY") or os.getenv("SERP_API_KEY"):
        return "serpapi"
    return "stub"


@dataclass(frozen=True)
class AgentConfig:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = DATA_DIR
    output_dir: Path = OUTPUT_DIR
    skills_dir: Path = SKILLS_DIR
    memory_dir: Path = MEMORY_DIR
    agent_memory_file: Path = AGENT_MEMORY_FILE
    deepseek_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    deepseek_api_key: str | None = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY") or None)
    planner_version: str = field(default_factory=lambda: os.getenv("AGENT_PLANNER_VERSION", "v1"))
    web_search_provider: str = field(default_factory=_default_web_search_provider)
    tool_emulation: bool = field(default_factory=lambda: _env_bool("AGENT_TOOL_EMULATION", False))


def get_config() -> AgentConfig:
    return AgentConfig()


def redact_secrets(text: str | None) -> str:
    if not text:
        return ""
    redacted = text
    for key in ("DEEPSEEK_API_KEY", "TAVILY_API_KEY", "SERPAPI_API_KEY", "WINDY_API_KEY"):
        secret = os.getenv(key)
        if secret:
            redacted = redacted.replace(secret, f"<redacted:{key}>")
    return redacted
