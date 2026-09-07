---
name: cmaq-forecast-qa
description: Use this skill when answering questions about CMAQ forecast NetCDF data, including PM2.5 and O3 trends, high-value events, exceedance checks, spatial hotspots, meteorological drivers, and extracting CMAQ indicators into CSV and JSON summaries for model-based Q&A.
---

# CMAQ Forecast QA

Use this skill to answer data questions over CMAQ forecast outputs. The model should interpret the user's question, but scripts must do the NetCDF reading, metric extraction, aggregation, CSV export, and JSON summarization.

## Workflow

1. Locate the CMAQ files, usually a main `.ncf` file and optionally an `_EXTRA` file.
2. Inspect available variables and the forecast time range with `scripts/inspect_cmaq.py`.
3. Map the user's indicator to a CMAQ field using `references/field_map.md`.
4. Run `scripts/analyze_cmaq_question.py` for end-to-end question handling, or `scripts/extract_cmaq_metric.py` for a specific variable.
5. Use the generated CSV files for traceability and the JSON summary for the final answer.
6. Answer in Chinese when the user asks in Chinese. Cite calculated values, peak dates, trend direction, threshold assumptions, and any uncertainty.

Do not load full NetCDF arrays into the chat context. Do not answer pollutant trend or high-value questions from field names alone.

## Default Files

If the user does not provide paths, first look for CMAQ files under a project data directory such as:

```text
data/CMAQ forecast data
data/CMAQ
Data/CMAQ
```

In this project, the expected folder is:

```text
data/CMAQ forecast data
```

If the path is in Chinese or otherwise project-specific, use the user's provided path or locate files by searching for `*.ncf`.

## Common Commands

Inspect files:

```bash
python scripts/inspect_cmaq.py --data-dir "<CMAQ folder>"
```

Answer a natural-language question:

```bash
python scripts/analyze_cmaq_question.py --data-dir "<CMAQ folder>" --question "future 14 days PM2.5 trend" --out-dir "<output folder>"
```

Extract a specific metric:

```bash
python scripts/extract_cmaq_metric.py --main "<main.ncf>" --extra "<extra file>" --metric PM25 --period-days 14 --out-dir "<output folder>"
```

## Question Handling Defaults

- PM2.5 trend: use `PM25_TOT`, daily domain mean as the main trend line, plus domain max and hotspots.
- PM10 trend: use `PM10`.
- O3 high value: prefer `O3_R8` from `_EXTRA` if available; otherwise use `O3_UGM3`. If only hourly O3 is available, state that the result is hourly unless an 8-hour rolling calculation was explicitly run.
- CO, NO2, SO2, NH3: use mass concentration fields when available.
- Meteorological context: use `TEMP2`, `RH`, `WSPD10`, `WDIR10`, `RT`, `PBLH`, `PSFC`, and `VIS`.

## Outputs

The scripts should create:

- `*_hourly_domain.csv`: hourly domain statistics.
- `*_daily_domain.csv`: daily statistics for trend and high-value summaries.
- `*_hotspots.csv`: top grid/time high-value records.
- `*_summary.json`: compact model-readable summary.

Use the JSON summary for the final answer and mention the CSV files for auditability when useful.

## References

- Field mapping: `references/field_map.md`
- Indicator rules: `references/indicator_rules.md`
- Output schema: `references/output_schema.md`
- Threshold defaults: `references/thresholds.yaml`
