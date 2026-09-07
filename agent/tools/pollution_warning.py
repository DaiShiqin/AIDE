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


POLLUTANT_ALIASES = {
    "PM2.5": ("PM2.5", "PM25", "PM2_5", "细颗粒物"),
    "PM10": ("PM10", "可吸入颗粒物"),
    "O3": ("O3", "臭氧"),
    "NO2": ("NO2", "二氧化氮"),
    "SO2": ("SO2", "二氧化硫"),
    "CO": ("CO", "一氧化碳"),
}


def pollution_warning(
    question: str,
    config: AgentConfig,
    session_id: str,
    *,
    pollutants_json: str | None = None,
    forecast_days_json: str | None = None,
    forecast_daily_aqi: str | None = None,
    dominant_pollutant: str | None = None,
) -> ToolResult:
    """Calculate Chengdu AQI warning guidance with the local warning skill."""
    out_dir = config.output_dir / "pollution_warning" / session_id / uuid4().hex[:8]
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = _build_payload(
        question,
        pollutants_json=pollutants_json,
        forecast_days_json=forecast_days_json,
        forecast_daily_aqi=forecast_daily_aqi,
        dominant_pollutant=dominant_pollutant,
    )
    input_path = out_dir / "pollution_warning_input.json"
    output_path = out_dir / "pollution_warning_result.json"
    input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    script = config.skills_dir / "chengdu-pollution-alerming" / "scripts" / "calculate_aqi_warning.py"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(script), "--input", str(input_path)],
        cwd=str(script.parent),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
    )
    stdout = redact_secrets(completed.stdout)
    stderr = redact_secrets(completed.stderr)
    data = _parse_json(stdout)
    if data:
        output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = _summarize_warning(data) if data else (stderr.strip() or stdout.strip())
    artifacts = [
        Artifact(kind="json", path=str(input_path.resolve()), label="污染预警输入"),
    ]
    if output_path.exists():
        artifacts.append(Artifact(kind="json", path=str(output_path.resolve()), label="污染预警研判结果"))

    return ToolResult(
        tool="pollution_warning",
        ok=completed.returncode == 0 and bool(data),
        summary=summary,
        data={
            "question": question,
            "payload": payload,
            "summary": data,
            "stdout": stdout,
            "stderr": stderr,
            "out_dir": str(out_dir.resolve()),
        },
        artifacts=artifacts,
    )


def _build_payload(
    question: str,
    *,
    pollutants_json: str | None,
    forecast_days_json: str | None,
    forecast_daily_aqi: str | None,
    dominant_pollutant: str | None,
) -> dict:
    pollutants = _parse_pollutants_json(pollutants_json) or _extract_pollutants(question)
    forecast_days = _parse_forecast_days_json(forecast_days_json)
    daily_aqi = _parse_aqi_values(forecast_daily_aqi) or _extract_daily_aqi(question)
    dominant = dominant_pollutant or _infer_dominant_pollutant(question)

    payload: dict[str, object] = {}
    if pollutants:
        payload["pollutants"] = pollutants
    if forecast_days:
        payload["forecast_days"] = forecast_days
    if daily_aqi:
        payload["forecast_daily_aqi"] = daily_aqi
    if dominant:
        payload["dominant_pollutant"] = dominant
    return payload


def _parse_forecast_days_json(value: str | None) -> list[dict[str, float]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    days = parsed.get("forecast_days", parsed) if isinstance(parsed, dict) else parsed
    if not isinstance(days, list):
        return []
    result: list[dict[str, float]] = []
    for day in days:
        if not isinstance(day, dict):
            continue
        pollutants: dict[str, float] = {}
        for key, raw in day.items():
            try:
                pollutants[str(key)] = float(raw)
            except (TypeError, ValueError):
                continue
        if pollutants:
            result.append(pollutants)
    return result


def _parse_pollutants_json(value: str | None) -> dict[str, float]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    pollutants = parsed.get("pollutants", parsed)
    if not isinstance(pollutants, dict):
        return {}
    result: dict[str, float] = {}
    for key, raw in pollutants.items():
        try:
            result[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return result


def _parse_aqi_values(value: str | None) -> list[int]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [int(round(float(item))) for item in parsed]
    except Exception:
        pass
    return [int(item) for item in re.findall(r"\d{1,3}", value) if 0 <= int(item) <= 500]


def _extract_daily_aqi(text: str) -> list[int]:
    repeated = _extract_repeated_threshold_aqi(text)
    if repeated:
        return repeated

    aqi_pos = text.upper().find("AQI")
    if aqi_pos >= 0:
        segment = text[aqi_pos : aqi_pos + 80]
        segment_values = [int(item) for item in re.findall(r"\d{2,3}", segment)]
        segment_values = [value for value in segment_values if 50 <= value <= 500]
        if len(segment_values) >= 2:
            return segment_values

    values: list[int] = []
    for match in re.finditer(r"AQI\s*(?:为|=|:|：)?\s*(\d{1,3})", text, flags=re.IGNORECASE):
        value = int(match.group(1))
        if 0 <= value <= 500:
            values.append(value)
    if values:
        return values

    if "AQI" not in text.upper():
        return []
    candidate_numbers = [int(item) for item in re.findall(r"\d{2,3}", text)]
    return [value for value in candidate_numbers if 50 <= value <= 500]


def _extract_repeated_threshold_aqi(text: str) -> list[int]:
    if "AQI" not in text.upper():
        return []
    day_count = None
    day_match = re.search(r"未来\s*([一二两三四五六七八九十\d]+)\s*天", text)
    if day_match:
        day_count = _zh_int(day_match.group(1))
    if day_count is None:
        return []

    threshold_match = re.search(r"AQI[^，。；;]{0,20}(?:都|均|全部)?\s*(超过|大于|高于|>=|≥)\s*(\d{2,3})", text, flags=re.IGNORECASE)
    if not threshold_match:
        return []
    threshold = int(threshold_match.group(2))
    if not 50 <= threshold <= 500:
        return []
    value = min(threshold + 1, 500) if threshold_match.group(1) in {"超过", "大于", "高于", ">", "≥", ">="} else threshold
    return [value] * day_count


def _zh_int(value: str) -> int | None:
    value = value.strip()
    if value.isdigit():
        return int(value)
    mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    return mapping.get(value)


def _extract_pollutants(text: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for canonical, aliases in POLLUTANT_ALIASES.items():
        for alias in aliases:
            pattern = rf"{re.escape(alias)}\s*(?:24h|8h|1h|日均|小时|浓度)?\s*(?:为|=|:|：)?\s*([0-9]+(?:\.[0-9]+)?)"
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            key = _default_pollutant_key(canonical)
            result[key] = float(match.group(1))
            break
    return result


def _default_pollutant_key(canonical: str) -> str:
    return {
        "PM2.5": "pm25_24h",
        "PM10": "pm10_24h",
        "O3": "o3_8h",
        "NO2": "no2_24h",
        "SO2": "so2_24h",
        "CO": "co_24h",
    }[canonical]


def _infer_dominant_pollutant(text: str) -> str | None:
    normalized = text.upper().replace(" ", "")
    if "O3" in normalized or "臭氧" in text:
        return "O3"
    if "PM2.5" in normalized or "PM25" in normalized or "细颗粒物" in text:
        return "PM2.5"
    if "PM10" in normalized:
        return "PM10"
    return None


def _parse_json(stdout: str) -> dict:
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


def _summarize_warning(data: dict) -> str:
    current = data.get("current_aqi") or {}
    warning = data.get("warning") or {}
    daily = data.get("forecast_daily_aqi") or []
    response_measures = data.get("response_measures")

    current_text = "未提供现况污染物浓度"
    if isinstance(current, dict) and current.get("aqi") is not None:
        current_text = f"当前AQI {current.get('aqi')}，首要污染物 {current.get('primary_pollutant')}"

    level = warning.get("warning_level") if isinstance(warning, dict) else None
    reason = warning.get("reason") if isinstance(warning, dict) else None
    measure_text = "已匹配应急响应措施" if response_measures else "未匹配到应急响应措施章节"
    return (
        f"预警结论：{level or '无法判定'}。"
        f"启动理由：{reason or '缺少未来日AQI序列或主污染物信息'}。"
        f"AQI计算：{current_text}；未来日AQI序列 {daily or '未提供'}。"
        f"{measure_text}；仍需人工会商和正式发布程序确认。"
    )
