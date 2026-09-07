---
name: planner-core
description: Core planning guidance for the pollution-analysis planner. Use this skill to turn a user request into a short executable plan with the right tool hints and optional business skill references.
---

# Planner Core

Use this skill when generating the execution plan for a user turn.

## Responsibilities

1. Understand the current user request, recent dialogue, recent tool results, and user memory.
2. Break the request into a short list of concrete executable steps.
3. Choose the most suitable `tool_hint` for each step.
4. When a step should follow a domain skill, write the skill name into `skill_hint`. If multiple skills are relevant, separate them with commas.

## Planning Rules

- Prefer `reasoning` when the existing context is already enough to answer a follow-up.
- Use `web_search` only when external information is truly necessary.
- Use `read_file` when the step depends on local files, specs, prompts, code, or documents in the project.
- Use `current_time` when the task depends on expressions such as "now," "today," "tomorrow," "recently," "the next 14 days," or localized equivalents.
- Use `cmaq_forecast_qa` for CMAQ numeric analysis and structured data summaries.
- Use `cmaq_plot_data` for charts, plots, maps, spatial distribution, or visual outputs.
- Use `rsm_reduction` with `skill_hint=run-rsm-reduction` for emission-reduction benefits, RSM scenarios, control-matrix cases, or PM2.5 improvement amounts.
- Use `pollution_warning` with skill_hint `chengdu-pollution-alerming` when the user provides pollutant concentrations, forecast AQI values, PM2.5/O3 primary pollutant context, asks whether to start a Chengdu heavy-pollution warning, or asks for matching emergency response measures. Do this before `web_search` unless the user explicitly asks for current external news or official real-time notices.
- If the user explicitly mentions `chengdu-pollution-alerming`, set skill_hint to `chengdu-pollution-alerming`.
- Preserve explicit date or time ranges as conversation variables. If a user asks for `2026.5.27-29`, every CMAQ analysis and plotting step must include that range in the step title.
- When a plotting step has a conversation time range, the executor must call `cmaq_plot_data` with `start_time` and `end_time`; do not rely on default full-period plotting.
- If the user asks for both a time-series chart and a spatial distribution map for the same metric and period, plan one `cmaq_plot_data` step using `plot="both"` instead of separate plot steps.
- Do not plan multiple spatial map steps for peak hours unless the user explicitly asks for hourly snapshots, multiple panels, or animation.
- Use `memory` only when the user is clearly asking the system to remember a preference or working habit.
- Use `shell` only when a controlled command execution is actually needed.

## Output Rules

- Keep steps short and actionable.
- Avoid duplicate or overlapping steps.
- Do not output the final synthesis step; the runtime adds it automatically.
- If a domain skill obviously applies, prefer referencing it in `skill_hint` instead of restating its workflow from memory.
