from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    clamp,
    classify_station_regions,
    default_cmaq_domain_file,
    dt_text,
    fnum,
    group_by,
    load_cmaq_domain,
    load_observations,
    load_stations,
    nearest_hourly_met,
    parse_dt,
    pollutant_col,
    read_json,
    wind_sector,
    write_csv,
    write_json,
)


def prior_for_pollutant(met_prior: dict, pollutant: str) -> dict:
    p = pollutant_col(pollutant)
    priors = met_prior.get("pollutant_prior") or {}
    return priors.get(p) or priors.get("PM2.5" if p == "PM2.5" else "O3") or {}


def prior_notes(prior: dict) -> str:
    return " ".join(str(x) for x in (prior.get("notes") or [])).lower()


def confidence_strength(met_prior: dict) -> tuple[float, list[str]]:
    """Shrink empirical factors when the forecaster signal is explicitly uncertain."""
    reasons = []
    strength = 1.0
    agreement = str(met_prior.get("model_agreement") or met_prior.get("multi_model_agreement") or "").lower()
    if agreement in {"high", "strong", "consistent", "吻合", "一致"}:
        reasons.append("multi-model weather pattern agreement is high; model trend is trusted")
    elif agreement in {"low", "weak", "divergent", "不吻合", "分歧"}:
        strength *= 0.75
        reasons.append("multi-model weather pattern agreement is low; empirical factors are made conservative")
    run_change = met_prior.get("run_to_run_change") or {}
    if run_change.get("large_change") and run_change.get("first_seen", True):
        strength *= 0.50
        reasons.append("latest 00/12 forecast changed sharply for the first time; hold only half correction pending one-day tracking")
    return strength, reasons


def apply_strength(factor: float, strength: float) -> float:
    return 1.0 + (factor - 1.0) * strength


def o3_rescue_day(met_prior: dict, dt, met_row: dict, start_dt) -> tuple[bool, list[str]]:
    signals = met_prior.get("short_term_signals") or {}
    no2 = fnum(signals.get("no2_08") or signals.get("morning_no2"))
    vocs = fnum(signals.get("vocs_ppb") or signals.get("morning_vocs_ppb"))
    wind = fnum(met_row.get("wind_speed"))
    cloud = fnum(met_row.get("cloud"))
    sector = wind_sector(met_row.get("wind_dir"))
    reasons = []
    if no2 is not None and vocs is not None and no2 <= 20 and vocs <= 30 and sector == "south" and wind is not None and wind >= 3.4:
        if cloud is None or cloud <= 60:
            reasons.append("O3 short-term rescue rule: 08:00 NO2<=20, VOCs<=30 ppb, afternoon southerly wind force 3+")
            return True, reasons
    prior = prior_for_pollutant(met_prior, "O3")
    notes = prior_notes(prior)
    pbl = fnum(met_row.get("pbl") or met_row.get("pblh") or met_row.get("boundary_layer_height"))
    first_48h = start_dt is None or (dt - start_dt).total_seconds() <= 48 * 3600
    if first_48h and ("高脊" in notes or "青高" in notes or "ridge" in notes or "qinghai" in notes):
        if (pbl is None or pbl >= 1200) and sector == "south" and wind is not None and 1.5 <= wind <= 5.5:
            reasons.append("ridge/Qinghai-high sunny case with PBL>=1200 m and grade 2-3 southerly wind; early O3 can stay below 160")
            return True, reasons
    return False, reasons


def met_time_factor(pollutant: str, dt, met_row: dict, met_prior: dict | None = None, include_routine: bool = True) -> tuple[float, list[str]]:
    met_prior = met_prior or {}
    prior = prior_for_pollutant(met_prior, pollutant)
    notes = prior_notes(prior)
    p = pollutant_col(pollutant)
    hour = dt.hour
    wind = fnum(met_row.get("wind_speed"))
    rh = fnum(met_row.get("rh"))
    precip = fnum(met_row.get("precip"), 0.0)
    temp = fnum(met_row.get("temp"))
    cloud = fnum(met_row.get("cloud"))
    factor = 1.0
    reasons = []
    if p == "PM2.5":
        if include_routine:
            factor *= 0.95
            reasons.append("PM2.5 routine Chengdu high-bias light correction 0.95")
        if precip is not None and precip >= 0.5:
            factor *= 0.85
            reasons.append("precipitation wet-scavenging correction 0.85")
        if wind is not None and wind >= 4:
            factor *= 0.85
            reasons.append("sustained dispersive wind correction 0.85")
        improvement_time = parse_dt(prior.get("improvement_time"))
        if improvement_time and dt < improvement_time and (wind is None or wind < 4):
            factor *= 1.08
            reasons.append("forecaster-delayed PM2.5 improvement node; maintain concentration before confirmed dispersive wind")
        if 8 <= hour <= 12 and (wind is None or wind < 4) and (precip is None or precip < 0.5):
            factor *= 1.06
            reasons.append("PM2.5 morning peak often occurs after rush hour; raise late-morning hours 1.06")
        if (20 <= hour or hour <= 8) and wind is not None and wind <= 2 and rh is not None and rh >= 75:
            factor *= 1.10
            reasons.append("nighttime weak-wind high-RH accumulation correction 1.10")
        if "secondary" in notes or "二次" in notes:
            factor *= 1.08
            reasons.append("secondary PM2.5 formation may be underestimated during rapid pollution jumps 1.08")
        strength, strength_reasons = confidence_strength(met_prior)
        factor = apply_strength(factor, strength)
        return clamp(factor, 0.70, 1.25), reasons + strength_reasons

    if include_routine:
        factor *= 1.05
        reasons.append("O3 routine Chengdu low-bias light correction 1.05")
    if precip is not None and precip >= 0.5:
        factor *= 0.90
        reasons.append("rain/cloud O3 suppression correction 0.90")
    if 13 <= hour <= 18 and temp is not None and temp >= 28 and (cloud is None or cloud <= 50) and (wind is None or wind <= 3):
        factor *= 1.15
        reasons.append("afternoon photochemical O3 enhancement correction 1.15")
    if wind_sector(met_row.get("wind_dir")) == "north":
        factor *= 1.08
        reasons.append("northerly transport O3 correction 1.08")
    if "副高" in notes or "subtropical" in notes:
        factor *= 1.10
        reasons.append("subtropical-high humid stagnant O3 high-value risk correction 1.10")
    if "高脊" in notes or "青高" in notes or "ridge" in notes or "qinghai" in notes:
        factor *= 0.97
        reasons.append("ridge/Qinghai-high case has good diffusion despite fast production; keep O3 correction conservative 0.97")
    strength, strength_reasons = confidence_strength(met_prior)
    factor = apply_strength(factor, strength)
    return clamp(factor, 0.75, 1.35), reasons + strength_reasons


def station_space_factor(pollutant: str, station_regions: set[str], met_prior: dict, path: str) -> tuple[float, list[str]]:
    p = pollutant_col(pollutant)
    factor = 1.0
    reasons = []
    prior = (met_prior.get("pollutant_prior") or {}).get(p) or (met_prior.get("pollutant_prior") or {}).get("PM2.5" if p == "PM2.5" else "O3") or {}
    risk = {str(x).lower() for x in (prior.get("risk_areas") or [])}
    notes = " ".join(prior.get("notes") or []).lower()
    if p == "PM2.5":
        factor *= 0.93
        reasons.append("PM2.5 routine full-domain high-bias spatial factor 0.93")
        if {"urban", "north", "south", "east", "west"} & risk & station_regions:
            factor *= 1.05
            reasons.append("station lies in Windy PM2.5 risk area spatial factor 1.05")
        if "secondary" in notes or "二次" in notes:
            factor *= 1.08
            reasons.append("secondary PM2.5 risk spatial factor 1.08")
        strength, strength_reasons = confidence_strength(met_prior)
        factor = apply_strength(factor, strength)
        return clamp(factor, 0.70, 1.25), reasons + strength_reasons

    factor *= 1.08
    reasons.append("O3 routine full-domain low-bias spatial factor 1.08")
    if "north" in station_regions and wind_sector((met_prior.get("dominant_wind") or {}).get("dir")) == "south":
        factor *= 1.08
        reasons.append("southerly flow can leave northern Chengdu slightly high 1.08")
    if "north" in station_regions and ("north" in risk or "downwind" in risk):
        factor *= 1.20
        reasons.append("north/downwind O3 transport spatial factor 1.20")
    elif station_regions & risk:
        factor *= 1.10
        reasons.append("station lies in Windy O3 risk area spatial factor 1.10")
    strength, strength_reasons = confidence_strength(met_prior)
    factor = apply_strength(factor, strength)
    return clamp(factor, 0.75, 1.35), reasons + strength_reasons


def observed_lookup(observations: list[dict]) -> dict[tuple[str, str], float]:
    return {(r["station_code"], r["datetime"]): r["observed"] for r in observations}


def latest_obs_before(obs_rows: list[dict], start_dt) -> float | None:
    candidates = [r for r in obs_rows if r["dt"] <= start_dt]
    if candidates:
        return candidates[-1]["observed"]
    return obs_rows[0]["observed"] if obs_rows else None


def anchor_trend_gain(pollutant: str, met_prior: dict) -> tuple[float, list[str]]:
    p = pollutant_col(pollutant)
    prior = (met_prior.get("pollutant_prior") or {}).get(p) or (met_prior.get("pollutant_prior") or {}).get("PM2.5" if p == "PM2.5" else "O3") or {}
    notes = " ".join(prior.get("notes") or []).lower()
    trend = str(prior.get("trend") or "").lower()
    if p == "PM2.5":
        if "secondary" in notes or "二次" in notes or trend == "increasing":
            return 0.80, ["PM2.5 anchor trend gain 0.80 because secondary/increasing risk weakens the routine high-bias damping"]
        return 0.50, ["PM2.5 anchor trend gain 0.50 to keep CMAQ rise-rate conservative under routine high-bias experience"]
    return 1.00, ["O3 anchor trend gain 1.00 because routine O3 bias is handled by photochemical and transport factors"]


def apply_correction(cmaq_rows, stations, observations, diagnosis, met_prior, pollutant):
    path = diagnosis["path"]
    obs_by_station = group_by(observations, "station_code")
    obs_at_time = observed_lookup(observations)
    regions = classify_station_regions(stations)
    start_raw = cmaq_rows[0]["raw_cmaq"]
    start_dt = cmaq_rows[0]["dt"]
    out_rows = []
    factor_rows = []
    explanations = {"path": path, "observation_count": len(observations), "stations": {}, "rules": []}

    for station in stations:
        code = station["station_code"]
        s_regions = regions.get(code, {"urban"})
        obs_anchor = latest_obs_before(obs_by_station.get(code, []), start_dt)
        space_factor, space_reasons = station_space_factor(pollutant, s_regions, met_prior, path)
        trend_gain, trend_reasons = anchor_trend_gain(pollutant, met_prior)
        factor_rows.append(
            {
                "station_code": code,
                "station_name": station["station_name"],
                "lon": station["lon"],
                "lat": station["lat"],
                "regions": ";".join(sorted(s_regions)),
                "space_factor": f"{space_factor:.4f}",
                "space_reasons": " | ".join(space_reasons),
            }
        )
        explanations["stations"][code] = {
            "station_name": station["station_name"],
            "regions": sorted(s_regions),
            "space_factor": space_factor,
            "space_reasons": space_reasons,
            "time_reasons": {},
        }
        for row in cmaq_rows:
            met_row = nearest_hourly_met(met_prior, row["dt"])
            time_factor, time_reasons = met_time_factor(pollutant, row["dt"], met_row, met_prior, include_routine=path != "anchor_trend")
            raw = row["raw_cmaq"]
            spatial = raw * (space_factor if path == "space_then_time" else 1.0)
            if path == "anchor_trend" and obs_anchor is not None:
                anchor_base = obs_anchor + trend_gain * (raw - start_raw)
                temporal = anchor_base * time_factor
                method = "Obs_now + damped CMAQ trend, then meteorology time factor"
            elif path == "anchor_trend":
                temporal = raw * time_factor
                method = "No observation anchor; CMAQ trend with meteorology time factor"
            elif path == "time_only":
                temporal = raw * time_factor
                method = "CMAQ station grid proxy with time factor"
            else:
                temporal = spatial * time_factor
                method = "Spatial factor then time factor"
            cap_reasons = []
            if pollutant_col(pollutant) == "O3":
                rescue, cap_reasons = o3_rescue_day(met_prior, row["dt"], met_row, start_dt)
                if rescue and temporal > 160:
                    temporal = 160.0
                    cap_reasons.append("applied O3 favorable-day cap at 160")
            observed = obs_at_time.get((code, row["datetime"]))
            out_rows.append(
                {
                    "datetime": row["datetime"],
                    "station_code": code,
                    "station_name": station["station_name"],
                    "lon": station["lon"],
                    "lat": station["lat"],
                    "pollutant": pollutant_col(pollutant),
                    "raw_cmaq": f"{raw:.6f}",
                    "spatial_corrected": f"{spatial:.6f}",
                    "temporal_corrected": f"{temporal:.6f}",
                    "final_corrected": f"{temporal:.6f}",
                    "observed": "" if observed is None else f"{observed:.6f}",
                    "space_factor": f"{space_factor:.6f}",
                    "time_factor": f"{time_factor:.6f}",
                    "trend_gain": f"{trend_gain:.6f}",
                    "method": method,
                    "triggered_rules": " | ".join(space_reasons + trend_reasons + time_reasons + cap_reasons),
                }
            )
            if time_reasons or cap_reasons:
                explanations["stations"][code]["time_reasons"][row["datetime"]] = time_reasons + cap_reasons
    return out_rows, factor_rows, explanations


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply expert spatial-temporal correction.")
    parser.add_argument("--cmaq-dir")
    parser.add_argument("--cmaq-file")
    parser.add_argument("--obs-dir")
    parser.add_argument("--diagnosis", required=True)
    parser.add_argument("--met-prior")
    parser.add_argument("--pollutant", default="PM2.5")
    parser.add_argument("--station-out", required=True)
    parser.add_argument("--factor-out", required=True)
    parser.add_argument("--explanations-out", required=True)
    args = parser.parse_args()

    cmaq_file = Path(args.cmaq_file) if args.cmaq_file else default_cmaq_domain_file(args.cmaq_dir, args.pollutant)
    rows, factors, explanations = apply_correction(
        load_cmaq_domain(cmaq_file),
        load_stations(args.obs_dir),
        load_observations(args.obs_dir, args.pollutant),
        read_json(args.diagnosis),
        read_json(args.met_prior, default={}) if args.met_prior else {},
        args.pollutant,
    )
    fields = [
        "datetime",
        "station_code",
        "station_name",
        "lon",
        "lat",
        "pollutant",
        "raw_cmaq",
        "spatial_corrected",
        "temporal_corrected",
        "final_corrected",
        "observed",
        "space_factor",
        "time_factor",
        "trend_gain",
        "method",
        "triggered_rules",
    ]
    write_csv(args.station_out, rows, fields)
    write_csv(args.factor_out, factors, ["station_code", "station_name", "lon", "lat", "regions", "space_factor", "space_reasons"])
    write_json(args.explanations_out, explanations)
    print(f"Wrote corrected station records: {args.station_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
