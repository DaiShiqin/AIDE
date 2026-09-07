from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import default_cmaq_domain_file, default_hotspots_file, dt_text, fnum, load_cmaq_domain, load_hotspots, parse_dt, read_json, trend_label, write_json


def hotspot_regions(hotspots: list[dict]) -> set[str]:
    if not hotspots:
        return {"unknown"}
    rows = [h["row"] for h in hotspots if h.get("row") is not None]
    cols = [h["col"] for h in hotspots if h.get("col") is not None]
    if not rows or not cols:
        return {"unknown"}
    max_row = max(rows) or 1
    max_col = max(cols) or 1
    top = sorted(hotspots, key=lambda h: h.get("value") or 0, reverse=True)[: max(3, min(20, len(hotspots)))]
    mean_row = sum(h["row"] for h in top) / len(top)
    mean_col = sum(h["col"] for h in top) / len(top)
    regions = {"urban"}
    # CMAQ row/col orientation varies by preprocessing; this v1 treats high row as north.
    if mean_row >= max_row * 0.60:
        regions.add("north")
    elif mean_row <= max_row * 0.40:
        regions.add("south")
    if mean_col >= max_col * 0.60:
        regions.add("east")
    elif mean_col <= max_col * 0.40:
        regions.add("west")
    return regions


def prior_for_pollutant(met_prior: dict, pollutant: str) -> dict:
    priors = met_prior.get("pollutant_prior") or {}
    return priors.get(pollutant) or priors.get(pollutant.upper()) or priors.get("PM2.5" if pollutant.upper().startswith("PM") else "O3") or {}


def improvement_time(cmaq_rows: list[dict]) -> dict:
    if len(cmaq_rows) < 4:
        return {}
    peak_idx, peak = max(enumerate(cmaq_rows), key=lambda item: item[1]["raw_cmaq"])
    peak_value = peak["raw_cmaq"]
    drop_threshold = max(5.0, peak_value * 0.10)
    for row in cmaq_rows[peak_idx + 1 :]:
        if peak_value - row["raw_cmaq"] >= drop_threshold:
            return row
    return {}


def diagnose(cmaq_rows: list[dict], hotspots: list[dict], met_prior: dict, pollutant: str) -> dict:
    values = [r["raw_cmaq"] for r in cmaq_rows]
    cmaq_trend = trend_label(values)
    peak = max(cmaq_rows, key=lambda r: r["raw_cmaq"]) if cmaq_rows else {}
    improve = improvement_time(cmaq_rows)
    hs_regions = hotspot_regions(hotspots)

    prior = prior_for_pollutant(met_prior, pollutant)
    prior_trend = (prior.get("trend") or "unknown").lower()
    risk_areas = {str(x).lower() for x in (prior.get("risk_areas") or [])}
    if "domain" in risk_areas or "full_domain" in risk_areas:
        risk_areas.add("urban")

    if not risk_areas:
        spatial_match = True
        spatial_reason = "No explicit Windy risk area was supplied; spatial match treated as provisionally true."
    else:
        overlap = hs_regions & risk_areas
        spatial_match = bool(overlap) or ("urban" in risk_areas and "urban" in hs_regions)
        spatial_reason = f"CMAQ hotspot regions={sorted(hs_regions)}, Windy risk areas={sorted(risk_areas)}, overlap={sorted(overlap)}."

    if prior_trend in {"unknown", "", "neutral"}:
        temporal_match = True
        temporal_reason = "No explicit Windy trend was supplied; temporal match treated as provisionally true."
    else:
        temporal_match = prior_trend == cmaq_trend
        temporal_reason = f"CMAQ trend={cmaq_trend}, Windy prior trend={prior_trend}."

    prior_peak = parse_dt(prior.get("peak_time"))
    if prior_peak and peak.get("dt"):
        diff_h = abs((peak["dt"] - prior_peak).total_seconds()) / 3600.0
        if diff_h > 4:
            temporal_match = False
        temporal_reason += f" Peak-time difference={diff_h:.1f}h."
    prior_improve = parse_dt(prior.get("improvement_time"))
    if prior_improve and improve.get("dt"):
        diff_h = (prior_improve - improve["dt"]).total_seconds() / 3600.0
        if abs(diff_h) > 4:
            temporal_match = False
        if diff_h > 0:
            temporal_reason += f" CMAQ improvement appears {diff_h:.1f}h earlier than forecaster/Windy improvement node."
        else:
            temporal_reason += f" CMAQ improvement appears {-diff_h:.1f}h later than forecaster/Windy improvement node."

    if spatial_match and temporal_match:
        path = "anchor_trend"
    elif spatial_match:
        path = "time_only"
    else:
        path = "space_then_time"

    return {
        "pollutant": pollutant,
        "path": path,
        "spatial_match": spatial_match,
        "temporal_match": temporal_match,
        "spatial_reason": spatial_reason,
        "temporal_reason": temporal_reason,
        "cmaq_trend": cmaq_trend,
        "cmaq_peak_time": peak.get("datetime"),
        "cmaq_peak_value": fnum(peak.get("raw_cmaq")),
        "cmaq_improvement_time": improve.get("datetime"),
        "hotspot_regions": sorted(hs_regions),
        "windy_prior": prior,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose CMAQ spatial and temporal credibility.")
    parser.add_argument("--cmaq-dir")
    parser.add_argument("--cmaq-file")
    parser.add_argument("--hotspots-file")
    parser.add_argument("--met-prior")
    parser.add_argument("--pollutant", default="PM2.5")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    cmaq_file = Path(args.cmaq_file) if args.cmaq_file else default_cmaq_domain_file(args.cmaq_dir, args.pollutant)
    hotspots_file = Path(args.hotspots_file) if args.hotspots_file else default_hotspots_file(args.cmaq_dir, args.pollutant) if args.cmaq_dir else None
    met = read_json(args.met_prior, default={}) if args.met_prior else {}
    result = diagnose(load_cmaq_domain(cmaq_file), load_hotspots(hotspots_file), met, args.pollutant)
    write_json(args.out, result)
    print(f"Wrote diagnosis: {args.out} path={result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
