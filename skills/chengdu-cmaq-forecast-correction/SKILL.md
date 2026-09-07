---
name: chengdu-cmaq-forecast-correction
description: Diagnose and correct Chengdu CMAQ air-quality forecasts with Windy.com/EC Chengdu meteorology, optional station observations, multi-model/run-to-run credibility checks, and forecaster expert rules. Use when the agent needs to revise PM2.5 or O3 CMAQ results, judge whether CMAQ spatial or temporal evolution is credible, apply expert spatial-temporal correction coefficients, handle sparse/no-observation forecast correction, smooth corrected forecasts, compare against observations when available, plot station and spatial diagnostics, or produce a Chengdu air-quality model diagnosis and correction assessment.
---

# Chengdu CMAQ Forecast Correction

Use this skill to produce a multi-source air-quality model diagnosis and correction assessment for Chengdu. The core task is not only to adjust values, but to explain why CMAQ is high or low in specific areas and periods.

## Required Workflow

1. Use Windy.com Chengdu meteorology first.
   - Prefer machine-readable Windy Point Forecast output when `WINDY_API_KEY` is available.
   - If no API key is available, open `https://www.windy.com/` for Chengdu and manually summarize wind, precipitation, cloud, temperature, humidity, vertical mixing/PBL, weather type, improvement time, and O3 short-term NO2/VOCs signals into `met_prior.json`.
   - When available, record EC/Windy versus GFS, IFS, CFS, 14-day/30-day or other model agreement in `model_agreement`. If the newest 00/12 forecast changes sharply for the first time, set `run_to_run_change.large_change=true` and keep correction conservative until about one day of tracking confirms it.
2. Read CMAQ and observation data.
   - Use `references/io-schema.md` for default paths and expected fields.
   - For local tests, prefer existing PM2.5 CSV summaries under the configured CMAQ data directory.
   - Observations are optional. With observations, use them as station-hour anchors. With sparse observations, only anchor available station-hours. With no observations or no station metadata, continue with a Chengdu city-mean proxy station and explicitly report forecast-only uncertainty.
3. Diagnose only two credibility dimensions:
   - Chengdu full-domain spatial distribution: is the CMAQ high-value area consistent with meteorology and transport?
   - Chengdu full-domain temporal evolution: are trend, peak timing, and improvement timing consistent with meteorology? Treat CMAQ improvement that is more than about 4 h earlier than the forecaster/Windy/EC improvement node as a time mismatch.
4. Choose exactly one correction path:
   - `anchor_trend`: spatial and temporal evolution are both credible. Use observations as truth and CMAQ as trend, rise-rate, and turning-point reference. If no observations exist, keep the CMAQ trend but apply meteorology and expert factors without observation anchoring.
   - `time_only`: spatial distribution is credible, but peak/improvement timing is wrong. Keep CMAQ spatial structure and correct station-grid time factors.
   - `space_then_time`: spatial distribution is not credible. Apply spatial factors first, then station-grid time factors.
5. Apply correction and smoothing.
   - Always smooth the final result.
   - Keep intermediate values: raw CMAQ, spatial-corrected, temporal-corrected, and final-smoothed.
   - When matched station observations exist at a timestamp, apply observation-constrained nudging before final smoothing. This improves diagnostic fit and spatial consistency; for future hours without observations it has no effect.
   - Always apply the updated forecaster rules from `references/expert-rules.md`: PM2.5 routine high bias, O3 routine low bias, PM2.5 secondary-formation underestimation, improvement-node delay by 4-6 h, morning-rush PM2.5 peak timing, north/south wind transport, Deyang VOCs/O3 transport, O3 short-term recoverable-good-day signals, high-ridge/Qinghai-high versus subtropical-high O3 weather types, and 00/12 run-to-run conservative tracking.
6. Aggregate and plot.
   - Aggregate only available non-control stations.
   - Plot corrected-vs-raw-vs-observed city mean and key stations.
   - Plot spatial factor, raw spatial distribution, corrected distribution, and correction difference.
7. Write the assessment.
   - The report must state where CMAQ is high/low, what was corrected, how much it changed, why it changed, aggregate results, and figure paths.

## Script Entry Points

Run the full workflow:

```powershell
python scripts/run_correction.py --cmaq-dir "<CMAQ folder>" --obs-dir "<observation folder>" --pollutant PM2.5 --met-prior met_prior.json --out "<output folder>"
```

Run a forecast-only fallback when no observations are available:

```powershell
python scripts/run_correction.py --cmaq-dir "<CMAQ folder>" --pollutant PM2.5 --met-prior met_prior.json --out "<output folder>"
```

Generate or template a Windy Chengdu prior:

```powershell
python scripts/fetch_windy_prior.py --out met_prior.json
```

If `WINDY_API_KEY` is present, the script calls Windy Point Forecast API and parses the returned GFS point forecast into `hourly` wind, precipitation, temperature, humidity, cloud, and pressure fields. If `WINDY_API_KEY` is missing, the script creates a manual template that must be filled from Windy Chengdu before formal correction.

Windy Point Forecast API does not provide ECMWF/EC fields in this workflow. Use the API result for machine-readable correction support, and still use Windy.com EC/ECMWF map-layer inspection or another licensed EC data source when forecaster judgment depends on EC synoptic patterns.

## References

- Read `references/expert-rules.md` when deciding correction coefficients or writing explanations.
- Read `references/io-schema.md` when connecting CMAQ, observation, station, meteorology, and output files.

## Guardrails

- Do not treat the scripts as official forecast issuance. They support diagnostic correction and should still be checked by a forecaster.
- Do not overfit to observations by replacing the forecast with observed values. Observations anchor the current state; CMAQ and meteorology still define future trend and turning points.
- If Windy meteorology is unavailable or only manually summarized, state that uncertainty in the report.
- If observations are sparse or unavailable, do not fail the workflow. Skip observation nudging, use the city-mean proxy if needed, apply conservative expert/met correction, and state the uncertainty.
- For forecast horizons beyond 5 days, keep quantitative correction conservative and emphasize qualitative trend.
