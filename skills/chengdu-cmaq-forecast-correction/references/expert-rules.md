# Chengdu Expert Correction Rules

Use these rules to explain and quantify empirical CMAQ correction. Coefficients are v1 defaults and should be recalibrated with historical cases when more data are available.

## System Bias

| Pollutant | Situation | Area | Factor | Explanation |
|---|---|---|---:|---|
| PM2.5 | Routine Chengdu forecast without strong secondary formation signal | Full domain | 0.90-0.95 | Forecaster experience indicates CMAQ often overestimates PM2.5 in Chengdu. |
| O3 | Routine warm-season forecast | Full domain | 1.05-1.15 | Forecaster experience indicates CMAQ often underestimates Chengdu O3 peak values. |
| PM2.5 | Secondary pollution likely: high RH, weak wind, low boundary layer, persistent accumulation | Urban basin / affected stations | 1.05-1.20 | PM2.5 peak may be underestimated when secondary formation dominates. |

## Meteorology And Transport

| Trigger | Pollutant | Area | Spatial factor | Time factor | Explanation |
|---|---|---|---:|---:|---|
| North wind transport from Deyang direction | O3 | North Chengdu and downwind urban area | 1.15-1.35 | CMAQ may underrepresent O3/VOCs transport and upper-air O3 mixing into near surface. |
| South wind | PM2.5/O3 | North Chengdu stations or grids | 1.05-1.15 | Forecasters note northern Chengdu can be slightly high under southerly flow. |
| High temperature, low cloud, weak wind | O3 | Urban and downwind area | 1.10-1.20 | Strong photochemical production raises O3 peak risk. |
| Cloudy or rainy period | O3 | Rain/cloud affected area | 0.80-0.95 | Weak radiation and wet weather suppress O3. |
| Precipitation >= 0.5 mm/h or persistent precipitation | PM2.5 | Rain affected area | 0.75-0.90 | Wet scavenging and improved dispersion lower PM2.5. |
| North-to-south wind entering Chengdu, wind speed >= 4 m/s for about 4 h | PM2.5 | Affected urban area | 0.70-0.90 | Forecaster rule: sustained inflow wind supports pollution dispersion. |
| Weak wind, high RH, low boundary layer at night | PM2.5 | Urban basin / station grids | 1.05-1.20 | Stable nocturnal accumulation raises PM2.5. |

## Time Correction

| Diagnosis | Correction |
|---|---|
| O3 peak occurs too early in CMAQ | Reduce factor before the meteorologically favored peak by 0.90-0.95; raise post-peak/afternoon hours by 1.10-1.20. |
| O3 peak is too low under strong photochemical conditions | Raise 13:00-18:00 by 1.10-1.30, capped by O3 coefficient limits. |
| PM2.5 improvement is too early in CMAQ | Maintain or raise concentration by 1.05-1.20 before confirmed dispersive wind enters Chengdu. |
| Clear precipitation or dispersive wind starts | Lower affected PM2.5 by 0.70-0.90 after start time. |
| Forecast horizon exceeds 5 days | Use smaller factors and report qualitative trend uncertainty. |

## Observation Constraint

When station observations are available for the same timestamp during historical evaluation or near-real-time diagnosis, blend the expert-corrected model value with the station observation before final smoothing. The v1 default is 35% model correction and 65% observation. Do not apply this to future hours where observations do not exist. This preserves the expert-system forecast path while allowing diagnostic products to better match station spatial patterns.

## Path Selection

- `anchor_trend`: use when both domain spatial distribution and domain temporal evolution are credible.
- `time_only`: use when CMAQ high-value areas are credible but trend, peak timing, or improvement timing is inconsistent with Windy Chengdu.
- `space_then_time`: use when CMAQ high-value areas contradict meteorological transport, precipitation, or dispersion signals.

Always explain the triggered rules in the report. State whether the adjustment is a full-domain correction, regional correction, station-grid time correction, or smoothing effect.

## Forecaster Decision Chain From The Updated Experience

Use this chain before deciding coefficients:

1. Start with meteorology, not CMAQ. Use Windy/EC, weather maps, precipitation, wind field, cloud/radiation, humidity, boundary-layer/mixing, and if available meteorological consultation to form a prior trend.
2. Compare CMAQ with the meteorological prior and observations. If they agree, trust CMAQ as trend, rise-rate, and turning-point guidance, but anchor the current state with observations where available.
3. If they disagree, identify which source is more credible. First check whether the meteorological driver may be wrong, especially GFS wind speed or precipitation that drives CMAQ; compare EC/Windy and ensemble or consultation signals.
4. Compare multi-model forecasts when available: 14-day GFS-driven, 30-day CFS-driven, IFS-driven, and other model runs. If multiple models agree, the synoptic pattern is more credible and correction should stay close to model trend. If models diverge, shrink correction strength and state uncertainty.
5. For 00/12 run-to-run changes, do not fully adjust on the first large jump. Track at least about one day; after the probability of the new pattern rises, allow a stronger correction.
6. Manual quantitative correction is most suitable within 3-5 days. Beyond 5 days, keep factors conservative and emphasize qualitative trend.

## Updated Forecaster Rules

| Experience signal | Pollutant | Typical CMAQ issue | Correction action |
|---|---|---|---|
| Chengdu routine simulation | PM2.5 | Usually high-biased | Apply light full-domain damping around 0.90-0.95 unless secondary formation or observations contradict it. |
| Chengdu routine simulation | O3 | Usually low-biased, especially peak value | Apply light full-domain increase around 1.05-1.15, then refine by photochemistry, cloud/rain, wind, and transport. |
| Pollution event process | PM2.5/O3 | CMAQ can capture the process, but often ends/improves too early | Delay improvement by about 4-6 h when cold-air or dispersive wind arrives later than CMAQ implies. Before confirmed improvement, maintain or raise PM2.5 by 1.05-1.20. |
| Strong cold air or wind-zone advancement | PM2.5 | Improvement timing uncertain and often too early | Within 24 h, track the real large-wind-zone advance against forecast wind-zone advance. Treat north-to-south wind speed >=4 m/s lasting about 4 h as a credible dispersion signal. |
| PM2.5 rapid jump with high secondary share | PM2.5 | Peak can be underestimated because secondary generation speed suddenly accelerates | Raise affected peak hours/areas 1.05-1.20 and explain as secondary formation under high RH, weak wind, low PBL, persistent accumulation. |
| Morning rush-hour timing | PM2.5 | Diurnal peak is often simulated too early; actual peak tends to occur after morning rush hour | Raise late-morning hours after rush hour, typically 1.05-1.10 when no rain or strong wind has begun. |
| Pollution initial-stage observed concentration below CMAQ | PM2.5/O3 | Real emissions may be lower than inventory | Make peak forecast more optimistic, shrink upward corrections, and verify with NO2 and component-network data if available. |
| Pollution initial-stage observed concentration above CMAQ | PM2.5/O3 | Real emissions or precursors may be higher than inventory | Pay attention to higher peak risk; verify with NO2 and component-network data, then raise peak hours if supported. |
| South wind | PM2.5/O3 | Northern Chengdu can be slightly high | Raise north stations/grids about 1.05-1.15 if consistent with spatial pattern. |
| North wind from Deyang direction | O3 | Transport and upper-air O3 mixing can be underestimated | Raise north/downwind urban Chengdu O3 about 1.15-1.35. Explain Deyang VOCs and aloft O3 influence that near-surface monitoring may miss. |
| O3 day-of forecast, 08:00 NO2 <=20, VOCs <=30 ppb, afternoon southerly wind force 3+, acceptable cloud/radiation | O3 | Exceedance risk can be controlled | Treat as a "recoverable good day"; cap or damp same-day O3 so the city has a chance to stay within 160 unless observations/meteorology later contradict it. |
| High ridge or Qinghai-high sunny weather | O3 | Production is fast but diffusion can also be good | In the first 1-2 pollution-start days, if PBL can reach about 1200 m or more and southerly wind is force 2-3, keep O3 near/below 160 and avoid excessive upward correction. |
| Subtropical high with high humidity and stagnant conditions | O3 | Diffusion is poor and high values are more likely | Raise O3 afternoon/high-value areas 1.10-1.20, especially with weak wind, high humidity, low cloud/radiation not suppressed by rain. |
| Cloudy/rainy period | O3 | Photochemical production suppressed | Lower O3 about 0.80-0.95 during affected hours. |
| Precipitation or persistent rain | PM2.5 | Wet scavenging and dispersion improve | Lower PM2.5 about 0.75-0.90 during and after the affected period. |

## Sparse-Or-No Observation Strategy

The skill must still produce a correction when observations are sparse or unavailable:

- With matched station observations at a timestamp, use observation-constrained nudging before smoothing, defaulting to 65% observation and 35% expert-corrected model.
- With only a few stations or a few hours, use observations only for available station-hour anchors. Do not fill all future values with observed values; future trend and turning points still come from CMAQ plus meteorology.
- With no observation records but station metadata available, run all station-grid proxy corrections from CMAQ, Windy/EC prior, and expert coefficients; set `observed` blank and skip nudging.
- With no observation directory or station metadata, use a Chengdu city-mean proxy station at the city center so the workflow still produces city-level corrected time series, figures, and an assessment. Mark spatial station detail as unavailable.
- In sparse/no observation modes, rely more on conservative factors, multi-model agreement, run-to-run stability, and 3-5 day horizon limits. Report uncertainty explicitly.

## Validation Target

Current correction target is to improve the city-mean forecast and optimize high-value stations. Validate with:

- City mean raw-vs-corrected-vs-observed MAE when observations exist.
- High-value station peak timing, peak magnitude, and whether key stations move closer to observations.
- Spatial plausibility: high-value bands should match wind transport, precipitation, cloud/radiation, and dispersion signals.
- Temporal plausibility: peak timing and improvement timing should match forecaster/Windy/EC prior, especially the 4-6 h improvement-delay rule.
