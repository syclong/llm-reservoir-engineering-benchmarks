# Round 1 · Early pressure, gas/oil ratio and bottom-water response

The model used the first 1,488 days of six-well baseline feedback. It set near-well horizontal permeability multipliers of 0.32–0.50, increased vertical permeability on the P14, P15 and P16 bottom-water paths, and reduced local hydrocarbon-bearing pore volume. In active hydrocarbon-bearing cells it shifted 0.007 mole fraction from C6C19 to N2C1. The main proposal changed porosity in 3,844 active cells and initial composition in 57,956 cells, together with changes in all three permeability directions.

The main candidate and the permeability-only control stopped at day 1,912 (248 steps) and day 1,809 (234 steps). A permeability-and-porosity control was prepared and queued, then withdrawn. On the common 1,281-day window the main candidate reduced field water-rate RMSE from 195.96 to 155.82 m³/d. At day 1,488 P14 water production rose from 1.29 to 199.82 m³/d against an observed 862.36 m³/d.

## Files

- [Decision JSON](../../decisions/round1_decision.json)
- [Editing code](../../decision_source/edit_round1.py)
- [Model replies](trace/answers.jsonl)
- [Execution records](trace/tool_calls.jsonl)
- [Task messages](trace/inputs.jsonl)
- [Main candidate](inputs/round1_full/diff.json)
- [Permeability-only control](inputs/round1_k_only/diff.json)
- [Permeability-and-porosity control](inputs/round1_k_phi/diff.json)
- [Common-window scores](../../evidence/partial_runs/round2_oil_water_comparison_day1281.json)
