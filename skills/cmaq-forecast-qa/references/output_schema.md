# Output Schema

## Hourly Domain CSV

Filename pattern:

```text
<metric>_<analysis>_hourly_domain.csv
```

Columns:

```text
datetime,metric,field,unit,domain_mean,domain_min,domain_max,p50,p90,p95,exceed_grid_count,exceed_grid_ratio
```

## Daily Domain CSV

Filename pattern:

```text
<metric>_<analysis>_daily_domain.csv
```

Columns:

```text
date,metric,field,unit,daily_mean,daily_min,daily_max_domain_mean,daily_grid_max,p90_max,p95_max,exceed_hours,exceed_grid_count_max,exceed_grid_ratio_max
```

## Hotspots CSV

Filename pattern:

```text
<metric>_<analysis>_hotspots.csv
```

Columns:

```text
rank,datetime,date,metric,field,unit,row,col,value
```

## Summary JSON

Filename pattern:

```text
<metric>_<analysis>_summary.json
```

Top-level keys:

```json
{
  "metric": "PM25",
  "field": "PM25_TOT",
  "unit": "ug/m3",
  "source_file": "...",
  "period": {
    "start": "2026-05-19 01:00:00",
    "end": "2026-06-01 23:00:00",
    "steps": 336
  },
  "threshold": null,
  "trend": {},
  "high_value": {},
  "peak": {},
  "outputs": {}
}
```
