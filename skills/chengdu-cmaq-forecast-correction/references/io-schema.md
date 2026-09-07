# I/O Schema

## Portable Project Paths

- Skill path: `skills/chengdu-cmaq-forecast-correction`
- CMAQ data directory: use the user-provided path or the application's configured data directory.
- Original CMAQ file: `<CMAQ folder>/CCTM_P.GFSCSTOBSD2.AIRVIEW.ncf`
- Fast PM2.5 CSVs:
  - `<CMAQ folder>/output/pm25_trend_hourly_domain.csv`
  - `<CMAQ folder>/output/pm25_trend_hotspots.csv`
  - `<CMAQ folder>/output/pm25_trend_summary.json`
- Observation directory: `<CMAQ folder>/observations_matched`
- Station metadata: `observations_matched/chengdu_stations.csv`
- Site observations: `observations_matched/chengdu_observations_site_hourly_*.csv`

Observation files are optional for forecast-only operation. If `--obs-dir` is omitted, missing, or contains no site-hourly observation CSV, the workflow skips observation nudging and continues. If station metadata is also missing, the scripts create a `CD_CITYMEAN` Chengdu city-mean proxy station so downstream aggregation and reporting still run.

## Station Columns

Use stations where `is_available_non_control=True`.

Important columns. Some local datasets use the following Chinese source headers:

- station code: `监测点编码`
- station name: `监测点名称`
- longitude: `经度`
- latitude: `纬度`
- `is_control`
- `is_stopped`
- `is_available_non_control`

## Observation Columns

Important columns:

- `datetime`
- `station_code`
- `station_name`
- `lon`
- `lat`
- `PM2.5`
- `O3`

## CMAQ Fast CSV Columns

`pm25_trend_hourly_domain.csv`:

- `datetime`
- `metric`
- `field`
- `unit`
- `domain_mean`
- `domain_min`
- `domain_max`
- `p50`
- `p90`
- `p95`
- `exceed_grid_count`
- `exceed_grid_ratio`

`pm25_trend_hotspots.csv`:

- `rank`
- `datetime`
- `date`
- `metric`
- `field`
- `unit`
- `row`
- `col`
- `value`

## Meteorology Prior

`met_prior.json` should be generated from Windy.com Chengdu or Windy API. Minimal shape:

When `WINDY_API_KEY` is available, `scripts/fetch_windy_prior.py` defaults to Windy Point Forecast `gfs`, stores the raw API payload in `raw_windy`, and parses a machine-readable `hourly` list. Point Forecast API is used for numeric support; ECMWF/EC map-layer judgment still requires manual Windy.com inspection or another licensed data source.

```json
{
  "source": "windy_chengdu",
  "location": {"name": "Chengdu", "lat": 30.5728, "lon": 104.0668},
  "confidence": "manual_or_api",
  "model_agreement": "high|low|unknown",
  "run_to_run_change": {
    "large_change": false,
    "first_seen": false,
    "notes": "Set true/true when the newest 00/12 forecast changes sharply for the first time; correction will be held conservative until roughly one day of tracking confirms it."
  },
  "dominant_wind": {"dir": 180, "speed": 3.5},
  "short_term_signals": {
    "no2_08": 20,
    "vocs_ppb": 30,
    "cloud": 40,
    "radiation": "moderate_or_strong",
    "notes": "For O3 same-day nowcasting."
  },
  "pollutant_prior": {
    "PM2.5": {
      "trend": "increasing",
      "risk_areas": ["urban", "north"],
      "peak_time": null,
      "improvement_time": null,
      "notes": ["weak wind and high RH favor accumulation", "secondary formation", "delayed improvement"]
    },
    "O3": {
      "trend": "increasing",
      "risk_areas": ["north", "downwind"],
      "peak_time": null,
      "improvement_time": null,
      "notes": ["high temperature and low cloud favor O3", "subtropical-high or ridge/Qinghai-high", "Deyang VOCs transport"]
    }
  },
  "hourly": [
    {
      "datetime": "2026-05-19 13:00:00",
      "wind_speed": 2.0,
      "wind_dir": 20,
      "precip": 0.0,
      "temp": 30.0,
      "rh": 60.0,
      "cloud": 20.0,
      "pbl": 1200.0
    }
  ]
}
```

Optional `met_prior` semantics:

- `model_agreement=high` means multi-model synoptic pattern agreement is good; keep model trend credible.
- `model_agreement=low` means model disagreement is obvious; shrink empirical correction strength and report uncertainty.
- `run_to_run_change.large_change=true` and `first_seen=true` means the latest 00/12 forecast changed sharply for the first time; apply only conservative correction pending about one day of tracking.
- `short_term_signals.no2_08<=20`, `vocs_ppb<=30`, afternoon southerly wind force 3+ (`wind_speed` about >=3.4 m/s), and acceptable cloud/radiation trigger the O3 recoverable-good-day damp/cap rule.
- PM2.5 `improvement_time` is the forecaster/Windy/consultation improvement node. Before that node, keep PM2.5 from improving too early unless rain or sustained wind has clearly entered Chengdu.
- O3 notes can include `subtropical-high`, `ridge`, or `Qinghai-high`. The localized aliases `副高`, `高脊`, and `青高` are also recognized by the correction rules.

## Outputs

Each run should write:

- `diagnosis.json`
- `station_corrected.csv`
- `city_aggregate.csv`
- `space_factor.csv`
- `explanations.json`
- `assessment.md`
- `figures/`

Figures should include city mean time series, key station time series, spatial factor, raw spatial distribution, corrected spatial distribution, and correction difference. SVG output is acceptable when PNG plotting libraries are unavailable.
