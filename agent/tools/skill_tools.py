from __future__ import annotations

import re
from pathlib import Path

from agent.config import AgentConfig
from agent.models import ToolResult


INTERNAL_SKILLS = {"planner-core", "executor-core"}


def list_skills(config: AgentConfig, include_internal: bool = False) -> ToolResult:
    items = get_skill_inventory(config, include_internal=include_internal)
    if not items:
        return ToolResult(tool="list_skills", ok=False, summary="没有发现可用的 skill。", data={"skills": []})

    lines = [f"{item['name']}: {item['description']}" for item in items]
    return ToolResult(
        tool="list_skills",
        ok=True,
        summary="可用 skills:\n" + "\n".join(lines),
        data={"skills": items},
    )


def read_skill(skill_name: str, config: AgentConfig, section_hint: str | None = None) -> ToolResult:
    skill_dir = _find_skill_dir(config.skills_dir, skill_name)
    if skill_dir is None:
        return ToolResult(
            tool="read_skill",
            ok=False,
            summary=f"未找到 skill：{skill_name}",
            data={"skill_name": skill_name},
        )

    skill_file = skill_dir / "SKILL.md"
    content = skill_file.read_text(encoding="utf-8")
    excerpt = _extract_relevant_excerpt(content, section_hint)
    return ToolResult(
        tool="read_skill",
        ok=True,
        summary=excerpt,
        data={
            "skill_name": skill_dir.name,
            "path": str(skill_file.resolve()),
            "section_hint": section_hint or "",
        },
    )


def get_skill_inventory(config: AgentConfig, include_internal: bool = False) -> list[dict[str, str]]:
    if not config.skills_dir.exists():
        return []

    items: list[dict[str, str]] = []
    for skill_dir in sorted(path for path in config.skills_dir.iterdir() if path.is_dir()):
        if not include_internal and skill_dir.name in INTERNAL_SKILLS:
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        content = skill_file.read_text(encoding="utf-8")
        items.append(
            {
                "name": skill_dir.name,
                "description": _extract_description(content),
                "path": str(skill_file.resolve()),
            }
        )
    return items


def load_skill_context(
    config: AgentConfig,
    skill_names: list[str] | None = None,
    *,
    include_inventory: bool = False,
    max_chars_per_skill: int = 4000,
) -> str:
    blocks: list[str] = []

    if include_inventory:
        inventory = get_skill_inventory(config, include_internal=False)
        if inventory:
            lines = [f"- {item['name']}: {item['description']}" for item in inventory]
            blocks.append("## Skill Inventory\n" + "\n".join(lines))

    for skill_name in skill_names or []:
        skill_dir = _find_skill_dir(config.skills_dir, skill_name)
        if skill_dir is None:
            blocks.append(f"## Skill Missing\n- {skill_name}")
            continue
        skill_file = skill_dir / "SKILL.md"
        content = _trim_content(skill_file.read_text(encoding="utf-8"), max_chars=max_chars_per_skill)
        blocks.append(f"## Skill: {skill_dir.name}\n{content}")

    return "\n\n".join(blocks).strip()


def parse_skill_names(skill_hint: str | None) -> list[str]:
    if not skill_hint:
        return []
    names = [item.strip() for item in re.split(r"[,，\n;；]+", skill_hint) if item.strip()]
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(name)
    return ordered


def _find_skill_dir(skills_dir: Path, skill_name: str) -> Path | None:
    normalized = skill_name.strip().lower()
    direct = skills_dir / normalized
    if direct.exists():
        return direct
    for skill_dir in skills_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.lower() == normalized:
            return skill_dir
    return None


def _extract_description(content: str) -> str:
    match = re.search(r"^description:\s*(.+)$", content, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    for line in lines:
        if not line.startswith("---") and not line.startswith("#"):
            return line[:180]
    return "No description."


def _extract_relevant_excerpt(content: str, section_hint: str | None) -> str:
    if not section_hint:
        return _trim_content(content)

    sections = re.split(r"(?m)^# ", content)
    hint = section_hint.lower()
    for section in sections:
        if hint in section.lower():
            prefix = "# " if not section.startswith("# ") else ""
            return _trim_content(prefix + section)
    return _trim_content(content)


def _trim_content(content: str, max_chars: int = 2400) -> str:
    text = content.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...\n"
