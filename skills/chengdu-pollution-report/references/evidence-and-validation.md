# Evidence And Validation

## Data Source Routing

Use these sources in priority order.

1. User-provided files and paths.
2. Current workspace:
   - project root: resolve from the running repository; do not assume a machine-specific absolute path.
   - CMAQ correction skill: `skills\chengdu-cmaq-forecast-correction`
   - CMAQ QA skill: `skills\cmaq-forecast-qa`
   - existing CMAQ/output folders and generated `*_summary.json`, `*_daily_domain.csv`, `*_hourly_domain.csv`, `*_hotspots.csv`.
   - regional emission or source-characteristic files if present; search for English keywords such as `emission`, `source`, `inventory`, `industry`, `district`, `region`, `profile`, and `reduction`, plus localized Chinese filename aliases when working in the original project.
3. Global warning skill:
   - `skills\chengdu-pollution-alerming`
   - use it for AQI calculation, PM2.5 warning thresholds, O3/other response, official plan measures, and regional differentiated measures.
4. Windy.com:
   - `https://www.windy.com/`
   - inspect Chengdu and surrounding Sichuan Basin layers relevant to wind, precipitation, cloud/radiation, temperature, humidity, and upper/surface circulation when available.

## CMAQ And Correction Evidence

For heavier-region analysis, prefer corrected products over raw model fields:

- `city_aggregate.csv`: city mean trend, peak, improvement.
- `station_corrected.csv`: station-level corrected concentrations.
- `diagnosis.json`: correction path, spatial/temporal credibility, rationale.
- `explanations.json`: station/area explanations.
- `space_factor.csv`: spatial correction factors.
- `figures\corrected_spatial_peak.svg/png`: corrected peak distribution.
- `*_hotspots.csv` or `*_summary.json`: raw or extracted hotspots when correction output is unavailable.

When corrected outputs are absent:

1. If user asked for a full report and CMAQ files exist, run the CMAQ correction skill workflow.
2. If no observations/met prior exist, run CMAQ QA for trend/hotspot extraction and clearly mark the result as raw CMAQ.
3. Never call a district "the most polluted" from one unsupported model grid. Use qualified wording such as "the model indicates that high values may be concentrated in..." unless observations or correction validate the conclusion.

## Windy Meteorology Checklist

Record the date/time inspected and the layer/source. Cover:

- surface wind: dominant direction, speed, convergence/stagnation, downwind districts;
- precipitation: whether there is wet scavenging or lack of removal;
- temperature: high-temperature O3 risk or low-temperature/stable PM2.5 accumulation;
- humidity: PM2.5 hygroscopic growth and secondary conversion risk;
- cloud/radiation: O3 photochemistry;
- upper/circulation: steering flow, ridge/trough, basin subsidence/stability if inspected;
- boundary-layer/mixing proxy if available; otherwise state that direct PBL evidence is unavailable.

## Warning And Measures Evidence

Use the warning skill. Report:

- forecast daily AQI sequence or calculated AQI basis;
- dominant pollutant and whether colored warning logic applies;
- warning level or O3/other response category;
- startup reason and threshold;
- mandatory plan measures;
- differentiated regional suggestions.

Always distinguish:

- `Official plan measures`: content required by the emergency plan.
- `Process-specific strengthened recommendations`: analysis-based additions.
- `Consultation still required`: official release, timing, and approval.

## Missing Data Rules

- Missing time range or pollutant: stop and ask for confirmation.
- Pollutant outside PM2.5/O3: say the skill only supports PM2.5 and O3, then ask which one to use.
- Missing Windy/API data: provide a placeholder for manual meteorology review; do not complete weather causation as fact.
- Missing component/source-apportionment data: omit those subsections or mark the limitation.
- Missing emission inventory/regional source-characteristic file: use warning skill regional measures, but label them as general differentiated suggestions.
- Missing official warning decision: provide threshold-based recommendation only.

## Final Self-Validation

Before final delivery, verify:

- The report answers the confirmed time range and pollutant only.
- The order matches the required flow: demand confirmation, overview, weather, pollution characteristics, measures, integrated report.
- Every numerical statement has a source file, tool output, user input, or visible web observation.
- Warning conclusions come from the warning skill or its rules, not from freehand text.
- Heavier regions come from corrected CMAQ, observations, or hotspot outputs and are cross-checked with meteorology.
- O3 reports do not force PM2.5 yellow/orange/red warning logic unless the user provided an official decision.
- Advanced component/source/reduction-effect analysis is omitted unless data exist.
- The report includes uncertainty and a consultation or manual-confirmation section.
- File paths and figures referenced in the report exist, unless they are clearly marked as placeholders.
