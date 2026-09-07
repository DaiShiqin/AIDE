from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from agent.config import AgentConfig, redact_secrets
from agent.models import Artifact, ToolResult


OUTER_ALIASES = {
    "A": ("A", "成都平原地区", "成都平原", "CD", "成渝9kmA"),
    "B": ("B", "重庆区域", "重庆", "CQ"),
    "C": ("C", "川南地区", "川南", "CN"),
    "D": ("D", "川东北地区", "川东北", "CDB"),
    "E": ("E", "川西北区域", "川西北", "CXB"),
    "F": ("F", "攀西区域", "攀西", "PX"),
}

OUTER_NAMES = {
    "A": "成都平原地区",
    "B": "重庆区域",
    "C": "川南地区",
    "D": "川东北地区",
    "E": "川西北区域",
    "F": "攀西区域",
}

INNER_ALIASES = {
    "A": ("A", "成都主城区", "主城区"),
    "B": ("B", "成都二圈层", "二圈层"),
    "C1": ("C1", "成都郊区新城1", "郊区新城1"),
    "C2": ("C2", "成都郊区新城2", "郊区新城2"),
    "D": ("D", "德阳"),
    "E": ("E", "绵阳"),
    "F": ("F", "遂宁"),
    "G": ("G", "乐山"),
    "H": ("H", "眉山"),
    "I": ("I", "雅安"),
    "J": ("J", "资阳"),
    "K": ("K", "其他外层调整区域", "外层调整区域"),
}

INNER_NAMES = {
    "A": "成都主城区",
    "B": "成都二圈层",
    "C1": "成都郊区新城1",
    "C2": "成都郊区新城2",
    "D": "德阳",
    "E": "绵阳",
    "F": "遂宁",
    "G": "乐山",
    "H": "眉山",
    "I": "雅安",
    "J": "资阳",
    "K": "其他外层调整区域",
}

POLLUTANTS = {
    "PM2.5": "PM25",
    "PM25": "PM25",
    "PM2_5": "PM25",
    "NOX": "NOX",
    "SO2": "SO2",
    "NH3": "NH3",
    "VOC": "VOC",
}


def rsm_reduction(
    question: str,
    config: AgentConfig,
    session_id: str,
    *,
    case: int | None = None,
    outer_reduction: str | None = None,
    inner_reduction: str | None = None,
    month: int | None = None,
    dry_run: bool = False,
    no_run: bool = False,
) -> ToolResult:
    """Create a PM2.5 DeepRSM reduction case and summarize Dpm25 improvements."""
    script = config.skills_dir / "run-rsm-reduction" / "scripts" / "run_pm_reduction_case.py"
    out_dir = config.output_dir / "rsm_reduction" / session_id / uuid4().hex[:8]
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        outer_specs = _split_specs(outer_reduction)
        inner_specs = _split_specs(inner_reduction)
        if not outer_specs and not inner_specs:
            inferred_outer, inferred_inner = _infer_specs(question)
            outer_specs.extend(inferred_outer)
            inner_specs.extend(inferred_inner)
        _validate_named_region_coverage(question, outer_specs, inner_specs)
    except ValueError as exc:
        return ToolResult(tool="rsm_reduction", ok=False, summary=str(exc), data={"question": question})

    if not outer_specs and not inner_specs:
        return ToolResult(
            tool="rsm_reduction",
            ok=False,
            summary="没有识别到可写入控制矩阵的减排情景。请说明区域、污染物和减排比例，例如：成都平原地区 PM2.5 减排50%。",
            data={"question": question},
        )

    args = ["--format", "json"]
    if case is not None:
        args.extend(["--case", str(case)])
    for spec in outer_specs:
        args.extend(["--outer-reduction", spec])
    for spec in inner_specs:
        args.extend(["--inner-reduction", spec])
    if month is not None:
        args.extend(["--month", str(month)])
    if dry_run:
        args.append("--dry-run")
    if no_run:
        args.append("--no-run")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(script.parent),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=900,
    )
    stdout = redact_secrets(completed.stdout)
    stderr = redact_secrets(completed.stderr)
    data = _parse_json_from_stdout(stdout)

    summary_path = out_dir / "rsm_pm25_reduction_summary.json"
    payload = {
        "question": question,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "parsed": data,
        "outer_specs": outer_specs,
        "inner_specs": inner_specs,
        "dry_run": dry_run,
        "no_run": no_run,
    }
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if data and not dry_run and not no_run:
        summary = _summarize_rsm_result(data, question)
    elif data and dry_run:
        summary = f"RSM 减排情景 dry-run 解析成功：case{data.get('case')}，外层={outer_specs or '无'}，内层={inner_specs or '无'}。"
    elif no_run:
        summary = stdout.strip() or f"已写入 RSM 控制矩阵，但未运行模型：外层={outer_specs}，内层={inner_specs}"
    else:
        summary = stderr.strip() or stdout.strip() or f"RSM 工具退出码：{completed.returncode}"

    return ToolResult(
        tool="rsm_reduction",
        ok=completed.returncode == 0,
        summary=summary,
        data={
            "summary": data,
            "stdout": stdout,
            "stderr": stderr,
            "out_dir": str(out_dir.resolve()),
            "summary_json": str(summary_path.resolve()),
        },
        artifacts=[Artifact(kind="json", path=str(summary_path.resolve()), label="RSM PM2.5 减排摘要")],
    )


def _split_specs(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,;，；\n]+", value) if item.strip()]


def _infer_specs(question: str) -> tuple[list[str], list[str]]:
    text = question.strip()
    reduction_context = _reduction_clause(text)
    pollutants = _infer_reduction_pollutants(reduction_context)
    reduction = _infer_reduction_percent(text)
    if reduction is None:
        raise ValueError("没有识别到减排比例，请使用类似“减排50%”的表述。")

    outer_codes = _match_regions(reduction_context, OUTER_ALIASES, layer="outer")
    inner_codes = _match_regions(reduction_context, INNER_ALIASES, layer="inner")

    outer_specs = [f"{code}:{pollutant}={reduction:g}" for code in outer_codes for pollutant in pollutants]
    inner_specs = [f"{code}:{pollutant}={reduction:g}" for code in inner_codes for pollutant in pollutants]

    if not outer_specs and not inner_specs:
        raise ValueError("没有识别到区域，请使用清华网格说明中的区域名称或代码。")
    return outer_specs, inner_specs


def _infer_pollutant(text: str) -> str:
    upper = text.upper()
    for alias, canonical in POLLUTANTS.items():
        if alias in upper:
            return canonical
    return "PM25"


def _infer_reduction_pollutants(text: str) -> list[str]:
    """Return every pollutant in the reduction clause, excluding the outcome metric."""
    context = _reduction_clause(text).upper()
    pollutants: list[str] = []
    for alias, canonical in POLLUTANTS.items():
        if alias in context and canonical not in pollutants:
            pollutants.append(canonical)
    return pollutants or ["PM25"]


def _reduction_clause(text: str) -> str:
    reduction_tokens = ("减排", "削减", "降低", "减少")
    if not any(token in text for token in reduction_tokens):
        return text
    markers = ("后，对", "后,对", "后对", "后，", "后,", "后", "，计算对", ",计算对", "，评估对", ",评估对", "，对", ",对")
    positions = [text.find(marker) for marker in markers if text.find(marker) > 0]
    outcome_delimiter = re.search(r"[%％]\s*(?:后)?\s*[，,；;。]", text)
    if outcome_delimiter:
        positions.append(outcome_delimiter.end())
    return text[: min(positions)] if positions else text


def _infer_reduction_percent(text: str) -> float | None:
    verbs = r"(?:减排|削减|降低|减少)"
    patterns = [
        rf"{verbs}\s*(?:了\s*)?([0-9]+(?:\.[0-9]+)?)\s*[%％]",
        rf"([0-9]+(?:\.[0-9]+)?)\s*[%％]\s*{verbs}",
        rf"{verbs}\s*(?:了\s*)?([0-9]+(?:\.[0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = float(match.group(1))
            if value <= 1:
                value *= 100
            if 0 <= value <= 100:
                return value
            raise ValueError(f"减排比例应在 0% 到 100% 之间，当前是 {value:g}%。")
    return None


def _match_regions(text: str, alias_map: dict[str, tuple[str, ...]], *, layer: str) -> list[str]:
    upper = text.upper()
    matches: list[str] = []
    for code, aliases in alias_map.items():
        found = False
        for alias in aliases:
            if alias == code:
                continue
            if _is_ascii(alias):
                found = bool(re.search(rf"(?<![A-Z0-9]){re.escape(alias.upper())}(?![A-Z0-9])", upper))
            else:
                found = alias in text
            if found:
                break
        if not found:
            layer_tokens = ("外层", "9KM", "成渝9") if layer == "outer" else ("内层", "3KM", "成渝3")
            code_pattern = re.compile(rf"(?:{'|'.join(layer_tokens)})[^，,；;。]{{0,12}}?{re.escape(code)}(?:区|区域)?", re.IGNORECASE)
            found = bool(code_pattern.search(upper))
        if found:
            matches.append(code)
    return matches


def _validate_named_region_coverage(question: str, outer_specs: list[str], inner_specs: list[str]) -> None:
    reduction_context = _reduction_clause(question)
    outer_codes = {_spec_region(spec) for spec in outer_specs}
    if "重庆" in reduction_context and any(_spec_region(spec) == "K" for spec in inner_specs):
        raise ValueError("RSM 区域映射不一致：重庆是外层 B 区，内层 K 是其他外层调整区域，不能作为重庆使用。")

    required = {
        "成都平原": "A",
        "重庆": "B",
        "川南": "C",
        "川东北": "D",
        "川西北": "E",
        "攀西": "F",
    }
    for name, code in required.items():
        if name in reduction_context and code not in outer_codes:
            raise ValueError(f"RSM 区域映射不一致：{name}应写入外层 {code} 区，当前外层参数为 {outer_specs or '无'}。")


def _spec_region(spec: str) -> str:
    return spec.split(":", 1)[0].strip().upper()


def _is_ascii(text: str) -> bool:
    return all(ord(char) < 128 for char in text)


def _parse_json_from_stdout(stdout: str) -> dict:
    text = stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
    return {}


def _summarize_rsm_result(data: dict, question: str | None = None) -> str:
    case = data.get("case")
    records = data.get("records") if isinstance(data.get("records"), list) else []
    means = data.get("mean_improvement") if isinstance(data.get("mean_improvement"), dict) else {}
    months = ", ".join(str(record.get("month")) for record in records if isinstance(record, dict) and record.get("month"))
    if not means:
        return f"RSM case{case} 已完成，但没有解析到 Dpm25 改善量。"
    scenario_lines: list[str] = []
    for item in data.get("outer_reductions") or []:
        code = str(item.get("region") or "")
        pct = float(item.get("reduction_fraction") or 0) * 100
        scenario_lines.append(f"外层 {code} {OUTER_NAMES.get(code, code)} {item.get('pollutant')} 减排 {pct:g}%")
    for item in data.get("inner_reductions") or []:
        code = str(item.get("region") or "")
        pct = float(item.get("reduction_fraction") or 0) * 100
        scenario_lines.append(f"内层 {code} {INNER_NAMES.get(code, code)} {item.get('pollutant')} 减排 {pct:g}%")
    available = [
        (code, name, float(means[code]))
        for code, name in INNER_NAMES.items()
        if means.get(code) is not None
    ]
    positive = [item for item in available if item[2] > 0]
    ranked = sorted(positive, key=lambda item: item[2], reverse=True)
    outcome_context = ""
    if question:
        reduction_context = _reduction_clause(question)
        outcome_context = question[len(reduction_context) :]
    target_codes = _match_regions(outcome_context, INNER_ALIASES, layer="inner") if outcome_context else []
    target_code = next((code for code in target_codes if means.get(code) is not None), None)

    if target_code:
        conclusion = f"{INNER_NAMES[target_code]} PM2.5 的 Dpm25 模型改善量为 `{float(means[target_code]):.3f}`"
    elif ranked:
        conclusion = f"{len(positive)}/{len(available)} 个内层区域呈正改善，{ranked[0][1]}响应最大（`{ranked[0][2]:.3f}`）"
    else:
        conclusion = "本情景未得到正的 Dpm25 模型改善量"
    if target_code and ranked and ranked[0][0] != target_code:
        conclusion += f"；12 个内层区域中，{ranked[0][1]}响应最大（`{ranked[0][2]:.3f}`）"

    month_count = len([record for record in records if isinstance(record, dict) and record.get("month")])
    month_scope = months or "未识别"
    if month_count:
        month_scope += f"（{month_count} 个模型输出时段）"

    def region_group(codes: tuple[str, ...]) -> str:
        return "；".join(
            f"{INNER_NAMES[code]} `{float(means[code]):.3f}`"
            for code in codes
            if means.get(code) is not None
        )

    top_text = "；".join(f"{name} `{value:.3f}`" for _, name, value in ranked[:3]) or "无正改善区域"
    lines = [
        "## RSM 情景评估结果",
        "",
        f"**核心结论：{conclusion}。**",
        "",
        "### 情景设置",
        f"- **算例**：case{case}",
        f"- **排放控制**：{'；'.join(scenario_lines) or '未识别'}",
        f"- **读取时段**：{month_scope}",
        "",
        "### 12 个内层区域改善量",
        f"- **成都区域**：{region_group(('A', 'B', 'C1', 'C2'))}",
        f"- **成都周边城市**：{region_group(('D', 'E', 'F', 'G', 'H', 'I', 'J'))}",
        f"- **其他调整区域**：{region_group(('K',))}",
        "",
        "### 结果解读",
        f"- **响应较大的区域**：{top_text}",
        f"- **总体方向**：{len(positive)}/{len(available)} 个区域为正改善量。",
        "- **计算口径**：改善量为 `baseline - scenario`；减排百分比是排放控制比例，不是 PM2.5 浓度同比下降比例。",
        "- **时段与单位**：上述结果是对已读取输出时段的简单平均，不自动等同于日历年均值；源文件未附单位，因此按 Dpm25 模型输出值报告。",
        "- **解释边界**：仅凭响应数值不能判断传输方向、当地排放贡献或地形作用等具体成因。",
    ]
    return "\n".join(lines)
