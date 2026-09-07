---
name: run-rsm-reduction
description: Run the local Chengdu/Chengyu DeepRSM workflow for PM2.5 emission-reduction benefits, scenario cases, control matrices, and regional improvement estimates. Use for requests to create or run an RSM scenario, inspect Dpm25 results, or assess 2021 modeled reduction benefits; report improvement deltas rather than current absolute concentrations.
---

# Run RSM Reduction

## Purpose

Use the local DeepRSM post-processing workflow to answer PM2.5 emission-reduction benefit questions. The workflow edits scenario rows in the two control matrices, runs the local RSM chain, then reads the matching `Dpm25_*.csv` outputs and reports 12-region PM2.5 improvement values.

Treat `Dpm25` outputs as 2021-model scenario deltas. Do not present them as current-year absolute concentrations unless the user explicitly provides a separate calibration baseline. Prefer `baseline - scenario` improvement amounts.

## Required Reference

Read `references/model-grid.md` when region names, grid dimensions, or control-matrix columns need to be mapped. It preserves the authoritative region-code mapping supplied with the local model package.

## Local Paths

- Default RSM root: `<project-root>\deepRSM\to_cdhky\to_cdhky`
- Default working directory: `<project-root>\deepRSM\to_cdhky\to_cdhky\CYDeepRSM`
- Override the working directory with the `RSM_WORKDIR` environment variable when the model is stored elsewhere.
- Outer matrix: `Control_Matrix_outer.csv`
- Inner matrix: `Control_Matrix_inner.csv`
- Runner: `run_local.py`
- Final outputs: `csv\test\Dpm25_2021_M*_caseN.csv`

## Workflow

1. Parse the user's requested scenario into:
   - matrix scope: outer `cn09CY` region, inner `cn03CY` region, or both if the request clearly says so
   - region code/name
   - pollutant factor: usually `PM25`, but also allow `NOX`, `SO2`, `NH3`, and `VOC`
   - reduction percentage
2. Convert reduction percentage to the control-matrix remaining-emission coefficient:
   - no reduction = `1.0`
   - 50% reduction = `0.5`
   - 90% reduction = `0.1`
3. Write one scenario row, called `caseN`, into both `Control_Matrix_outer.csv` and `Control_Matrix_inner.csv`.
   - Unmentioned matrix cells should remain `1.0`.
   - If only an outer reduction is requested, write the outer row with the requested coefficient and write the inner row as all `1.0`.
   - If only an inner reduction is requested, write the inner row with the requested coefficient and write the outer row as all `1.0`.
4. Run the PM chain from `CYDeepRSM`:

```powershell
python run_local.py --target pm --cases N
```

5. Read `csv\test\Dpm25_2021_M*_caseN.csv`.
   - Each file has 2 rows and 12 columns.
   - Row 1 is baseline.
   - Row 2 is scenario.
   - Report improvement as row 1 minus row 2 for each of the 12 inner `cn03CY` regions.
6. Answer in the user's language. Keep this RSM-specific presentation compact and scannable:
   - Start with one bold core conclusion that directly answers the region named by the user. If useful, also name the largest positive regional response; describe it as a model response, not a causal mechanism.
   - Use short Markdown headings and bullets for scenario settings, regional results, and interpretation. Do not concatenate all 12 region-value pairs into one paragraph.
   - State the case number, actual matrix changes, and months read. Group the 12 inner-region values into a few geographic bullets, while still reporting every region.
   - Round displayed improvement values consistently to three decimals unless the user requests otherwise.
   - State that the values are `baseline - scenario` RSM 2021 scenario improvements and that M1-M13 is a simple mean over the files read, not automatically a calendar-year mean.
   - Treat the percentages as emission-reduction settings, not PM2.5 concentration-reduction percentages.
   - Do not attach a physical unit unless the source output or model configuration establishes it. If it is unavailable, call the values “Dpm25 模型输出值”.
   - Do not infer transport direction, local-source dominance, terrain effects, or other causes from response magnitudes alone.

## Helper Script

Prefer the bundled helper for common PM2.5 reduction cases:

```powershell
python skills\run-rsm-reduction\scripts\run_pm_reduction_case.py --case 12 --outer-reduction "A:PM25=50"
```

Examples:

```powershell
# Chengdu Plain PM2.5 reduction of 50%
python scripts\run_pm_reduction_case.py --case 12 --outer-reduction "A:PM25=50"

# Chengdu urban core PM2.5 reduction of 50%
python scripts\run_pm_reduction_case.py --case 12 --inner-reduction "A:PM25=50"

# Deyang NOX reduction of 30%; Mianyang PM2.5 reduction of 50%
python scripts\run_pm_reduction_case.py --case 12 --inner-reduction "D:NOX=30" --inner-reduction "E:PM25=50"
```

Use `--dry-run` to validate parsing without editing matrices or running RSM. Use `--no-run` only when the user asks to prepare matrices without executing the model.

## Result Interpretation

`Dpm25` columns are the 12 inner regions:

`A Chengdu urban core`, `B Chengdu second-circle districts`, `C1 Chengdu suburban new towns 1`, `C2 Chengdu suburban new towns 2`, `D Deyang`, `E Mianyang`, `F Suining`, `G Leshan`, `H Meishan`, `I Ya'an`, `J Ziyang`, and `K other outer adjustment area`.

If the user asks for a final concentration, explain that this local RSM package should be used for the modeled improvement amount only unless a separate real-world baseline is supplied. Return the modeled improvement and, if useful, the scenario row values from the RSM output.


The local PM/O3 post-processing scripts honor the control-matrix values for outer `A Chengdu Plain` and inner `K other outer adjustment area`; do not warn that these regions are hardcoded to no-control.
