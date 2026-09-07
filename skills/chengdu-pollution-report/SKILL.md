---
name: chengdu-pollution-report
description: Generate end-to-end Chengdu PM2.5 or O3 pollution-process reports with requirements confirmation, AQI and warning assessment, CMAQ regional analysis, Windy meteorology, pollution mechanisms, and emergency emission-reduction recommendations. Use for forecast assessments, retrospective process reviews, cause analysis, or complete air-quality reporting workflows.
---

# Chengdu Pollution Report

## Overview

Use this skill as the orchestrator for a Chengdu PM2.5/O3 pollution report. It must collect requirements, call or reuse the warning and CMAQ correction skills, analyze Windy.com meteorology, then write a report with traceable evidence and explicit data gaps.

## Core Workflow

Follow these steps in order.

1. Confirm the user request.
   - Required: report time range and pollutant, limited to `PM2.5` or `O3`.
   - Ask a concise clarification if either is missing, ambiguous, or outside scope.
   - Also confirm output form when important: Markdown report by default; use the document skill only if the user requests `.docx`.
   - Confirm whether the report is forecast/advice, retrospective assessment, or mixed.

2. Build the evidence pack.
   - Load `references/report-structure.md` for the report outline.
   - Load `references/evidence-and-validation.md` for data routing, missing-data handling, and self-checks.
   - Use `$chengdu-pollution-alerming` for AQI, warning level, startup reason, emergency plan measures, and differentiated regional control suggestions.
   - Use the local project skill `skills/chengdu-cmaq-forecast-correction` when CMAQ correction or model diagnosis is needed.
   - Use `skills/cmaq-forecast-qa` when only CMAQ extraction/trend/hotspot summaries are needed.

3. Analyze air-quality overview.
   - Summarize overall air quality for the requested period: daily AQI/grade if available, pollutant concentration trend, start/peak/end timing, and duration.
   - Judge the warning or response category through `$chengdu-pollution-alerming`.
   - Identify heavier areas from corrected CMAQ outputs, hotspot CSV/JSON, station observations, or spatial figures. Cross-check against meteorological transport before naming key districts.

4. Analyze weather situation and meteorological factors.
   - Use `https://www.windy.com/` for Chengdu and the surrounding Sichuan Basin.
   - Cover circulation situation and ground meteorological factors.
   - Include at least: upper-level/subsidence or steering-flow signal when visible, surface wind direction/speed, humidity, precipitation, temperature, cloud/solar radiation relevance, and boundary-layer/dispersion cues when available.
   - State uncertainty when Windy information is manually read or partial.

5. Analyze pollution characteristics.
   - For PM2.5: focus on accumulation/removal, nighttime or stagnant buildup, secondary conversion risk, regional transport, and local source signatures if evidence exists.
   - For O3: focus on high temperature, radiation/cloud, low wind/downwind transport, afternoon peak behavior, and VOCs/NOx coordinated-control implications.
   - Include component analysis, VOCs, source apportionment, or reduction effectiveness only when data are provided or found in the project. Do not invent these sections.

6. Propose emergency emission-reduction measures.
   - Separate official plan-based measures from analysis-based strengthened suggestions.
   - For PM2.5 colored warnings, use yellow/orange/red measures from `$chengdu-pollution-alerming`.
   - For O3-dominated pollution, use the plan's O3/other-pollution response category and emphasize VOCs + NOx coordinated control.
   - Add regional measures from user-provided regional emission-characteristic files, project source-profile files, or the warning skill's regional differentiated measures when district or hotspot information is available.

7. Integrate the report.
   - Use a formal government and technical-report tone in the user's language.
   - Prefer concise paragraphs with numbered sections, figure/table placeholders, and evidence citations such as file paths, dates, values, and source names.
   - End with a "Consultation or Manual Confirmation Still Required" section when warning release, official approval, or missing datasets remain.

## Demand Confirmation

If the request is incomplete, return only a confirmation question block:

```text
Please confirm the following information before I generate the report:
1. Time range, for example 11-15 June 2026.
2. Pollutant: PM2.5, O3, or both.
3. Report type: forecast assessment, retrospective process review, or warning/emission-reduction advice.
4. Available data: CMAQ, observations, composition/source apportionment, emission inventory, or other file paths.
```

Do not ask again for information already present in the conversation or inferable from files.

## Output Rules

- Match the user's language; use Chinese for Chinese requests and English for English requests.
- Use `PM2.5` and `O3` consistently; do not accept other primary pollutants for this skill.
- Quantify every major claim when data exist. If a claim is qualitative, name the source of inference.
- Never fabricate monitoring, component, source-apportionment, or emission-reduction-effect values.
- For `.docx` output, use the documents skill and visually verify the rendered result.
- For Markdown output, include figure/table placeholders where supporting images or CSVs exist.

## References

- `references/report-structure.md`: report outline and section-writing guidance.
- `references/evidence-and-validation.md`: data sources, tool routing, missing-data rules, and final self-checklist.
