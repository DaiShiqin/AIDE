from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def run(args: list[str]) -> None:
    cmd = [sys.executable] + [str(a) for a in args]
    print("RUN", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Chengdu CMAQ forecast diagnosis and correction workflow.")
    parser.add_argument("--cmaq-dir", help="CMAQ data directory. For tests, use 数据/CMAQ预报数据.")
    parser.add_argument("--cmaq-file", help="Hourly-domain CMAQ CSV. NetCDF support is reserved for future extension.")
    parser.add_argument("--hotspots-file", help="Optional CMAQ hotspots CSV.")
    parser.add_argument("--obs-dir", help="observations_matched directory. If omitted or missing, use a Chengdu city-mean proxy station and skip observation nudging.")
    parser.add_argument("--met-prior", help="Windy Chengdu met_prior.json. If omitted, a manual template is written.")
    parser.add_argument("--pollutant", default="PM2.5", choices=["PM2.5", "O3", "PM25"])
    parser.add_argument("--out", required=True, help="Output directory.")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fig_dir = out / "figures"
    met_prior = Path(args.met_prior) if args.met_prior else out / "met_prior_template.json"
    if not args.met_prior:
        run([SCRIPT_DIR / "fetch_windy_prior.py", "--out", met_prior])
        print("No --met-prior was supplied. A Windy Chengdu template was generated; review it for formal correction.")

    diagnosis = out / "diagnosis.json"
    station_tmp = out / "station_corrected_unsmoothed.csv"
    station_final = out / "station_corrected.csv"
    factors = out / "space_factor.csv"
    explanations = out / "explanations.json"
    city = out / "city_aggregate.csv"
    station_summary = out / "station_summary.csv"
    figures = out / "figures.csv"
    report = out / "assessment.md"

    diag_args = [SCRIPT_DIR / "diagnose_cmaq.py", "--met-prior", met_prior, "--pollutant", args.pollutant, "--out", diagnosis]
    if args.cmaq_file:
        diag_args += ["--cmaq-file", args.cmaq_file]
    else:
        diag_args += ["--cmaq-dir", args.cmaq_dir]
    if args.hotspots_file:
        diag_args += ["--hotspots-file", args.hotspots_file]
    run(diag_args)

    apply_args = [
        SCRIPT_DIR / "apply_expert_correction.py",
        "--diagnosis",
        diagnosis,
        "--met-prior",
        met_prior,
        "--pollutant",
        args.pollutant,
        "--station-out",
        station_tmp,
        "--factor-out",
        factors,
        "--explanations-out",
        explanations,
    ]
    if args.obs_dir:
        apply_args += ["--obs-dir", args.obs_dir]
    if args.cmaq_file:
        apply_args += ["--cmaq-file", args.cmaq_file]
    else:
        apply_args += ["--cmaq-dir", args.cmaq_dir]
    run(apply_args)

    run([SCRIPT_DIR / "smooth_correction.py", "--input", station_tmp, "--out", station_final, "--pollutant", args.pollutant])
    run(
        [
            SCRIPT_DIR / "aggregate_and_plot.py",
            "--station-corrected",
            station_final,
            "--city-out",
            city,
            "--station-summary-out",
            station_summary,
            "--fig-dir",
            fig_dir,
            "--figures-out",
            figures,
        ]
    )
    run(
        [
            SCRIPT_DIR / "generate_report.py",
            "--diagnosis",
            diagnosis,
            "--explanations",
            explanations,
            "--city",
            city,
            "--station-summary",
            station_summary,
            "--figures",
            figures,
            "--out",
            report,
        ]
    )
    print(f"Done. Assessment: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
