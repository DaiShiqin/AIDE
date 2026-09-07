import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RSM_WORKDIR = PROJECT_ROOT / "deepRSM" / "to_cdhky" / "to_cdhky" / "CYDeepRSM"
configured_rsm_workdir = Path(os.getenv("RSM_WORKDIR") or DEFAULT_RSM_WORKDIR).expanduser()
RSM_WORKDIR = (
    configured_rsm_workdir if configured_rsm_workdir.is_absolute() else PROJECT_ROOT / configured_rsm_workdir
).resolve()

OUTER_REGIONS = {
    "A": "成都平原地区",
    "B": "重庆区域",
    "C": "川南地区",
    "D": "川东北地区",
    "E": "川西北区域",
    "F": "攀西区域",
}

INNER_REGIONS = {
    "A": "成都主城区",
    "B": "成都二圈层",
    "C1": "成都郊区新城1",
    "C2": "成都郊区新城2",
    "D": "德阳",
    "E": "绵阳",
    "F": "遂宁",
    "G": "乐山",
    "H": "眉山",
    "I": "雅安",
    "J": "资阳",
    "K": "其他外层调整区域",
}

POLLUTANT_ALIASES = {
    "NOX": "NOX",
    "SO2": "SO2",
    "NH3": "NH3",
    "VOC": "VOC",
    "PM25": "PM25",
    "PM2.5": "PM25",
    "PM2_5": "PM25",
}

SPEC_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]*)\s*:\s*([A-Za-z0-9_.]+)\s*=\s*([0-9.]+)\s*%?\s*$")


def read_matrix(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise ValueError(f"empty matrix: {path}")
    return rows[0], rows[1:]


def write_matrix(path, header, data_rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(data_rows)


def normalize_reduction(value_text):
    value = float(value_text)
    reduction_fraction = value / 100.0 if value > 1 else value
    if reduction_fraction < 0 or reduction_fraction > 1:
        raise ValueError(f"reduction must be between 0 and 100%, got {value_text}")
    remaining = 1.0 - reduction_fraction
    return reduction_fraction, remaining


def parse_specs(specs, valid_regions):
    parsed = []
    for spec in specs:
        match = SPEC_RE.match(spec)
        if not match:
            raise ValueError(f"bad reduction spec {spec!r}; use REGION:POLLUTANT=PERCENT")
        region, pollutant, reduction = match.groups()
        region = region.upper()
        pollutant = pollutant.upper()
        if region not in valid_regions:
            raise ValueError(f"unknown region {region!r}; valid: {', '.join(valid_regions)}")
        if pollutant not in POLLUTANT_ALIASES:
            raise ValueError(f"unknown pollutant {pollutant!r}; valid: NOX, SO2, NH3, VOC, PM25")
        reduction_fraction, remaining = normalize_reduction(reduction)
        parsed.append(
            {
                "region": region,
                "pollutant": POLLUTANT_ALIASES[pollutant],
                "reduction_fraction": reduction_fraction,
                "remaining": remaining,
                "source": spec,
            }
        )
    return parsed


def find_column(header, region, pollutant):
    suffix = f"){region}_{pollutant}_TT"
    for idx, name in enumerate(header):
        if name.endswith(suffix):
            return idx
    raise ValueError(f"column not found for {region}:{pollutant}")


def upsert_case_row(matrix_path, case_number, specs):
    header, rows = read_matrix(matrix_path)
    width = len(header)
    while len(rows) < case_number:
        run_id = str(len(rows) + 1)
        rows.append([run_id] + ["1"] * (width - 1))

    row = [str(case_number)] + ["1"] * (width - 1)
    for spec in specs:
        col = find_column(header, spec["region"], spec["pollutant"])
        row[col] = f"{spec['remaining']:.10g}"

    rows[case_number - 1] = row
    write_matrix(matrix_path, header, rows)
    return row


def run_rsm(case_number):
    cmd = [sys.executable, "run_local.py", "--target", "pm", "--cases", str(case_number)]
    subprocess.run(cmd, cwd=RSM_WORKDIR, check=True)


def read_dpm25_results(case_number, month=None):
    result_dir = RSM_WORKDIR / "csv" / "test"
    pattern = f"Dpm25_2021_M*_case{case_number}.csv"
    files = sorted(result_dir.glob(pattern), key=lambda p: month_number(p.name))
    if month is not None:
        wanted = f"M{int(month)}_"
        files = [p for p in files if wanted in p.name]
    if not files:
        raise FileNotFoundError(f"no Dpm25 files found for case{case_number} in {result_dir}")

    records = []
    for path in files:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        if len(rows) < 3:
            raise ValueError(f"unexpected result shape: {path}")
        baseline = [float(v) for v in rows[1][:12]]
        scenario = [float(v) for v in rows[2][:12]]
        improvement = [b - s for b, s in zip(baseline, scenario)]
        records.append(
            {
                "file": str(path),
                "month": f"M{month_number(path.name)}",
                "improvement": dict(zip(INNER_REGIONS.keys(), improvement)),
                "scenario": dict(zip(INNER_REGIONS.keys(), scenario)),
            }
        )
    return records


def month_number(name):
    match = re.search(r"_M(\d+)_", name)
    return int(match.group(1)) if match else 999


def mean_improvement(records):
    totals = {code: 0.0 for code in INNER_REGIONS}
    for record in records:
        for code, value in record["improvement"].items():
            totals[code] += value
    return {code: value / len(records) for code, value in totals.items()}


def print_markdown(case_number, outer_specs, inner_specs, records):
    print(f"# case{case_number} PM2.5 improvement")
    print()
    print("Improvement is `baseline - scenario`; values are RSM 2021 scenario improvements.")
    print()
    print("## Matrix changes")
    if not outer_specs and not inner_specs:
        print("- No reductions specified; all coefficients are 1.0.")
    for spec in outer_specs:
        pct = spec["reduction_fraction"] * 100
        print(f"- outer {spec['region']} {OUTER_REGIONS[spec['region']]} {spec['pollutant']}: reduction {pct:.6g}%, coefficient {spec['remaining']:.6g}")
    for spec in inner_specs:
        pct = spec["reduction_fraction"] * 100
        print(f"- inner {spec['region']} {INNER_REGIONS[spec['region']]} {spec['pollutant']}: reduction {pct:.6g}%, coefficient {spec['remaining']:.6g}")
    print()
    print("## Mean improvement across read months")
    means = mean_improvement(records)
    for code, name in INNER_REGIONS.items():
        print(f"- {code} {name}: {means[code]:.6f}")
    print()
    print("## Monthly improvement")
    header = ["month"] + [f"{code}{name}" for code, name in INNER_REGIONS.items()]
    print("| " + " | ".join(header) + " |")
    print("| " + " | ".join(["---"] * len(header)) + " |")
    for record in records:
        row = [record["month"]] + [f"{record['improvement'][code]:.6f}" for code in INNER_REGIONS]
        print("| " + " | ".join(row) + " |")


def main():
    parser = argparse.ArgumentParser(description="Create and run a local DeepRSM PM2.5 reduction case.")
    parser.add_argument("--case", type=int, help="Case number to write. Defaults to the next row after existing matrices.")
    parser.add_argument("--outer-reduction", action="append", default=[], help="Outer spec like A:PM25=50. Can be repeated.")
    parser.add_argument("--inner-reduction", action="append", default=[], help="Inner spec like D:NOX=30. Can be repeated.")
    parser.add_argument("--month", type=int, help="Only read one output month, e.g. 11 for M11.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and preview without editing matrices or running RSM.")
    parser.add_argument("--no-run", action="store_true", help="Edit matrices but do not run RSM or read outputs.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    outer_path = RSM_WORKDIR / "Control_Matrix_outer.csv"
    inner_path = RSM_WORKDIR / "Control_Matrix_inner.csv"
    outer_header, outer_rows = read_matrix(outer_path)
    inner_header, inner_rows = read_matrix(inner_path)

    case_number = args.case or max(len(outer_rows), len(inner_rows)) + 1
    if case_number < 1:
        raise ValueError("--case must be >= 1")

    outer_specs = parse_specs(args.outer_reduction, OUTER_REGIONS)
    inner_specs = parse_specs(args.inner_reduction, INNER_REGIONS)

    if args.dry_run:
        preview = {
            "case": case_number,
            "outer_reductions": outer_specs,
            "inner_reductions": inner_specs,
            "would_edit": [str(outer_path), str(inner_path)],
            "would_run": f"python run_local.py --target pm --cases {case_number}",
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return

    upsert_case_row(outer_path, case_number, outer_specs)
    upsert_case_row(inner_path, case_number, inner_specs)

    if args.no_run:
        print(f"Wrote case{case_number} to control matrices. RSM was not run.")
        return

    run_rsm(case_number)
    records = read_dpm25_results(case_number, args.month)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "case": case_number,
                    "outer_reductions": outer_specs,
                    "inner_reductions": inner_specs,
                    "records": records,
                    "mean_improvement": mean_improvement(records),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_markdown(case_number, outer_specs, inner_specs, records)


if __name__ == "__main__":
    main()
