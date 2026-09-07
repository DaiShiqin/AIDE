#!/usr/bin/env python3
"""Calculate China AQI and Chengdu heavy-pollution warning guidance."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


AQI_POINTS = [0, 50, 100, 150, 200, 300, 400, 500]

BREAKPOINTS = {
    "pm25_24h": [0, 35, 75, 115, 150, 250, 350, 500],
    "pm10_24h": [0, 50, 150, 250, 350, 420, 500, 600],
    "so2_24h": [0, 50, 150, 475, 800, 1600, 2100, 2620],
    "so2_1h": [0, 150, 500, 650, 800, 1600, 2100, 2620],
    "no2_24h": [0, 40, 80, 180, 280, 565, 750, 940],
    "no2_1h": [0, 100, 200, 700, 1200, 2340, 3090, 3840],
    "co_24h": [0, 2, 4, 14, 24, 36, 48, 60],
    "co_1h": [0, 5, 10, 35, 60, 90, 120, 150],
    "o3_8h": [0, 100, 160, 215, 265, 800, None, None],
    "o3_1h": [0, 160, 200, 300, 400, 800, 1000, 1200],
}

DISPLAY_NAMES = {
    "pm25_24h": "PM2.5 24h",
    "pm10_24h": "PM10 24h",
    "so2_24h": "SO2 24h",
    "so2_1h": "SO2 1h",
    "no2_24h": "NO2 24h",
    "no2_1h": "NO2 1h",
    "co_24h": "CO 24h",
    "co_1h": "CO 1h",
    "o3_8h": "O3 8h",
    "o3_1h": "O3 1h",
}


def iaqi(pollutant: str, concentration: float) -> int | None:
    breakpoints = BREAKPOINTS[pollutant]
    for i in range(len(AQI_POINTS) - 1):
        c_low = breakpoints[i]
        c_high = breakpoints[i + 1]
        if c_low is None or c_high is None:
            continue
        if c_low <= concentration <= c_high:
            i_low = AQI_POINTS[i]
            i_high = AQI_POINTS[i + 1]
            value = (i_high - i_low) * (concentration - c_low) / (c_high - c_low) + i_low
            return round(value)
    if concentration > max(x for x in breakpoints if x is not None):
        return 500
    return None


def calculate_aqi(pollutants: dict[str, Any]) -> dict[str, Any]:
    iaqis: dict[str, int] = {}
    for key, raw_value in pollutants.items():
        norm_key = key.lower().replace(".", "").replace("-", "_")
        aliases = {
            "pm25": "pm25_24h",
            "pm2_5": "pm25_24h",
            "pm2_5_24h": "pm25_24h",
            "pm10": "pm10_24h",
            "so2": "so2_24h",
            "no2": "no2_24h",
            "co": "co_24h",
            "o3": "o3_8h",
            "ozone": "o3_8h",
        }
        pollutant = aliases.get(norm_key, norm_key)
        if pollutant not in BREAKPOINTS:
            continue
        value = iaqi(pollutant, float(raw_value))
        if value is not None:
            iaqis[pollutant] = value

    if not iaqis:
        return {"aqi": None, "primary_pollutant": None, "iaqis": {}}

    primary = max(iaqis, key=iaqis.get)
    return {
        "aqi": iaqis[primary],
        "primary_pollutant": DISPLAY_NAMES.get(primary, primary),
        "iaqis": {DISPLAY_NAMES.get(k, k): v for k, v in sorted(iaqis.items())},
    }


def max_consecutive(values: list[int], threshold: int) -> int:
    best = 0
    current = 0
    for value in values:
        if value > threshold:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def warning_from_daily_aqi(daily_aqi: list[int], dominant_pollutant: str | None) -> dict[str, str | None]:
    pollutant = (dominant_pollutant or "").lower().replace(".", "").replace(" ", "")
    if pollutant in {"o3", "ozone"}:
        return {
            "warning_level": "其他响应措施/O3污染",
            "reason": "O3为主污染物；预案第3.4条要求发布健康提示，并强化VOCs和NOx排放源日常监管。",
            "reference_section": "其他响应措施",
        }

    if not daily_aqi:
        return {
            "warning_level": None,
            "reason": "未提供预测日AQI序列；只能计算AQI，不能可靠判别预警启动级别。",
            "reference_section": None,
        }

    over_150 = max_consecutive(daily_aqi, 150)
    over_200 = max_consecutive(daily_aqi, 200)
    over_300 = max_consecutive(daily_aqi, 300)

    if over_200 >= 3 and over_300 >= 1:
        return {
            "warning_level": "红色预警/I级响应",
            "reason": "预测日AQI>200持续72小时，且日AQI>300持续24小时及以上。",
            "reference_section": "I级响应/红色预警",
        }
    if over_200 >= 2:
        return {
            "warning_level": "橙色预警/II级响应",
            "reason": "预测日AQI>200持续48小时，且未达到红色预警条件。",
            "reference_section": "II级响应/橙色预警",
        }
    if over_150 >= 3:
        return {
            "warning_level": "橙色预警/II级响应",
            "reason": "预测日AQI>150持续72小时及以上，且未达到红色预警条件。",
            "reference_section": "II级响应/橙色预警",
        }
    if any(value > 200 for value in daily_aqi):
        return {
            "warning_level": "黄色预警/III级响应",
            "reason": "预测日AQI>200，且未达到更高级别预警条件。",
            "reference_section": "III级响应/黄色预警",
        }
    if over_150 >= 2:
        return {
            "warning_level": "黄色预警/III级响应",
            "reason": "预测日AQI>150持续48小时及以上，且未达到更高级别预警条件。",
            "reference_section": "III级响应/黄色预警",
        }
    return {
        "warning_level": "未达到成都市重污染天气预警启动条件",
        "reason": "预测日AQI未满足黄色、橙色或红色预警阈值。",
        "reference_section": None,
    }


def load_response_measures(section: str | None) -> str | None:
    if not section:
        return None
    reference_path = Path(__file__).resolve().parents[1] / "references" / "emergency-response-measures.md"
    if not reference_path.exists():
        return None
    text = reference_path.read_text(encoding="utf-8", errors="replace")
    heading = f"## {section}"
    start = text.find(heading)
    if start < 0:
        return None
    next_heading = text.find("\n## ", start + len(heading))
    if next_heading < 0:
        next_heading = len(text)
    return text[start:next_heading].strip()


def load_payload(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return json.load(sys.stdin)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="JSON input file. Reads stdin when omitted.")
    args = parser.parse_args()

    payload = load_payload(args.input)
    current = calculate_aqi(payload.get("pollutants", {})) if payload.get("pollutants") else None

    daily_aqi: list[int] = []
    forecast_day_results: list[dict[str, Any]] = []
    if "forecast_daily_aqi" in payload:
        daily_aqi = [int(round(float(v))) for v in payload["forecast_daily_aqi"]]
    elif "forecast_days" in payload:
        for index, day in enumerate(payload["forecast_days"], start=1):
            day_result = calculate_aqi(day)
            forecast_day_results.append(
                {
                    "day_index": index,
                    "input_pollutants": day,
                    "aqi": day_result.get("aqi"),
                    "primary_pollutant": day_result.get("primary_pollutant"),
                    "iaqis": day_result.get("iaqis", {}),
                }
            )
        daily_aqi = [int(r["aqi"]) for r in forecast_day_results if r.get("aqi") is not None]
    dominant = payload.get("dominant_pollutant")
    if not dominant and current:
        dominant = current.get("primary_pollutant")

    warning = warning_from_daily_aqi(daily_aqi, dominant)
    response_measures = load_response_measures(warning.get("reference_section"))
    result = {
        "current_aqi": current,
        "forecast_daily_aqi": daily_aqi,
        "forecast_day_results": forecast_day_results,
        "warning": warning,
        "response_reference": "references/emergency-response-measures.md",
        "response_measures": response_measures,
        "notes": [
            "Colored warning judgment is threshold guidance; official release still follows Chengdu approval and会商 procedures.",
            "For O3-caused heavy pollution, use the plan's other response measures rather than forcing PM2.5 colored warning logic.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
