from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import clamp, fnum, group_by, read_csv, rolling_mean, write_csv


def smooth_station_rows(rows: list[dict], pollutant: str, window: int | None = None, obs_nudge_weight: float = 0.65) -> list[dict]:
    if window is None:
        window = 5 if pollutant.upper().replace(".", "") == "PM25" else 3
    low, high = (0.70, 1.25) if pollutant.upper().replace(".", "") == "PM25" else (0.75, 1.35)
    obs_nudge_weight = clamp(obs_nudge_weight, 0.0, 1.0)
    out = []
    for _, station_rows in group_by(rows, "station_code").items():
        station_rows = sorted(station_rows, key=lambda r: r["datetime"])
        vals = []
        for row in station_rows:
            model_val = fnum(row.get("final_corrected"))
            obs_val = fnum(row.get("observed"))
            if model_val is not None and obs_val is not None and obs_nudge_weight > 0:
                vals.append((1.0 - obs_nudge_weight) * model_val + obs_nudge_weight * obs_val)
            else:
                vals.append(model_val)
        smoothed = rolling_mean(vals, window)
        for row, val in zip(station_rows, smoothed):
            raw = fnum(row.get("raw_cmaq"))
            method = row.get("method", "")
            if "Obs_now" in method:
                final = max(0.0, val) if val is not None else val
            elif raw and raw > 0 and val is not None:
                ratio = clamp(val / raw, low, high)
                final = raw * ratio
            else:
                final = val
            new = dict(row)
            new["final_corrected_unsmoothed"] = row.get("final_corrected", "")
            new["final_corrected"] = "" if final is None else f"{final:.6f}"
            new["smoothing_window_hours"] = str(window)
            new["obs_nudge_weight"] = f"{obs_nudge_weight:.3f}" if fnum(row.get("observed")) is not None else "0.000"
            out.append(new)
    out.sort(key=lambda r: (r["datetime"], r["station_code"]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Smooth station correction time series.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pollutant", default="PM2.5")
    parser.add_argument("--window", type=int)
    parser.add_argument("--obs-nudge-weight", type=float, default=0.65)
    args = parser.parse_args()
    rows = smooth_station_rows(read_csv(args.input), args.pollutant, args.window, args.obs_nudge_weight)
    fields = list(rows[0].keys()) if rows else []
    write_csv(args.out, rows, fields)
    print(f"Wrote smoothed correction: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
