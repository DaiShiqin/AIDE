# Plot Style

## Time-Series

- Create a clean white canvas with light grid lines and vertical day separators.
- Plot domain mean as a thick red line with circular markers.
- Plot domain max and min as lighter context lines; label them clearly.
- Add dashed horizontal threshold lines when available.
- Annotate the peak value and timestamp near the highest domain mean.
- Rotate x labels so dense hourly timestamps remain readable.
- Use Chinese labels if the final user request is Chinese and the local font supports it; otherwise use concise English labels to avoid broken glyphs.

## Spatial Map

- Draw a single time slice unless the user explicitly requests animation or multiple panels.
- Use `imshow` or `pcolormesh` with discrete color levels and a blue-green-yellow-orange-red palette.
- Put the pollutant and timestamp in the title area; put the unit near the colorbar or top right.
- If `WSPD10` and `WDIR10` exist, overlay sparse wind vectors.
- If projection metadata is available, compute approximate lon/lat ticks from IOAPI Lambert attributes. If not, label axes as row/column.
- Keep final PNG large enough for inspection: default width around 900-1100 px.

## Final Answer

- State the plotted variable and unit.
- State the time coverage or selected time.
- Include the PNG with an absolute local path.
- Mention any important caveat, especially when `_EXTRA` variables lack units or when a fallback variable is used.
