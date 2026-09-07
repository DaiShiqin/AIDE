---
name: chengdu-pollution-alerming
description: Calculate China AQI from PM2.5, O3, PM10, SO2, NO2, and CO data, assess Chengdu heavy-pollution warning levels under the 2024 emergency plan, and return the trigger rationale and matching response measures. Use for pollutant concentrations, daily AQI forecasts, warning recommendations, or emergency-control requests for Chengdu.
---

# chengdu-pollution-alerming

## Core Workflow

Use this skill to turn pollutant inputs into an AQI-based emergency response package for Chengdu.

1. Normalize pollutant inputs into China AQI concentration units:
   - `pm25_24h`, `pm10_24h`, `so2_24h`, `no2_24h`, `o3_8h`, `o3_1h`: micrograms per cubic meter.
   - `co_24h`, `co_1h`: milligrams per cubic meter.
2. Calculate IAQI for each pollutant and select the highest IAQI as AQI.
3. Judge warning level from predicted daily AQI sequences.
4. Return:
   - AQI and primary pollutant.
   - Warning level or O3/other-pollution response category.
   - Start reason with threshold logic.
   - Matching emergency response measures from `references/emergency-response-measures.md`.

## AQI And Warning Tool

Prefer running:

```powershell
python scripts/calculate_aqi_warning.py --input input.json
```

Input shape:

```json
{
  "pollutants": {
    "pm25_24h": 82,
    "o3_8h": 145
  },
  "forecast_daily_aqi": [168, 212, 226],
  "dominant_pollutant": "PM2.5"
}
```

Use `forecast_days` when daily AQI must be calculated from pollutant concentrations:

```json
{
  "forecast_days": [
    {"pm25_24h": 78, "o3_8h": 120},
    {"pm25_24h": 165, "o3_8h": 130},
    {"pm25_24h": 180, "o3_8h": 135}
  ],
  "dominant_pollutant": "PM2.5"
}
```

If the user only provides a single observed concentration without forecast duration, calculate AQI but do not overstate warning activation; state that the forecast duration or official consultation is still needed.

## Chengdu Warning Rules

Apply the Chengdu 2024 emergency plan rules:

- Yellow warning: predicted daily AQI > 200, or daily AQI > 150 for 48 hours or more, and no higher-level condition is met.
- Orange warning: predicted daily AQI > 200 for 48 hours, or daily AQI > 150 for 72 hours or more, and no higher-level condition is met.
- Red warning: predicted daily AQI > 200 for 72 hours and daily AQI > 300 for 24 hours or more.

The plan's main colored warning system applies to PM2.5-caused heavy pollution weather. If O3 is the primary pollutant, return the O3/other-pollution response in the reference instead of forcing a yellow/orange/red PM2.5 warning unless the user provides an official warning decision.

## Response Measures

Load `references/emergency-response-measures.md` after the warning level is known. Return the relevant section only:

- Yellow: `III级响应/黄色预警` (Level III Response / Yellow Warning)
- Orange: `II级响应/橙色预警` (Level II Response / Orange Warning)
- Red: `I级响应/红色预警` (Level I Response / Red Warning)
- O3, sand, wildfire, or external transport: `其他响应措施` (Other Response Measures)

The script also returns a `response_measures` field with the matching reference section. Prefer using that field in app integrations where separate reference loading is unavailable.

Match the user's language. Use the following semantic sections, translated when needed:

```text
Warning conclusion:
Activation rationale:
AQI calculation:
Emergency response measures:
Manual or official consultation still required:
```

Always distinguish automatic threshold judgment from official approval and release procedures.
