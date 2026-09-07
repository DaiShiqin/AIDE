---
name: executor-core
description: Core execution guidance for the pollution-analysis executor. Use this skill to complete one planned step with the right tools, absorb tool outputs, and produce a concise conclusion in the user's language.
---

# Executor Core

Use this skill when executing a single plan step.

## Responsibilities

1. Focus only on the current step instead of solving the whole request at once.
2. Reuse recent context when possible; do not re-run tools without a reason.
3. If `skill_hint` is present, read and follow the referenced business skills before acting.
4. Use tools only when they add evidence or produce required artifacts.
5. Write the step conclusion in the user's language after absorbing the tool results.

## Execution Rules

- Prefer direct reasoning if the step can already be completed from recent context.
- Prefer `read_file` before guessing the contents of local prompts, configs, code, or documents.
- Prefer `current_time` before assuming any absolute date or current timestamp.
- For CMAQ tasks, rely on CMAQ scripts and summaries instead of manually inferring pollutant values.
- For RSM emission-reduction tasks, use `rsm_reduction` and follow `run-rsm-reduction`; do not manually edit matrices through `shell` unless debugging the tool itself.
- For Chengdu warning tasks, use `pollution_warning` and follow `chengdu-pollution-alerming`; do not manually calculate AQI through `shell` unless debugging the tool itself.
- If the plan step already names a domain tool such as `cmaq_forecast_qa`, `cmaq_plot_data`, `pollution_warning`, or `rsm_reduction`, call that tool directly instead of substituting `shell`.
- Treat conversation variables such as `requested_start_time` and `requested_end_time` as hard constraints. When calling `cmaq_plot_data`, pass them as `start_time` and `end_time` so plots do not fall back to the full forecast period.
- When both a time series and a spatial map are needed for the same metric and period, call `cmaq_plot_data` once with `plot="both"`. Do not issue several spatial calls for peak-hour maps unless explicitly requested.
- If a tool fails, state the failure clearly and do not invent missing evidence.
- Keep shell usage minimal and controlled.

## Step Conclusion Rules

- Summarize what was learned or produced, not raw logs.
- Mention generated artifacts only if they actually exist.
- Keep the wording compact and factual.
