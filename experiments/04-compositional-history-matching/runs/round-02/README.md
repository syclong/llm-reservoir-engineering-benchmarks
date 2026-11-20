# Round 2 · Adjust water arrival along lower connections

The user clarified the objective to field and well oil and water rates across the history. The model used the first round's day-1,488 production residuals and near-well saturations. Starting from round1_k_only, it increased directional permeability and reduced pore volume around the deepest bottom-water connections. At P14, P15 and P16 the additional central Kh multipliers were 3, 5 and 8; central porosity multipliers were 0.50, 0.55 and 0.65. Initial composition retained its normalized baseline values.

On the first 1,281 days the P14 water-rate RMSE fell from 170.77 to 62.77 m³/d versus round one. Water reached P15 and P16 too early. At P15 the simulated water rate on day 1,281 was 365.13 m³/d against 86.35 observed. The candidate stopped after 141 report steps at day 1,446.

## Files

- [Decision JSON](../../decisions/round2_decision.json)
- [Editing code](../../decision_source/edit_round2.py)
- [Model replies](trace/answers.jsonl)
- [Execution records](trace/tool_calls.jsonl)
- [Task messages](trace/inputs.jsonl)
- [Input changes](inputs/round2_oil_water/diff.json)
- [Window results](../../evidence/partial_runs/round2_oil_water_comparison_day1281.json)
- [Early stop](../../evidence/partial_runs/round2_oil_water/early_stop.json)
