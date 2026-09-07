# Indicator Rules

## PM2.5 Trend

Use `PM25_TOT`.

Default calculations:

- Hourly domain mean, min, max, p50, p90, and p95.
- Daily mean based on hourly domain mean.
- Daily max based on hourly domain mean.
- Daily grid maximum.
- Top hotspot grid/time records.
- Trend slope over daily mean.
- First-three-day mean versus last-three-day mean.

Trend label:

- `increasing`: final mean is meaningfully higher than initial mean and slope is positive.
- `decreasing`: final mean is meaningfully lower than initial mean and slope is negative.
- `stable`: change is within the configured small-change margin.
- `fluctuating`: slope and endpoint comparison disagree.

## O3 High Value

Prefer `O3_R8` from the `_EXTRA` file if available. If unavailable, use `O3_UGM3` and clearly state whether the result is hourly or rolling 8-hour.

Default threshold:

- O3 8-hour high value: `160 ug/m3`.

Default calculations:

- Daily maximum.
- Exceedance days.
- Peak value and peak time.
- Number and share of exceeding grid cells per hour.
- Top hotspot grid/time records.

## Spatial Aggregation

Default aggregation is whole-domain unless the user provides a station, district, city, polygon, or grid cell. Keep `row` and `col` in hotspot outputs so later versions can join to geographic coordinates or administrative regions.

## Time Periods

When the user asks for "future 14 days", use the first 14 available forecast days from the file unless the user provides an explicit date range. Always report the actual start and end timestamps used.

## Answer Style

Use the JSON summary for concise answers:

- State the metric, unit, and period.
- Give the trend label and key values.
- For high-value questions, state whether the threshold was exceeded and list the peak date/time.
- Mention important caveats, especially O3 hourly versus 8-hour interpretation.
