from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean


CHENGDU = {"name": "Chengdu", "lat": 30.5728, "lon": 104.0668}


def read_csv(path: str | Path) -> list[dict]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: str | Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = sorted({k for row in rows for k in row.keys()})
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: str | Path, default=None):
    if not path:
        return default
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y%m%d%H"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def dt_text(dt: datetime | None) -> str:
    return "" if dt is None else dt.strftime("%Y-%m-%d %H:%M:%S")


def fnum(value, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        if isinstance(value, str) and value.lower() in {"nan", "none", "null"}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def truthy(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是", "可用"}


def pollutant_col(pollutant: str) -> str:
    p = pollutant.upper().replace("_", "").replace(".", "")
    if p in {"PM25", "PM2.5".replace(".", "")}:
        return "PM2.5"
    if p == "O3":
        return "O3"
    raise ValueError(f"Unsupported pollutant: {pollutant}. Use PM2.5 or O3.")


def pollutant_metric(pollutant: str) -> str:
    return "PM25" if pollutant_col(pollutant) == "PM2.5" else "O3"


def find_latest(path: Path, pattern: str) -> Path | None:
    matches = sorted(path.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def default_cmaq_domain_file(cmaq_dir: str | Path, pollutant: str) -> Path:
    cmaq_dir = Path(cmaq_dir)
    metric = pollutant_metric(pollutant).lower()
    output = cmaq_dir / "output"
    candidates = [
        output / f"{metric}_trend_hourly_domain.csv",
        output / f"{metric}_summary_hourly_domain.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    found = find_latest(output, f"*{metric}*hourly*domain*.csv")
    if found:
        return found
    ncf = find_latest(cmaq_dir, "*.ncf")
    if ncf:
        raise RuntimeError(
            f"Found NetCDF CMAQ file {ncf}, but v1 fast path requires a derived hourly-domain CSV. "
            "Generate a CSV summary first or provide --cmaq-file."
        )
    raise FileNotFoundError(f"No CMAQ hourly-domain CSV found in {cmaq_dir}")


def default_hotspots_file(cmaq_dir: str | Path, pollutant: str) -> Path | None:
    cmaq_dir = Path(cmaq_dir)
    metric = pollutant_metric(pollutant).lower()
    output = cmaq_dir / "output"
    for name in (f"{metric}_trend_hotspots.csv", f"{metric}_summary_hotspots.csv"):
        path = output / name
        if path.exists():
            return path
    return find_latest(output, f"*{metric}*hotspots*.csv")


def load_cmaq_domain(path: str | Path) -> list[dict]:
    rows = []
    for row in read_csv(path):
        dt = parse_dt(row.get("datetime"))
        value = fnum(row.get("domain_mean"))
        if dt is None or value is None:
            continue
        rows.append(
            {
                "datetime": dt_text(dt),
                "dt": dt,
                "raw_cmaq": value,
                "domain_min": fnum(row.get("domain_min")),
                "domain_max": fnum(row.get("domain_max")),
                "p90": fnum(row.get("p90")),
                "p95": fnum(row.get("p95")),
            }
        )
    rows.sort(key=lambda r: r["dt"])
    return rows


def load_hotspots(path: str | Path | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    rows = []
    for row in read_csv(path):
        dt = parse_dt(row.get("datetime"))
        rows.append(
            {
                "datetime": dt_text(dt),
                "dt": dt,
                "row": fnum(row.get("row")),
                "col": fnum(row.get("col")),
                "value": fnum(row.get("value")),
                "rank": fnum(row.get("rank")),
            }
        )
    return [r for r in rows if r["dt"] and r["row"] is not None and r["col"] is not None and r["value"] is not None]


def first_value(row: dict, keys: list[str], default: str = ""):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def station_code(row: dict) -> str:
    return first_value(row, ["station_code", "监测点编码", "站点编码", "站点编号", "code"])


def station_name(row: dict) -> str:
    return first_value(row, ["station_name", "监测点名称", "站点名称", "name"], station_code(row))


def city_mean_proxy_station() -> dict:
    return {
        "station_code": "CD_CITYMEAN",
        "station_name": "Chengdu city mean proxy",
        "lon": CHENGDU["lon"],
        "lat": CHENGDU["lat"],
    }


def load_stations(obs_dir: str | Path | None = None) -> list[dict]:
    path = Path(obs_dir) / "chengdu_stations.csv" if obs_dir else None
    if not path or not path.exists():
        return [city_mean_proxy_station()]
    rows = []
    for row in read_csv(path):
        if not truthy(row.get("is_available_non_control")):
            continue
        lon = fnum(first_value(row, ["lon", "经度", "longitude"]))
        lat = fnum(first_value(row, ["lat", "纬度", "latitude"]))
        if lon is None or lat is None:
            continue
        rows.append(
            {
                "station_code": station_code(row),
                "station_name": station_name(row),
                "lon": lon,
                "lat": lat,
            }
        )
    return rows or [city_mean_proxy_station()]


def default_observation_file(obs_dir: str | Path | None) -> Path | None:
    if not obs_dir:
        return None
    obs_dir = Path(obs_dir)
    if not obs_dir.exists():
        return None
    found = find_latest(obs_dir, "chengdu_observations_site_hourly_*.csv")
    if not found:
        return None
    return found


def load_observations(obs_dir: str | Path | None, pollutant: str) -> list[dict]:
    path = default_observation_file(obs_dir)
    if not path:
        return []
    col = pollutant_col(pollutant)
    rows = []
    for row in read_csv(path):
        dt = parse_dt(row.get("datetime"))
        value = fnum(row.get(col))
        code = row.get("station_code") or row.get("监测点编码")
        if dt is None or value is None or not code:
            continue
        rows.append(
            {
                "datetime": dt_text(dt),
                "dt": dt,
                "station_code": code,
                "station_name": row.get("station_name") or row.get("监测点名称") or code,
                "observed": value,
                "lon": fnum(row.get("lon")),
                "lat": fnum(row.get("lat")),
            }
        )
    rows.sort(key=lambda r: (r["station_code"], r["dt"]))
    return rows


def group_by(rows: list[dict], key: str) -> dict:
    result = defaultdict(list)
    for row in rows:
        result[row[key]].append(row)
    return result


def trend_label(values: list[float]) -> str:
    vals = [v for v in values if v is not None]
    if len(vals) < 4:
        return "unknown"
    n = max(1, min(24, len(vals) // 4))
    first = mean(vals[:n])
    last = mean(vals[-n:])
    delta = last - first
    ref = max(5.0, abs(first) * 0.15)
    if delta > ref:
        return "increasing"
    if delta < -ref:
        return "decreasing"
    return "flat"


def nearest_hourly_met(met: dict, dt: datetime) -> dict:
    hourly = met.get("hourly") or []
    if not hourly:
        return {}
    best = None
    best_abs = None
    for row in hourly:
        hdt = parse_dt(row.get("datetime"))
        if hdt is None:
            continue
        delta = abs((hdt - dt).total_seconds())
        if best_abs is None or delta < best_abs:
            best = row
            best_abs = delta
    return best or {}


def wind_sector(deg) -> str:
    deg = fnum(deg)
    if deg is None:
        return "unknown"
    deg = deg % 360
    if deg >= 315 or deg < 45:
        return "north"
    if 45 <= deg < 135:
        return "east"
    if 135 <= deg < 225:
        return "south"
    return "west"


def classify_station_regions(stations: list[dict]) -> dict[str, set[str]]:
    lats = sorted(s["lat"] for s in stations)
    lons = sorted(s["lon"] for s in stations)
    if not lats or not lons:
        return {}
    lat_low = lats[len(lats) // 3]
    lat_high = lats[(len(lats) * 2) // 3]
    lon_low = lons[len(lons) // 3]
    lon_high = lons[(len(lons) * 2) // 3]
    regions = {}
    for s in stations:
        rs = {"urban"}
        if s["lat"] >= lat_high:
            rs.add("north")
        elif s["lat"] <= lat_low:
            rs.add("south")
        if s["lon"] >= lon_high:
            rs.add("east")
        elif s["lon"] <= lon_low:
            rs.add("west")
        regions[s["station_code"]] = rs
    return regions


def rolling_mean(values: list[float], window: int) -> list[float]:
    if window <= 1:
        return values[:]
    half = window // 2
    out = []
    for i in range(len(values)):
        subset = [v for v in values[max(0, i - half) : min(len(values), i + half + 1)] if v is not None]
        out.append(mean(subset) if subset else values[i])
    return out


def mae(pairs: list[tuple[float | None, float | None]]) -> float | None:
    errs = [abs(a - b) for a, b in pairs if a is not None and b is not None]
    return mean(errs) if errs else None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_float_text(value, digits: int = 3) -> str:
    value = fnum(value)
    return "" if value is None else f"{value:.{digits}f}"
