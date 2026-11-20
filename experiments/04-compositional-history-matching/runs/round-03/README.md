# Round 3 · Delay water arrival at P15 and P16

Round two gave P16 water production of 51.11 m³/d on day 1,281 against 4.97 observed. The third candidate retained the P14 change. At P15 it reduced the additional Kh multiplier from 5 to 3 and the Kz multiplier from 3 to 1.75, and raised the porosity multiplier from 0.55 to 0.72. At P16 it reduced the additional Kh multiplier from 8 to 4 and raised the porosity multiplier from 0.65 to 0.95. The porosity multipliers use the original porosity as reference.

P15 water-rate RMSE through day 1,281 fell from 127.93 to 13.98 m³/d. By day 1,439 simulated water was still below history at P14 and P16. These residuals guided round four. Round three completed all 516 report steps over 2,891 days with a combined NRMSE of 20.7914%.

## Files

- [Decision JSON](../../decisions/round3_decision.json)
- [Editing code](../../decision_source/edit_round3.py)
- [Model replies](trace/answers.jsonl)
- [Execution records](trace/tool_calls.jsonl)
- [Input changes](inputs/round3_timing/diff.json)
- [Full-period score](../../evidence/round3_timing/oil_water_score.json)
- [Day-1,439 comparison](../../evidence/partial_runs/round3_oil_water_comparison_day1439.json)
- [Field curves](../../results/round3_field_oil_water_history.png)
