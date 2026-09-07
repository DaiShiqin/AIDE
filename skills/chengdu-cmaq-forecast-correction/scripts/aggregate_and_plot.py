from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fnum, group_by, mae, read_csv, safe_float_text, write_csv

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
except Exception:  # pragma: no cover - SVG fallback still works without matplotlib
    plt = None


SVG_W = 920
SVG_H = 420


def set_fonts():
    if plt is None:
        return
    preferred = [
        "Microsoft YaHei",
        "SimHei",
        "SimSun",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Arial Unicode MS",
    ]
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in preferred:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            break
    plt.rcParams["axes.unicode_minus"] = False


def color(value, vmin, vmax):
    if value is None:
        return "#999999"
    if vmax <= vmin:
        t = 0.5
    else:
        t = max(0, min(1, (value - vmin) / (vmax - vmin)))
    r = int(40 + 210 * t)
    b = int(210 - 170 * t)
    g = int(90 + 80 * (1 - abs(t - 0.5) * 2))
    return f"#{r:02x}{g:02x}{b:02x}"


def polyline(points, xvals, yvals, xmin, xmax, ymin, ymax):
    coords = []
    left, top, width, height = 70, 30, SVG_W - 110, SVG_H - 90
    for x, y in zip(xvals, yvals):
        if y is None:
            continue
        px = left + width * ((x - xmin) / max(1, xmax - xmin))
        py = top + height * (1 - (y - ymin) / max(1e-9, ymax - ymin))
        coords.append(f"{px:.1f},{py:.1f}")
    return " ".join(coords)


def write_line_svg(path: Path, title: str, series: dict[str, list[float | None]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = max((len(v) for v in series.values()), default=0)
    xvals = list(range(n))
    vals = [v for arr in series.values() for v in arr if v is not None]
    ymin = min(vals) if vals else 0
    ymax = max(vals) if vals else 1
    if ymin == ymax:
        ymax = ymin + 1
    colors = {"raw_cmaq": "#666666", "final_corrected": "#1f77b4", "observed": "#d62728"}
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_W}" height="{SVG_H}" viewBox="0 0 {SVG_W} {SVG_H}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="70" y="22" font-size="16" font-family="Arial">{title}</text>',
        f'<line x1="70" y1="{SVG_H-60}" x2="{SVG_W-40}" y2="{SVG_H-60}" stroke="#333"/>',
        '<line x1="70" y1="30" x2="70" y2="360" stroke="#333"/>',
        f'<text x="8" y="45" font-size="11" font-family="Arial">{ymax:.1f}</text>',
        f'<text x="8" y="360" font-size="11" font-family="Arial">{ymin:.1f}</text>',
    ]
    legend_x = 70
    for name, arr in series.items():
        pts = polyline([], xvals, arr, 0, max(1, n - 1), ymin, ymax)
        c = colors.get(name, "#2ca02c")
        lines.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2"/>')
        lines.append(f'<rect x="{legend_x}" y="380" width="12" height="12" fill="{c}"/><text x="{legend_x+16}" y="391" font-size="12" font-family="Arial">{name}</text>')
        legend_x += 165
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_line_png(path: Path, title: str, series: dict[str, list[float | None]]):
    if plt is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 5), dpi=160)
    colors = {"raw_cmaq": "#666666", "final_corrected": "#1f77b4", "observed": "#d62728"}
    for name, arr in series.items():
        xvals = [i for i, value in enumerate(arr) if value is not None]
        yvals = [value for value in arr if value is not None]
        if not yvals:
            continue
        ax.plot(xvals, yvals, label=name, color=colors.get(name), linewidth=2.0)
    ax.set_title(title)
    ax.set_xlabel("Forecast hour index")
    ax.set_ylabel("Concentration")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_scatter_svg(path: Path, title: str, rows: list[dict], value_key: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    lons = [fnum(r.get("lon")) for r in rows if fnum(r.get("lon")) is not None]
    lats = [fnum(r.get("lat")) for r in rows if fnum(r.get("lat")) is not None]
    vals = [fnum(r.get(value_key)) for r in rows if fnum(r.get(value_key)) is not None]
    if not lons or not lats:
        return
    minlon, maxlon = min(lons), max(lons)
    minlat, maxlat = min(lats), max(lats)
    vmin, vmax = (min(vals), max(vals)) if vals else (0, 1)
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="560" viewBox="0 0 720 560">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="35" y="28" font-size="16" font-family="Arial">{title}</text>',
        '<rect x="50" y="45" width="620" height="455" fill="#fafafa" stroke="#999"/>',
    ]
    for r in rows:
        lon = fnum(r.get("lon"))
        lat = fnum(r.get("lat"))
        val = fnum(r.get(value_key))
        if lon is None or lat is None:
            continue
        x = 50 + 620 * (lon - minlon) / max(1e-9, maxlon - minlon)
        y = 500 - 455 * (lat - minlat) / max(1e-9, maxlat - minlat)
        c = color(val, vmin, vmax)
        label = r.get("station_name") or r.get("station_code")
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{c}" stroke="#333"><title>{label}: {safe_float_text(val,2)}</title></circle>')
    lines.append(f'<text x="50" y="532" font-size="12" font-family="Arial">min={vmin:.2f} max={vmax:.2f}</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_scatter_png(path: Path, title: str, rows: list[dict], value_key: str):
    if plt is None:
        return
    points = []
    for row in rows:
        lon = fnum(row.get("lon"))
        lat = fnum(row.get("lat"))
        val = fnum(row.get(value_key))
        if lon is None or lat is None or val is None:
            continue
        points.append((lon, lat, val, row.get("station_name") or row.get("station_code") or ""))
    if not points:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    vals = [p[2] for p in points]
    fig, ax = plt.subplots(figsize=(7.5, 6), dpi=160)
    scatter = ax.scatter(lons, lats, c=vals, cmap="coolwarm", s=70, edgecolors="#333333", linewidths=0.5)
    for lon, lat, _, label in points[:12]:
        ax.annotate(str(label), (lon, lat), xytext=(4, 4), textcoords="offset points", fontsize=7)
    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, alpha=0.2)
    fig.colorbar(scatter, ax=ax, shrink=0.85)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def aggregate(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    by_time = group_by(rows, "datetime")
    city = []
    for dt, rs in sorted(by_time.items()):
        raw = [fnum(r.get("raw_cmaq")) for r in rs if fnum(r.get("raw_cmaq")) is not None]
        corr = [fnum(r.get("final_corrected")) for r in rs if fnum(r.get("final_corrected")) is not None]
        obs = [fnum(r.get("observed")) for r in rs if fnum(r.get("observed")) is not None]
        city.append(
            {
                "datetime": dt,
                "raw_cmaq_mean": "" if not raw else f"{mean(raw):.6f}",
                "corrected_mean": "" if not corr else f"{mean(corr):.6f}",
                "observed_mean": "" if not obs else f"{mean(obs):.6f}",
                "station_count": len(rs),
                "observed_count": len(obs),
            }
        )
    station_summary = []
    for code, rs in group_by(rows, "station_code").items():
        raw_obs = [(fnum(r.get("raw_cmaq")), fnum(r.get("observed"))) for r in rs]
        cor_obs = [(fnum(r.get("final_corrected")), fnum(r.get("observed"))) for r in rs]
        observed_vals = [fnum(r.get("observed")) for r in rs if fnum(r.get("observed")) is not None]
        corrected_vals = [fnum(r.get("final_corrected")) for r in rs if fnum(r.get("final_corrected")) is not None]
        station_summary.append(
            {
                "station_code": code,
                "station_name": rs[0].get("station_name", code),
                "lon": rs[0].get("lon"),
                "lat": rs[0].get("lat"),
                "raw_mae": safe_float_text(mae(raw_obs), 4),
                "corrected_mae": safe_float_text(mae(cor_obs), 4),
                "observed_peak": safe_float_text(max(observed_vals) if observed_vals else None, 4),
                "corrected_peak": safe_float_text(max(corrected_vals) if corrected_vals else None, 4),
                "space_factor": rs[0].get("space_factor"),
            }
        )
    return city, station_summary


def make_figures(rows: list[dict], city: list[dict], station_summary: list[dict], fig_dir: Path) -> list[str]:
    fig_dir.mkdir(parents=True, exist_ok=True)
    figures = []
    city_series = {
        "raw_cmaq": [fnum(r.get("raw_cmaq_mean")) for r in city],
        "final_corrected": [fnum(r.get("corrected_mean")) for r in city],
        "observed": [fnum(r.get("observed_mean")) for r in city],
    }
    write_line_svg(fig_dir / "city_mean_timeseries.svg", "City mean: raw CMAQ / corrected / observed", city_series)
    write_line_png(fig_dir / "city_mean_timeseries.png", "City mean: raw CMAQ / corrected / observed", city_series)
    figures.extend(str(path) for path in [fig_dir / "city_mean_timeseries.png", fig_dir / "city_mean_timeseries.svg"] if path.exists())
    ranked = sorted(station_summary, key=lambda r: fnum(r.get("observed_peak"), -1) or -1, reverse=True)[:3]
    by_station = group_by(rows, "station_code")
    for s in ranked:
        code = s["station_code"]
        rs = sorted(by_station[code], key=lambda r: r["datetime"])
        path = fig_dir / f"station_{code}_timeseries.svg"
        station_series = {
            "raw_cmaq": [fnum(r.get("raw_cmaq")) for r in rs],
            "final_corrected": [fnum(r.get("final_corrected")) for r in rs],
            "observed": [fnum(r.get("observed")) for r in rs],
        }
        write_line_svg(path, f"Station {code} {s['station_name']}: raw / corrected / observed", station_series)
        png_path = fig_dir / f"station_{code}_timeseries.png"
        write_line_png(png_path, f"Station {code} {s['station_name']}: raw / corrected / observed", station_series)
        figures.extend(str(item) for item in [png_path, path] if item.exists())
    peak_rows = []
    for code, rs in by_station.items():
        max_raw = max((fnum(r.get("raw_cmaq")) for r in rs if fnum(r.get("raw_cmaq")) is not None), default=None)
        max_corr = max((fnum(r.get("final_corrected")) for r in rs if fnum(r.get("final_corrected")) is not None), default=None)
        peak_rows.append({**rs[0], "raw_peak": max_raw, "corrected_peak": max_corr, "difference_peak": None if max_raw is None or max_corr is None else max_corr - max_raw})
    for key, name in [
        ("space_factor", "spatial_factor.svg"),
        ("raw_peak", "raw_spatial_peak.svg"),
        ("corrected_peak", "corrected_spatial_peak.svg"),
        ("difference_peak", "correction_difference_spatial.svg"),
    ]:
        path = fig_dir / name
        write_scatter_svg(path, name.replace("_", " "), peak_rows, key)
        png_path = path.with_suffix(".png")
        write_scatter_png(png_path, name.replace("_", " "), peak_rows, key)
        figures.extend(str(item) for item in [png_path, path] if item.exists())
    return figures


def main() -> int:
    set_fonts()
    parser = argparse.ArgumentParser(description="Aggregate station corrections and generate SVG figures.")
    parser.add_argument("--station-corrected", required=True)
    parser.add_argument("--city-out", required=True)
    parser.add_argument("--station-summary-out", required=True)
    parser.add_argument("--fig-dir", required=True)
    parser.add_argument("--figures-out", required=True)
    args = parser.parse_args()
    rows = read_csv(args.station_corrected)
    city, station_summary = aggregate(rows)
    write_csv(args.city_out, city, ["datetime", "raw_cmaq_mean", "corrected_mean", "observed_mean", "station_count", "observed_count"])
    write_csv(args.station_summary_out, station_summary, ["station_code", "station_name", "lon", "lat", "raw_mae", "corrected_mae", "observed_peak", "corrected_peak", "space_factor"])
    figures = make_figures(rows, city, station_summary, Path(args.fig_dir))
    write_csv(args.figures_out, [{"figure": f} for f in figures], ["figure"])
    print(f"Wrote aggregate outputs and {len(figures)} figures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
