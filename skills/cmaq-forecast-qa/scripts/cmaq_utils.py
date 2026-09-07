from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy.io import netcdf_file


METRIC_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "PM25": {
        "field": "PM25_TOT",
        "unit": "ug/m3",
        "threshold": 75.0,
        "threshold_basis": "daily",
        "synonyms": ["pm2.5", "pm25", "PM2.5", "PM25", "xi keli", "fine particle"],
    },
    "PM10": {
        "field": "PM10",
        "unit": "ug/m3",
        "threshold": 150.0,
        "threshold_basis": "daily",
        "synonyms": ["pm10", "PM10"],
    },
    "O3": {
        "field": "O3_UGM3",
        "extra_field": "O3_R8",
        "unit": "ug/m3",
        "threshold": 160.0,
        "threshold_basis": "8h",
        "synonyms": ["o3", "O3", "ozone"],
    },
    "CO": {
        "field": "CO_MGM3",
        "unit": "mg/m3",
        "threshold": 10.0,
        "threshold_basis": "hourly",
        "synonyms": ["co", "CO"],
    },
    "NO2": {
        "field": "NO2_UGM3",
        "unit": "ug/m3",
        "threshold": 200.0,
        "threshold_basis": "hourly",
        "synonyms": ["no2", "NO2"],
    },
    "SO2": {
        "field": "SO2_UGM3",
        "unit": "ug/m3",
        "threshold": 500.0,
        "threshold_basis": "hourly",
        "synonyms": ["so2", "SO2"],
    },
    "NH3": {
        "field": "NH3_UGM3",
        "unit": "ug/m3",
        "threshold": None,
        "threshold_basis": None,
        "synonyms": ["nh3", "NH3"],
    },
    "TEMP": {
        "field": "TEMP2",
        "unit": "C",
        "threshold": None,
        "threshold_basis": None,
        "synonyms": ["temp", "temperature"],
    },
    "RH": {
        "field": "RH",
        "unit": "%",
        "threshold": None,
        "threshold_basis": None,
        "synonyms": ["rh", "humidity"],
    },
    "WIND": {
        "field": "WSPD10",
        "unit": "m/s",
        "threshold": None,
        "threshold_basis": None,
        "synonyms": ["wind", "wind speed"],
    },
}


CHINESE_METRIC_HINTS = {
    "PM25": ["PM2.5", "pm2.5", "PM25", "pm25", "细颗粒", "细颗粒物"],
    "PM10": ["PM10", "pm10"],
    "O3": ["O3", "o3", "臭氧"],
    "CO": ["CO", "co", "一氧化碳"],
    "NO2": ["NO2", "no2", "二氧化氮"],
    "SO2": ["SO2", "so2", "二氧化硫"],
    "NH3": ["NH3", "nh3", "氨"],
    "TEMP": ["气温", "温度"],
    "RH": ["湿度", "相对湿度"],
    "WIND": ["风速", "风"],
}


def clean_attr(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace").strip()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def attrs_to_dict(attrs: Dict[str, Any]) -> Dict[str, Any]:
    return {key: clean_attr(value) for key, value in attrs.items()}


def ioapi_datetime(yyyyddd: int, hhmmss: int) -> datetime:
    year = yyyyddd // 1000
    day_of_year = yyyyddd % 1000
    hour = hhmmss // 10000
    minute = (hhmmss % 10000) // 100
    second = hhmmss % 100
    return datetime(year, 1, 1) + timedelta(
        days=day_of_year - 1, hours=hour, minutes=minute, seconds=second
    )


def tstep_to_timedelta(hhmmss: int) -> timedelta:
    hour = hhmmss // 10000
    minute = (hhmmss % 10000) // 100
    second = hhmmss % 100
    return timedelta(hours=hour, minutes=minute, seconds=second)


def variable_names(path: Path) -> List[str]:
    with netcdf_file(str(path), "r", mmap=False) as ds:
        return list(ds.variables.keys())


def decode_times(ds: netcdf_file, nsteps: int) -> List[datetime]:
    if "TFLAG" in ds.variables:
        tflag = np.array(ds.variables["TFLAG"].data[:, 0, :], copy=True)
        return [ioapi_datetime(int(row[0]), int(row[1])) for row in tflag[:nsteps]]

    attrs = attrs_to_dict(ds._attributes)
    sdate = int(attrs.get("SDATE", 1970001))
    stime = int(attrs.get("STIME", 0))
    tstep = int(attrs.get("TSTEP", 10000))
    start = ioapi_datetime(sdate, stime)
    delta = tstep_to_timedelta(tstep)
    return [start + i * delta for i in range(nsteps)]


def inspect_file(path: Path) -> Dict[str, Any]:
    with netcdf_file(str(path), "r", mmap=False) as ds:
        dims = {key: clean_attr(value) for key, value in ds.dimensions.items()}
        variables = []
        for name, var in ds.variables.items():
            variables.append(
                {
                    "name": name,
                    "dimensions": list(var.dimensions),
                    "shape": list(var.shape),
                    "dtype": str(var.data.dtype),
                    "attrs": attrs_to_dict(var._attributes),
                }
            )
        nsteps = int(variables[0]["shape"][0]) if variables else 0
        times = decode_times(ds, nsteps) if nsteps else []
        return {
            "file": str(path),
            "dimensions": dims,
            "attrs": attrs_to_dict(ds._attributes),
            "time_start": times[0].strftime("%Y-%m-%d %H:%M:%S") if times else None,
            "time_end": times[-1].strftime("%Y-%m-%d %H:%M:%S") if times else None,
            "tsteps": nsteps,
            "variables": variables,
        }


def find_cmaq_files(data_dir: Path) -> Tuple[Optional[Path], Optional[Path]]:
    candidates = sorted(data_dir.glob("*.ncf*"))
    main_files = [p for p in candidates if "EXTRA" not in p.name.upper()]
    extra_files = [p for p in candidates if "EXTRA" in p.name.upper()]
    main = max(main_files, key=lambda p: p.stat().st_size) if main_files else None
    extra = max(extra_files, key=lambda p: p.stat().st_size) if extra_files else None
    return main, extra


def parse_metric(question: str, explicit_metric: Optional[str] = None) -> str:
    if explicit_metric:
        normalized = explicit_metric.upper().replace(".", "")
        if normalized in ("PM25", "PM25_TOT"):
            return "PM25"
        if normalized in METRIC_DEFINITIONS:
            return normalized
        raise ValueError(f"Unsupported metric: {explicit_metric}")

    text = question or ""
    lowered = text.lower()
    for metric, hints in CHINESE_METRIC_HINTS.items():
        if any(hint in text for hint in hints):
            return metric
    for metric, definition in METRIC_DEFINITIONS.items():
        if any(s.lower() in lowered for s in definition["synonyms"]):
            return metric
    raise ValueError("Could not infer metric from question. Use --metric.")


def parse_analysis(question: str, explicit_analysis: Optional[str] = None) -> str:
    if explicit_analysis:
        return explicit_analysis
    text = question or ""
    lowered = text.lower()
    high_hints = ["高值", "超标", "超过", "峰值", "high", "exceed", "exceedance", "peak"]
    trend_hints = ["趋势", "变化", "trend"]
    has_high = any(hint in text or hint in lowered for hint in high_hints)
    has_trend = any(hint in text or hint in lowered for hint in trend_hints)
    if has_high and not has_trend:
        return "high_value"
    if has_trend and not has_high:
        return "trend"
    if has_high and has_trend:
        return "trend_high_value"
    return "summary"


def resolve_metric_source(
    metric: str, main_path: Path, extra_path: Optional[Path] = None
) -> Dict[str, Any]:
    definition = dict(METRIC_DEFINITIONS[metric])
    main_vars = set(variable_names(main_path))
    extra_vars = set(variable_names(extra_path)) if extra_path else set()

    if metric == "O3" and definition.get("extra_field") in extra_vars:
        return {
            **definition,
            "metric": metric,
            "field": definition["extra_field"],
            "source_path": extra_path,
            "source_kind": "extra",
            "note": "Using O3_R8 from the EXTRA file; unit is assumed from project convention if metadata is absent.",
        }

    field = definition["field"]
    if field not in main_vars:
        raise ValueError(f"Field {field} not found in main file.")
    return {
        **definition,
        "metric": metric,
        "field": field,
        "source_path": main_path,
        "source_kind": "main",
        "note": None,
    }


def read_field(
    path: Path,
    field: str,
    period_days: Optional[int] = None,
    fallback_times: Optional[Sequence[datetime]] = None,
) -> Tuple[np.ndarray, List[datetime], Dict[str, Any]]:
    with netcdf_file(str(path), "r", mmap=False) as ds:
        if field not in ds.variables:
            raise ValueError(f"Field {field} not found in {path}")
        var = ds.variables[field]
        shape = var.shape
        nsteps = int(shape[0])
        times = list(fallback_times)[:nsteps] if fallback_times else decode_times(ds, nsteps)
        if period_days:
            end = times[0] + timedelta(days=period_days)
            keep = [i for i, dt in enumerate(times) if dt < end]
            nsteps = len(keep)
            times = times[:nsteps]
        raw = np.array(var.data[:nsteps], dtype=float, copy=True)
        attrs = attrs_to_dict(var._attributes)
    if raw.ndim == 4:
        raw = raw[:, 0, :, :]
    elif raw.ndim != 3:
        raise ValueError(f"Unsupported variable shape for {field}: {shape}")
    return raw, times, attrs


def hourly_domain_stats(
    data: np.ndarray,
    times: Sequence[datetime],
    metric: str,
    field: str,
    unit: str,
    threshold: Optional[float],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    cell_count = data.shape[1] * data.shape[2]
    for idx, dt in enumerate(times):
        grid = data[idx]
        exceed_count = int(np.sum(grid > threshold)) if threshold is not None else 0
        rows.append(
            {
                "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "metric": metric,
                "field": field,
                "unit": unit,
                "domain_mean": float(np.nanmean(grid)),
                "domain_min": float(np.nanmin(grid)),
                "domain_max": float(np.nanmax(grid)),
                "p50": float(np.nanpercentile(grid, 50)),
                "p90": float(np.nanpercentile(grid, 90)),
                "p95": float(np.nanpercentile(grid, 95)),
                "exceed_grid_count": exceed_count,
                "exceed_grid_ratio": float(exceed_count / cell_count),
            }
        )
    return rows


def daily_domain_stats(
    hourly_rows: Sequence[Dict[str, Any]],
    metric: str,
    field: str,
    unit: str,
) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in hourly_rows:
        grouped.setdefault(row["datetime"][:10], []).append(row)

    daily_rows: List[Dict[str, Any]] = []
    for date, rows in sorted(grouped.items()):
        means = np.array([r["domain_mean"] for r in rows], dtype=float)
        mins = np.array([r["domain_min"] for r in rows], dtype=float)
        maxes = np.array([r["domain_max"] for r in rows], dtype=float)
        p90s = np.array([r["p90"] for r in rows], dtype=float)
        p95s = np.array([r["p95"] for r in rows], dtype=float)
        exceed_counts = np.array([r["exceed_grid_count"] for r in rows], dtype=float)
        exceed_ratios = np.array([r["exceed_grid_ratio"] for r in rows], dtype=float)
        daily_rows.append(
            {
                "date": date,
                "metric": metric,
                "field": field,
                "unit": unit,
                "daily_mean": float(np.nanmean(means)),
                "daily_min": float(np.nanmin(mins)),
                "daily_max_domain_mean": float(np.nanmax(means)),
                "daily_grid_max": float(np.nanmax(maxes)),
                "p90_max": float(np.nanmax(p90s)),
                "p95_max": float(np.nanmax(p95s)),
                "exceed_hours": int(np.sum(exceed_counts > 0)),
                "exceed_grid_count_max": int(np.nanmax(exceed_counts)),
                "exceed_grid_ratio_max": float(np.nanmax(exceed_ratios)),
            }
        )
    return daily_rows


def hotspot_rows(
    data: np.ndarray,
    times: Sequence[datetime],
    metric: str,
    field: str,
    unit: str,
    top_n: int,
) -> List[Dict[str, Any]]:
    flat = data.reshape(-1)
    top_n = max(1, min(top_n, flat.size))
    if top_n == flat.size:
        indices = np.argsort(flat)[::-1]
    else:
        indices = np.argpartition(flat, -top_n)[-top_n:]
        indices = indices[np.argsort(flat[indices])[::-1]]

    rows: List[Dict[str, Any]] = []
    for rank, flat_idx in enumerate(indices, start=1):
        t_idx, row_idx, col_idx = np.unravel_index(int(flat_idx), data.shape)
        dt = times[t_idx]
        rows.append(
            {
                "rank": rank,
                "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "date": dt.strftime("%Y-%m-%d"),
                "metric": metric,
                "field": field,
                "unit": unit,
                "row": int(row_idx),
                "col": int(col_idx),
                "value": float(data[t_idx, row_idx, col_idx]),
            }
        )
    return rows


def trend_summary(daily_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not daily_rows:
        return {}
    values = np.array([row["daily_mean"] for row in daily_rows], dtype=float)
    x = np.arange(len(values), dtype=float)
    slope = float(np.polyfit(x, values, 1)[0]) if len(values) > 1 else 0.0
    first_window = values[: min(3, len(values))]
    last_window = values[-min(3, len(values)) :]
    first_mean = float(np.nanmean(first_window))
    last_mean = float(np.nanmean(last_window))
    delta = last_mean - first_mean
    margin = max(1.0, abs(first_mean) * 0.1)

    if abs(delta) <= margin:
        label = "stable"
    elif delta > 0 and slope > 0:
        label = "increasing"
    elif delta < 0 and slope < 0:
        label = "decreasing"
    else:
        label = "fluctuating"

    peak_daily = max(daily_rows, key=lambda row: row["daily_grid_max"])
    return {
        "label": label,
        "slope_per_day": slope,
        "first_window_mean": first_mean,
        "last_window_mean": last_mean,
        "delta": float(delta),
        "days": len(daily_rows),
        "peak_daily_grid_max": {
            "date": peak_daily["date"],
            "value": peak_daily["daily_grid_max"],
        },
    }


def high_value_summary(
    hourly_rows: Sequence[Dict[str, Any]],
    daily_rows: Sequence[Dict[str, Any]],
    threshold: Optional[float],
) -> Dict[str, Any]:
    if threshold is None:
        return {"threshold": None, "has_exceedance": None}
    exceed_hours = [row for row in hourly_rows if row["exceed_grid_count"] > 0]
    exceed_days = [row for row in daily_rows if row["exceed_hours"] > 0]
    peak_hour = max(hourly_rows, key=lambda row: row["domain_max"]) if hourly_rows else None
    return {
        "threshold": threshold,
        "has_exceedance": bool(exceed_hours),
        "exceed_hour_count": len(exceed_hours),
        "exceed_day_count": len(exceed_days),
        "exceed_days": [row["date"] for row in exceed_days],
        "peak_hour_grid_max": peak_hour,
    }


def write_csv(path: Path, rows: Sequence[Dict[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col) for col in columns})


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def json_print(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def safe_slug(value: str) -> str:
    allowed = []
    for ch in value.lower():
        allowed.append(ch if ch.isalnum() else "_")
    slug = "".join(allowed).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug


HOURLY_COLUMNS = [
    "datetime",
    "metric",
    "field",
    "unit",
    "domain_mean",
    "domain_min",
    "domain_max",
    "p50",
    "p90",
    "p95",
    "exceed_grid_count",
    "exceed_grid_ratio",
]

DAILY_COLUMNS = [
    "date",
    "metric",
    "field",
    "unit",
    "daily_mean",
    "daily_min",
    "daily_max_domain_mean",
    "daily_grid_max",
    "p90_max",
    "p95_max",
    "exceed_hours",
    "exceed_grid_count_max",
    "exceed_grid_ratio_max",
]

HOTSPOT_COLUMNS = [
    "rank",
    "datetime",
    "date",
    "metric",
    "field",
    "unit",
    "row",
    "col",
    "value",
]
