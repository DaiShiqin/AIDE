from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CHENGDU, write_json


WINDY_ENDPOINT = "https://api.windy.com/api/point-forecast/v2"


def series(raw: dict, key: str) -> list:
    value = raw.get(key)
    return value if isinstance(value, list) else []


def value_at(values: list, idx: int, default=None):
    return values[idx] if idx < len(values) else default


def wind_from_direction(u: float | None, v: float | None) -> float | None:
    if u is None or v is None:
        return None
    # Windy returns vector components toward east/north. Forecast rules use the
    # meteorological direction the wind comes from.
    return (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


def parse_windy_hourly(raw: dict, utc_offset_hours: int = 8) -> list[dict]:
    timestamps = series(raw, "ts")
    u_values = series(raw, "wind_u-surface")
    v_values = series(raw, "wind_v-surface")
    precip_values = series(raw, "past3hprecip-surface")
    rh_values = series(raw, "rh-surface")
    temp_values = series(raw, "temp-surface")
    low_clouds = series(raw, "lclouds-surface")
    mid_clouds = series(raw, "mclouds-surface")
    high_clouds = series(raw, "hclouds-surface")
    pressure_values = series(raw, "pressure-surface")
    rows = []
    for idx, ts in enumerate(timestamps):
        try:
            dt = datetime.fromtimestamp(float(ts) / 1000.0, tz=timezone.utc) + timedelta(hours=utc_offset_hours)
        except (TypeError, ValueError, OSError):
            continue
        u = value_at(u_values, idx)
        v = value_at(v_values, idx)
        wind_speed = math.hypot(u, v) if u is not None and v is not None else None
        clouds = [value_at(low_clouds, idx), value_at(mid_clouds, idx), value_at(high_clouds, idx)]
        clouds = [c for c in clouds if c is not None]
        precip_m_3h = value_at(precip_values, idx)
        rows.append(
            {
                "datetime": dt.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
                "wind_speed": None if wind_speed is None else round(wind_speed, 3),
                "wind_dir": None if u is None or v is None else round(wind_from_direction(u, v), 1),
                "precip": None if precip_m_3h is None else round(float(precip_m_3h) * 1000.0 / 3.0, 3),
                "temp": None if value_at(temp_values, idx) is None else round(float(value_at(temp_values, idx)) - 273.15, 2),
                "rh": None if value_at(rh_values, idx) is None else round(float(value_at(rh_values, idx)), 2),
                "cloud": None if not clouds else round(max(float(c) for c in clouds), 2),
                "pressure": None if value_at(pressure_values, idx) is None else round(float(value_at(pressure_values, idx)) / 100.0, 2),
            }
        )
    return rows


def build_manual_template(note: str) -> dict:
    return {
        "source": "windy_chengdu_manual_template",
        "location": CHENGDU,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "confidence": "manual_template",
        "warning": note,
        "model_agreement": "unknown",
        "run_to_run_change": {
            "large_change": False,
            "first_seen": False,
            "notes": "Set large_change=true and first_seen=true when the newest 00/12 forecast changes sharply for the first time; the correction will be held conservative pending about one day of tracking.",
        },
        "dominant_wind": {"dir": None, "speed": None},
        "short_term_signals": {
            "no2_08": None,
            "vocs_ppb": None,
            "cloud": None,
            "radiation": None,
            "notes": "For O3 nowcasting: NO2 around/under 20, VOCs within 30 ppb, afternoon southerly wind force 3+, and enough diffusion favors keeping O3 below 160.",
        },
        "manual_steps": [
            "Open https://www.windy.com/ and search Chengdu.",
            "Check ECMWF/EC wind, precipitation, cloud, temperature, humidity, and mixing conditions.",
            "Fill pollutant_prior and hourly rows before formal correction.",
        ],
        "pollutant_prior": {
            "PM2.5": {
                "trend": "unknown",
                "risk_areas": [],
                "peak_time": None,
                "improvement_time": None,
                "notes": ["Optional: secondary formation, delayed improvement, cold-air arrival, morning-peak-late"],
            },
            "O3": {
                "trend": "unknown",
                "risk_areas": [],
                "peak_time": None,
                "improvement_time": None,
                "notes": ["Optional weather type: ridge/Qinghai-high, subtropical-high, northerly transport, Deyang VOCs"],
            },
        },
        "hourly": [],
    }


def request_windy(api_key: str, lat: float, lon: float, model: str) -> dict:
    payload = {
        "lat": lat,
        "lon": lon,
        "model": model,
        "parameters": ["wind", "precip", "rh", "temp", "lclouds", "mclouds", "hclouds", "pressure"],
        "levels": ["surface"],
        "key": api_key,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(WINDY_ENDPOINT, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch or template Windy Chengdu meteorology prior.")
    parser.add_argument("--out", required=True, help="Output met_prior.json path.")
    parser.add_argument("--lat", type=float, default=CHENGDU["lat"])
    parser.add_argument("--lon", type=float, default=CHENGDU["lon"])
    parser.add_argument("--model", default="gfs")
    parser.add_argument("--utc-offset-hours", type=int, default=8)
    parser.add_argument("--template-if-missing-key", action="store_true", default=True)
    args = parser.parse_args()

    api_key = os.environ.get("WINDY_API_KEY")
    if not api_key:
        data = build_manual_template("WINDY_API_KEY is missing; fill this template from Windy.com Chengdu before formal correction.")
        write_json(args.out, data)
        print(f"WINDY_API_KEY not found. Wrote manual template: {args.out}")
        return 0

    try:
        raw = request_windy(api_key, args.lat, args.lon, args.model)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        data = build_manual_template(f"Windy API request failed: {exc}. Fill this template from Windy.com Chengdu.")
        data["api_error"] = str(exc)
        write_json(args.out, data)
        print(f"Windy API failed. Wrote manual template: {args.out}")
        return 0

    data = {
        "source": "windy_point_forecast_api",
        "location": {"name": "Chengdu", "lat": args.lat, "lon": args.lon},
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "confidence": "api_parsed_requires_review",
        "model": args.model,
        "raw_windy": raw,
        "api_warning": raw.get("warning"),
        "model_agreement": "unknown",
        "run_to_run_change": {"large_change": False, "first_seen": False, "notes": "Review 00/12 run-to-run consistency before formal correction."},
        "dominant_wind": {"dir": None, "speed": None},
        "short_term_signals": {"no2_08": None, "vocs_ppb": None, "cloud": None, "radiation": None, "notes": "Fill if O3 same-day nowcasting signals are available."},
        "pollutant_prior": {
            "PM2.5": {"trend": "unknown", "risk_areas": [], "peak_time": None, "improvement_time": None, "notes": ["Review raw_windy and set prior."]},
            "O3": {"trend": "unknown", "risk_areas": [], "peak_time": None, "improvement_time": None, "notes": ["Review raw_windy and set prior."]},
        },
        "hourly": parse_windy_hourly(raw, args.utc_offset_hours),
    }
    write_json(args.out, data)
    print(f"Wrote Windy raw prior for review: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
