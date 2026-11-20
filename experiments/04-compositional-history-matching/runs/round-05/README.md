# Round 5 · Test pore volume along I12-W to P16

Round four's first 1,789 days of production and the water-saturation profile along the path showed an advancing front and an underprediction at P16. Starting from round4_connectivity, the model reduced only the local pore volume. Among 19 DATA/INC files, only PORO.inc changed. The affected 1,120 active cells had porosity multipliers of approximately 0.50 to 0.9923.

At day 1,439 the endpoint water saturation rose from 0.180691 to 0.190653 and the P16 water rate from 12.91 to 27.28 m³/d. Across 2,891 days and 516 steps the combined NRMSE fell to 11.6202% and P16 water-rate RMSE to 446.0566 m³/d. The 11 path-node saturations at day 1,439 agree with the native arrays.

## Files

- [Decision JSON](../../decisions/round5_decision.json)
- [Editing code](../../decision_source/edit_round5.py)
- [Model replies](trace/answers.jsonl)
- [Execution records](trace/tool_calls.jsonl)
- [Input changes](inputs/round5_path_storage/diff.json)
- [Field edit](../../decisions/final_field_edit.json)
- [Full-period score](../../evidence/round5_path_storage/oil_water_score.json)
- [Day-1,439 diagnostics](diagnostics-1439/)
