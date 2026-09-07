from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from cmaq_utils import (
    DAILY_COLUMNS,
    HOURLY_COLUMNS,
    HOTSPOT_COLUMNS,
    daily_domain_stats,
    decode_times,
    find_cmaq_files,
    high_value_summary,
    hotspot_rows,
    hourly_domain_stats,
    json_print,
    netcdf_file,
    parse_metric,
    read_field,
    resolve_metric_source,
    safe_slug,
    trend_summary,
    write_csv,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract and summarize a CMAQ metric.")
    parser.add_argument("--data-dir", type=Path, help="Folder containing CMAQ .ncf files.")
    parser.add_argument("--main", type=Path, help="Main CMAQ .ncf file.")
    parser.add_argument("--extra", type=Path, help="Optional CMAQ EXTRA file.")
    parser.add_argument("--metric", required=True, help="Metric, for example PM25, O3, PM10, NO2.")
    parser.add_argument("--period-days", type=int, default=14, help="Number of forecast days to use.")
    parser.add_argument("--threshold", type=float, help="Override default high-value threshold.")
    parser.add_argument("--top-n", type=int, default=30, help="Number of hotspot rows to export.")
    parser.add_argument("--analysis", default="summary", help="Analysis label for output filenames.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output folder for CSV and JSON files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    main_path = args.main
    extra_path = args.extra
    if args.data_dir:
        found_main, found_extra = find_cmaq_files(args.data_dir)
        main_path = main_path or found_main
        extra_path = extra_path or found_extra
    if not main_path:
        raise SystemExit("No main CMAQ file found. Provide --main or --data-dir.")

    metric = parse_metric("", args.metric)
    source = resolve_metric_source(metric, main_path, extra_path)
    field = source["field"]
    threshold = args.threshold if args.threshold is not None else source.get("threshold")

    fallback_times = None
    if source["source_kind"] == "extra":
        with netcdf_file(str(main_path), "r", mmap=False) as ds:
            first_var = next(iter(ds.variables.values()))
            fallback_times = decode_times(ds, int(first_var.shape[0]))

    data, times, attrs = read_field(
        source["source_path"], field, period_days=args.period_days, fallback_times=fallback_times
    )
    unit = attrs.get("units") or source.get("unit") or ""
    hourly = hourly_domain_stats(data, times, metric, field, unit, threshold)
    daily = daily_domain_stats(hourly, metric, field, unit)
    hotspots = hotspot_rows(data, times, metric, field, unit, args.top_n)
    trend = trend_summary(daily)
    high_value = high_value_summary(hourly, daily, threshold)

    slug = f"{safe_slug(metric)}_{safe_slug(args.analysis)}"
    hourly_path = args.out_dir / f"{slug}_hourly_domain.csv"
    daily_path = args.out_dir / f"{slug}_daily_domain.csv"
    hotspots_path = args.out_dir / f"{slug}_hotspots.csv"
    summary_path = args.out_dir / f"{slug}_summary.json"

    write_csv(hourly_path, hourly, HOURLY_COLUMNS)
    write_csv(daily_path, daily, DAILY_COLUMNS)
    write_csv(hotspots_path, hotspots, HOTSPOT_COLUMNS)

    summary = {
        "metric": metric,
        "field": field,
        "unit": unit,
        "source_file": str(source["source_path"]),
        "source_kind": source["source_kind"],
        "note": source.get("note"),
        "period": {
            "start": times[0].strftime("%Y-%m-%d %H:%M:%S") if times else None,
            "end": times[-1].strftime("%Y-%m-%d %H:%M:%S") if times else None,
            "steps": len(times),
            "period_days_requested": args.period_days,
        },
        "threshold": threshold,
        "threshold_basis": source.get("threshold_basis"),
        "trend": trend,
        "high_value": high_value,
        "peak": hotspots[0] if hotspots else None,
        "outputs": {
            "hourly_domain_csv": str(hourly_path),
            "daily_domain_csv": str(daily_path),
            "hotspots_csv": str(hotspots_path),
            "summary_json": str(summary_path),
        },
    }
    write_json(summary_path, summary)
    json_print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
