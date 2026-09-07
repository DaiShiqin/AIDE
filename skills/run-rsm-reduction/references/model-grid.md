# Chengdu-Chongqing Model Grid

This mapping is derived from the model-grid reference supplied with the local DeepRSM package.

## Chengdu-Chongqing 9 km Grid

`col*row = 168*138`

1. A Chengdu Plain, `CD`
2. B Chongqing, `CQ`
3. C southern Sichuan, `CN`
4. D northeastern Sichuan, `CDB`
5. E northwestern Sichuan, `CXB`
6. F Panxi, `PX`

## Chengdu-Chongqing 3 km Grid

`col*row = 147*183`

1. A Chengdu urban core
2. B Chengdu second-circle districts
3. C1 Chengdu suburban new towns 1
4. C2 Chengdu suburban new towns 2
5. D Deyang
6. E Mianyang
7. F Suining
8. G Leshan
9. H Meishan
10. I Ya'an
11. J Ziyang
12. K other outer adjustment area

The helper scripts also recognize the original Chinese region names as localized input aliases.

## Control Matrix Notes

- `Control_Matrix_outer.csv` has 6 outer regions: `A`, `B`, `C`, `D`, `E`, `F`.
- `Control_Matrix_inner.csv` has 12 inner regions: `A`, `B`, `C1`, `C2`, `D`, `E`, `F`, `G`, `H`, `I`, `J`, `K`.
- Each region has five factors: `NOX`, `SO2`, `NH3`, `VOC`, `PM25`.
- Matrix values are remaining-emission coefficients, not reduction percentages.
- Examples:
  - 0% reduction -> write `1.0`
  - 50% reduction -> write `0.5`
  - 90% reduction -> write `0.1`
- Current runnable PM/O3 post-processing scripts honor the matrix values for outer `A Chengdu Plain` and inner `K other outer adjustment area`; these regions are no longer hardcoded to no-control.

## Output Notes

- Final PM files are in `CYDeepRSM\csv\test`.
- `Dpm25_2021_Mxx_caseN.csv` contains 2 rows x 12 columns.
- Row 1 is baseline, row 2 is scenario.
- The 12 columns map one-to-one to the 12 `cn03CY` regions above.
- Report PM2.5 improvement as `baseline - scenario`.
