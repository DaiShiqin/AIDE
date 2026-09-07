---
name: cmaq-plot-data
description: Extract CMAQ forecast NetCDF/IOAPI data and generate pollutant time-series plots or spatial distribution maps. Use when the user asks to plot, draw, visualize, map, compare, or export CMAQ variables such as PM2.5, PM10, O3, NO2, SO2, CO, meteorology, time trends, hourly/daily curves, high-value periods, hotspots, or pollution spatial fields from CMAQ `.ncf` files.
---

# CMAQ Plot Data

Use this skill to turn CMAQ forecast data into plotted artifacts for the final answer. Interpret the user's request, match the pollutant to a CMAQ variable, extract only the needed field, run the plotting script, then embed the resulting PNG in the response.

## Workflow

1. Parse the user request and decide the plot type:
   - Use a time-series plot for words like trend, process, hourly, daily, over time, forecast curve, high-value period, compare days.
   - Use a spatial map for words like distribution, spatial, map, hotspot, at a time, grid field, concentration map.
   - If both are useful, create both with one `--plot both` call.
   - When the user gives a date or time range, pass it as `start_time` and `end_time`. Use the same range for every requested plot.
   - Do not create one spatial map per peak hour/day unless the user explicitly asks for multiple snapshots or animation.
2. Locate CMAQ files from the user-provided path or the application's configured data directory, then look for a main `.ncf` file and an optional `_EXTRA` file.
3. Inspect fields when needed with:

```bash
python scripts/plot_cmaq.py --data-dir "<CMAQ folder>" --inspect
```

4. Match the requested indicator using `references/field_map.md`. Prefer mass concentration fields for reporting and plotting: `PM25_TOT`, `PM10`, `O3_UGM3`, `NO2_UGM3`, `SO2_UGM3`, `CO_MGM3`. Use `O3_R8` from `_EXTRA` only when the user asks for 8-hour ozone or MDA8-style ozone.
5. Run `scripts/plot_cmaq.py` with `--plot time-series`, `--plot spatial`, or preferably `--plot both` when both views are requested. Put outputs in a task-specific output folder.
6. Read the generated `summary.json` and write the final answer in the user's language. Include the generated image with Markdown image syntax using the absolute path.

## Commands

Time-series plot:

```bash
python scripts/plot_cmaq.py --data-dir "<CMAQ folder>" --metric PM25 --plot time-series --out-dir "<output folder>"
```

Spatial distribution map at a forecast time:

```bash
python scripts/plot_cmaq.py --data-dir "<CMAQ folder>" --metric O3 --plot spatial --time "2026-05-22 00:00" --out-dir "<output folder>"
```

Both plot types:

```bash
python scripts/plot_cmaq.py --data-dir "<CMAQ folder>" --metric PM25 --plot both --start-time "2026-05-27" --end-time "2026-05-29" --out-dir "<output folder>"
```

Time range behavior:

- `--start-time` and `--end-time` filter time-series plots to the matching timestamps.
- For spatial plots, a time range produces one average spatial field over the matching timestamps.
- If no `--time` or `--time-index` is provided for a spatial plot, the script produces a time-mean field rather than a single-hour map.
- Date-only `--end-time` values include the full day, so `--end-time "2026-05-29"` includes `2026-05-29 23:00` when present.

## Plot Defaults

- Time-series plots: use domain mean as the main red line with markers, add domain maximum/minimum as lighter context lines, add threshold lines when defined, rotate dense time labels, and annotate the peak. If the user provides a time range, plot only that range. Use a compact multi-panel layout for a full process chart and a focused single panel for one pollutant.
- Spatial maps: for a user-specified period, render exactly one average map with a title like `Mean PM2.5` or `Mean O3`; do not render several hourly maps. Use a white figure background, timestamp/range subtitle, `ug/m3` or the variable unit at top right, discrete color levels, latitude/longitude-style axes when projection metadata is present, and optional average wind vectors from `WSPD10`/`WDIR10` when available.
- Use transparent assumptions in the final answer: variable name, unit, time range, aggregation method, and whether values are hourly or 8-hour rolling.

## Outputs

The script writes:

- `cmaq_<metric>_<plot>.png`: rendered figure.
- `cmaq_<metric>_<plot>_summary.json`: plot metadata, variable, units, time range, min/mean/max, and output path.
- `cmaq_<metric>_timeseries.csv` for time-series requests.

Prefer the PNG and JSON summary for the final response. Mention CSV only when traceability matters.

## References

- Variable matching: `references/field_map.md`
- Plot style and response rules: `references/plot_style.md`
