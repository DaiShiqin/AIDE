#!/usr/bin/env python
"""Plot CMAQ IOAPI/NetCDF variables as time series or spatial maps."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap
from scipy.io import netcdf_file


ALIASES = {
    "pm25": ["PM25_TOT", "PMIJ"],
    "pm2.5": ["PM25_TOT", "PMIJ"],
    "pm2_5": ["PM25_TOT", "PMIJ"],
    "pm10": ["PM10"],
    "o3": ["O3_UGM3", "O3_CLASSIC", "O3"],
    "ozone": ["O3_UGM3", "O3_CLASSIC", "O3"],
    "o3_8h": ["O3_R8"],
    "mda8": ["O3_R8"],
    "no2": ["NO2_UGM3", "NO2"],
    "no": ["NO_UGM3", "NO"],
    "so2": ["SO2_UGM3", "SO2"],
    "co": ["CO_MGM3", "CO"],
    "nh3": ["NH3_UGM3", "NH3"],
    "temp": ["TEMP2"],
    "temperature": ["TEMP2"],
    "rh": ["RH"],
    "wind": ["WSPD10"],
    "wspd": ["WSPD10"],
    "rain": ["RT"],
    "precip": ["RT"],
    "vis": ["VIS"],
}

NICE_NAMES = {
    "PM25_TOT": "PM2.5",
    "PM10": "PM10",
    "O3_UGM3": "O3",
    "O3_R8": "O3 8h",
    "NO2_UGM3": "NO2",
    "SO2_UGM3": "SO2",
    "CO_MGM3": "CO",
}

THRESHOLDS = {
    "PM25_TOT": [35, 75],
    "PM10": [50, 150],
    "O3_UGM3": [160, 200],
    "O3_R8": [100, 160],
    "NO2_UGM3": [100, 200],
    "SO2_UGM3": [150, 500],
    "CO_MGM3": [4, 10],
}


def decode_attr(value):
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace").strip()
    if isinstance(value, np.ndarray):
        if value.size == 1:
            return value.item()
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return value


def decode_time(date_value, time_value):
    date_value = int(date_value)
    time_value = int(time_value)
    year = date_value // 1000
    day = date_value % 1000
    hour = time_value // 10000
    minute = (time_value % 10000) // 100
    second = time_value % 100
    return datetime(year, 1, 1) + timedelta(days=day - 1, hours=hour, minutes=minute, seconds=second)


def locate_files(data_dir):
    root = Path(data_dir)
    files = sorted(root.glob("*.ncf*"))
    if not files:
        raise FileNotFoundError(f"No .ncf files found under {root}")
    main = next((p for p in files if not p.name.endswith("_EXTRA")), files[0])
    extra = next((p for p in files if p.name.endswith("_EXTRA")), None)
    return main, extra


def list_vars(path):
    with netcdf_file(str(path), "r", mmap=False) as ds:
        return list(ds.variables.keys()), {k: decode_attr(v) for k, v in ds._attributes.items()}


def choose_variable(metric, main_path, extra_path=None):
    main_vars, _ = list_vars(main_path)
    extra_vars = []
    if extra_path and Path(extra_path).exists():
        extra_vars, _ = list_vars(extra_path)

    key = metric.strip()
    candidates = ALIASES.get(key.lower(), [key])
    for candidate in candidates:
        if candidate in main_vars:
            return candidate, main_path
        if candidate in extra_vars:
            return candidate, extra_path
    for candidate in candidates:
        upper = candidate.upper()
        if upper in main_vars:
            return upper, main_path
        if upper in extra_vars:
            return upper, extra_path
    available = ", ".join([v for v in main_vars + extra_vars if v != "TFLAG"][:80])
    raise ValueError(f"Could not match metric '{metric}'. Available variables include: {available}")


def read_variable(path, var_name, fallback_times=None):
    with netcdf_file(str(path), "r", mmap=False) as ds:
        var = ds.variables[var_name]
        data = np.array(var.data, dtype=float)
        attrs = {k: decode_attr(v) for k, v in var._attributes.items()}
        gattrs = {k: decode_attr(v) for k, v in ds._attributes.items()}
        if fallback_times is not None:
            times = list(fallback_times)[: data.shape[0]]
        else:
            times = read_times(ds, data.shape[0], gattrs)
    if data.ndim == 4:
        data = data[:, 0, :, :]
    return data, attrs, gattrs, times


def fallback_times_for_extra(source_path, main_path):
    if Path(source_path).resolve() == Path(main_path).resolve():
        return None
    with netcdf_file(str(main_path), "r", mmap=False) as ds:
        first_var = next(iter(ds.variables.values()))
        return read_times(ds, int(first_var.shape[0]), {k: decode_attr(v) for k, v in ds._attributes.items()})


def read_times(ds, n_steps, gattrs):
    if "TFLAG" in ds.variables:
        tflag = np.array(ds.variables["TFLAG"].data)
        return [decode_time(tflag[i, 0, 0], tflag[i, 0, 1]) for i in range(tflag.shape[0])]
    sdate = int(gattrs.get("SDATE", 1970001))
    stime = int(gattrs.get("STIME", 0))
    tstep = int(gattrs.get("TSTEP", 10000))
    base = decode_time(sdate, stime)
    hours = max(1, tstep // 10000)
    return [base + timedelta(hours=i * hours) for i in range(n_steps)]


def inspect(data_dir):
    main, extra = locate_files(data_dir)
    result = {"main": str(main), "extra": str(extra) if extra else None, "files": []}
    for path in [p for p in [main, extra] if p]:
        variables, attrs = list_vars(path)
        result["files"].append(
            {
                "path": str(path),
                "dimensions": {k: decode_attr(v) for k, v in attrs.items() if k in ["NCOLS", "NROWS", "NLAYS", "NVARS", "SDATE", "STIME", "TSTEP"]},
                "variables": [v for v in variables if v != "TFLAG"],
            }
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def output_stem(out_dir, variable, plot_type):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    safe = variable.lower().replace(".", "")
    return Path(out_dir) / f"cmaq_{safe}_{plot_type}"


def parse_time_bound(value, *, is_end=False):
    if not value:
        return None
    text = str(value).strip()
    parsed = pd.to_datetime(text).to_pydatetime()
    if is_end and len(text) <= 10 and parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
        return parsed + timedelta(days=1) - timedelta(microseconds=1)
    return parsed


def select_time_window(data, times, start_time=None, end_time=None):
    start = parse_time_bound(start_time)
    end = parse_time_bound(end_time, is_end=True)
    indices = [
        i
        for i, timestamp in enumerate(times)
        if (start is None or timestamp >= start) and (end is None or timestamp <= end)
    ]
    if not indices:
        available = f"{times[0].isoformat(sep=' ')} to {times[-1].isoformat(sep=' ')}" if times else "empty"
        requested_start = start.isoformat(sep=" ") if start else "beginning"
        requested_end = end.isoformat(sep=" ") if end else "end"
        raise ValueError(f"No CMAQ time steps matched requested range {requested_start} to {requested_end}; available range is {available}.")
    return data[indices], [times[i] for i in indices], indices


def set_fonts():
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def plot_time_series(data, attrs, times, variable, out_dir, start_time=None, end_time=None):
    set_fonts()
    data, times, indices = select_time_window(data, times, start_time, end_time)
    mean = np.nanmean(data, axis=(1, 2))
    maxv = np.nanmax(data, axis=(1, 2))
    minv = np.nanmin(data, axis=(1, 2))
    units = attrs.get("units", "")
    name = NICE_NAMES.get(variable, variable)

    fig, ax = plt.subplots(figsize=(13, 5.8), dpi=150)
    ax.plot(times, maxv, color="#8ecae6", lw=1.3, label="Domain max")
    ax.plot(times, minv, color="#adb5bd", lw=1.0, label="Domain min")
    ax.plot(times, mean, color="#c1121f", lw=2.2, marker="o", ms=3.2, label="Domain mean")
    for threshold in THRESHOLDS.get(variable, []):
        ax.axhline(threshold, color="#e63946", ls="--", lw=1, alpha=0.75)
        ax.text(times[-1], threshold, f" {threshold:g}", color="#e63946", va="bottom", fontsize=8)
    for day in sorted({datetime(t.year, t.month, t.day) for t in times}):
        ax.axvline(day, color="0.72", ls="--", lw=0.7, alpha=0.7)

    peak_i = int(np.nanargmax(mean))
    ax.scatter([times[peak_i]], [mean[peak_i]], color="#d00000", s=28, zorder=4)
    ax.annotate(
        f"{mean[peak_i]:.1f}",
        xy=(times[peak_i], mean[peak_i]),
        xytext=(4, 8),
        textcoords="offset points",
        color="#d00000",
        fontsize=9,
        weight="bold",
    )
    ax.set_title(f"CMAQ {name} Time Series", fontsize=15, weight="bold")
    ax.set_ylabel(f"{name} ({units})" if units else name)
    ax.grid(True, color="0.90", lw=0.8)
    ax.legend(loc="upper right", ncol=3, fontsize=9, frameon=False)
    ax.set_xlim(times[0], times[-1])
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=12))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate(rotation=90, ha="center")
    fig.tight_layout()

    stem = output_stem(out_dir, variable, "time_series")
    png = stem.with_suffix(".png")
    fig.savefig(png, bbox_inches="tight")
    plt.close(fig)

    csv = Path(out_dir) / f"cmaq_{variable.lower()}_timeseries.csv"
    pd.DataFrame({"time": times, "domain_mean": mean, "domain_min": minv, "domain_max": maxv}).to_csv(csv, index=False, encoding="utf-8-sig")
    summary = {
        "plot": "time-series",
        "variable": variable,
        "units": units,
        "start": times[0].isoformat(sep=" "),
        "end": times[-1].isoformat(sep=" "),
        "time_indices": [int(indices[0]), int(indices[-1])],
        "time_step_count": len(times),
        "domain_mean_min": float(np.nanmin(mean)),
        "domain_mean_max": float(np.nanmax(mean)),
        "domain_mean_avg": float(np.nanmean(mean)),
        "peak_time": times[peak_i].isoformat(sep=" "),
        "peak_domain_mean": float(mean[peak_i]),
        "png": str(png.resolve()),
        "csv": str(csv.resolve()),
    }
    write_summary(stem, summary)
    return summary


def lambert_lonlat(gattrs, nrows, ncols):
    try:
        p_alp = math.radians(float(gattrs["P_ALP"]))
        p_bet = math.radians(float(gattrs["P_BET"]))
        p_gam = math.radians(float(gattrs["P_GAM"]))
        xcent = math.radians(float(gattrs["XCENT"]))
        ycent = math.radians(float(gattrs["YCENT"]))
        xorig = float(gattrs["XORIG"])
        yorig = float(gattrs["YORIG"])
        xcell = float(gattrs["XCELL"])
        ycell = float(gattrs["YCELL"])
    except Exception:
        return None, None

    radius = 6370000.0
    if abs(p_alp - p_bet) < 1e-10:
        n = math.sin(p_alp)
    else:
        n = math.log(math.cos(p_alp) / math.cos(p_bet)) / math.log(math.tan(math.pi / 4 + p_bet / 2) / math.tan(math.pi / 4 + p_alp / 2))
    f = math.cos(p_alp) * math.tan(math.pi / 4 + p_alp / 2) ** n / n
    rho0 = radius * f / math.tan(math.pi / 4 + ycent / 2) ** n

    x = xorig + (np.arange(ncols) + 0.5) * xcell
    y = yorig + (np.arange(nrows) + 0.5) * ycell
    xx, yy = np.meshgrid(x, y)
    rho = np.sign(n) * np.sqrt(xx * xx + (rho0 - yy) * (rho0 - yy))
    theta = np.arctan2(xx, rho0 - yy)
    lat = 2 * np.arctan((radius * f / rho) ** (1 / n)) - math.pi / 2
    lon = p_gam + theta / n
    return np.degrees(lon), np.degrees(lat)


def choose_time_index(times, time_text, time_index):
    if time_index is not None:
        return max(0, min(int(time_index), len(times) - 1))
    if time_text:
        target = pd.to_datetime(time_text).to_pydatetime()
        deltas = [abs((t - target).total_seconds()) for t in times]
        return int(np.argmin(deltas))
    return int(np.nanargmax([0])) if not times else 0


def levels_for(variable, field):
    vmax = float(np.nanpercentile(field, 98))
    if variable == "PM25_TOT":
        vmax = max(80, min(160, math.ceil(vmax / 10) * 10))
    elif variable.startswith("O3"):
        vmax = max(160, min(260, math.ceil(vmax / 10) * 10))
    elif variable == "PM10":
        vmax = max(120, min(300, math.ceil(vmax / 10) * 10))
    else:
        vmax = max(1, math.ceil(vmax))
    return np.linspace(0, vmax, 21)


def pollutant_cmap():
    return LinearSegmentedColormap.from_list(
        "cmaq_pollutant",
        ["#f7fbff", "#c6dbef", "#6baed6", "#31a354", "#ffed6f", "#fd8d3c", "#e31a1c", "#99000d"],
        N=256,
    )


def read_wind(path):
    try:
        vars_, _ = list_vars(path)
        if "WSPD10" not in vars_ or "WDIR10" not in vars_:
            return None, None
        wspd, _, _, _ = read_variable(path, "WSPD10")
        wdir, _, _, _ = read_variable(path, "WDIR10")
        rad = np.deg2rad(270 - wdir)
        return wspd * np.cos(rad), wspd * np.sin(rad)
    except Exception:
        return None, None


def plot_spatial(
    data,
    attrs,
    gattrs,
    times,
    variable,
    out_dir,
    source_path,
    time_text=None,
    time_index=None,
    start_time=None,
    end_time=None,
):
    set_fonts()
    use_window = bool(start_time or end_time or (time_text is None and time_index is None))
    indices = None
    if use_window:
        window_data, window_times, indices = select_time_window(data, times, start_time, end_time)
        field = np.nanmean(window_data, axis=0)
        idx = None
        title_prefix = "Mean"
        time_label = f"{window_times[0].strftime('%Y%m%d %H:%M')} - {window_times[-1].strftime('%Y%m%d %H:%M')}"
    else:
        idx = choose_time_index(times, time_text, time_index)
        field = data[idx]
        window_times = [times[idx]]
        title_prefix = "Hourly"
        time_label = times[idx].strftime("%Y%m%d %H:%M")
    units = attrs.get("units", "")
    name = NICE_NAMES.get(variable, variable)
    lon, lat = lambert_lonlat(gattrs, field.shape[0], field.shape[1])
    x = lon if lon is not None else np.arange(field.shape[1])[None, :].repeat(field.shape[0], axis=0)
    y = lat if lat is not None else np.arange(field.shape[0])[:, None].repeat(field.shape[1], axis=1)

    levels = levels_for(variable, field)
    cmap = pollutant_cmap()
    norm = BoundaryNorm(levels, cmap.N, clip=True)
    fig, ax = plt.subplots(figsize=(7.5, 9.5), dpi=150)
    mesh = ax.pcolormesh(x, y, field, cmap=cmap, norm=norm, shading="auto")
    ax.contour(x, y, field, levels=levels[::4], colors="k", linewidths=0.25, alpha=0.25)

    u, v = read_wind(source_path)
    if u is not None and v is not None:
        step = max(4, min(field.shape) // 22)
        if use_window and indices is not None:
            u_field = np.nanmean(u[indices], axis=0)
            v_field = np.nanmean(v[indices], axis=0)
        else:
            u_field = u[idx]
            v_field = v[idx]
        ax.quiver(x[::step, ::step], y[::step, ::step], u_field[::step, ::step], v_field[::step, ::step], color="k", alpha=0.65, scale=110, width=0.0022)

    ax.set_title(f"{title_prefix} {name}", fontsize=18, weight="bold", pad=32)
    ax.text(0.02, 1.025, "CMAQ", transform=ax.transAxes, fontsize=13, ha="left", va="bottom")
    ax.text(0.50, 1.025, time_label, transform=ax.transAxes, fontsize=12, ha="center", va="bottom")
    ax.text(0.98, 1.025, units or "", transform=ax.transAxes, fontsize=12, ha="right", va="bottom")
    ax.set_xlabel("Longitude" if lon is not None else "Column")
    ax.set_ylabel("Latitude" if lat is not None else "Row")
    ax.grid(True, color="k", alpha=0.12, lw=0.5)
    cb = fig.colorbar(mesh, ax=ax, orientation="horizontal", pad=0.10, shrink=0.86, ticks=levels[::4])
    cb.set_label(units)
    fig.tight_layout()

    stem = output_stem(out_dir, variable, "spatial")
    png = stem.with_suffix(".png")
    fig.savefig(png, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "plot": "spatial",
        "variable": variable,
        "units": units,
        "aggregation": "time_mean" if use_window else "single_time",
        "selected_time": None if use_window else times[idx].isoformat(sep=" "),
        "time_index": None if use_window else idx,
        "start": window_times[0].isoformat(sep=" "),
        "end": window_times[-1].isoformat(sep=" "),
        "time_indices": [int(indices[0]), int(indices[-1])] if indices is not None else [int(idx), int(idx)],
        "time_step_count": len(window_times),
        "field_min": float(np.nanmin(field)),
        "field_mean": float(np.nanmean(field)),
        "field_max": float(np.nanmax(field)),
        "png": str(png.resolve()),
    }
    write_summary(stem, summary)
    return summary


def write_summary(stem, summary):
    out = Path(str(stem) + "_summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_json"] = str(out.resolve())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="Directory containing CMAQ .ncf files.")
    parser.add_argument("--metric", default="PM25", help="Pollutant or CMAQ variable, e.g. PM25, O3, O3_R8, NO2_UGM3.")
    parser.add_argument("--plot", choices=["time-series", "spatial", "both"], default="time-series")
    parser.add_argument("--time", help="Explicit single target time for spatial plot, e.g. '2026-05-22 00:00'. Without this or --time-index, spatial plots use a time-mean field.")
    parser.add_argument("--time-index", type=int, help="Explicit single target time index for spatial plot. Without this or --time, spatial plots use a time-mean field.")
    parser.add_argument("--start-time", help="Start of the requested time range, e.g. '2026-05-27' or '2026-05-27 00:00'.")
    parser.add_argument("--end-time", help="End of the requested time range. Date-only values include the full day.")
    parser.add_argument("--out-dir", default="cmaq_plot_outputs", help="Output directory.")
    parser.add_argument("--inspect", action="store_true", help="Print available files and variables as JSON, then exit.")
    args = parser.parse_args()

    main_path, extra_path = locate_files(args.data_dir)
    if args.inspect:
        inspect(args.data_dir)
        return

    variable, source_path = choose_variable(args.metric, main_path, extra_path)
    fallback_times = fallback_times_for_extra(source_path, main_path)
    data, attrs, gattrs, times = read_variable(source_path, variable, fallback_times=fallback_times)
    summaries = []
    if args.plot in ["time-series", "both"]:
        summaries.append(plot_time_series(data, attrs, times, variable, args.out_dir, args.start_time, args.end_time))
    if args.plot in ["spatial", "both"]:
        summaries.append(plot_spatial(data, attrs, gattrs, times, variable, args.out_dir, main_path, args.time, args.time_index, args.start_time, args.end_time))
    print(json.dumps({"variable": variable, "source": str(source_path), "outputs": summaries}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
