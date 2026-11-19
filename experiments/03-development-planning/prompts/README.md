# Prompts

Every prompt contains the entire base DATA deck. Round 1 is ready to send. Rounds 2–5 are review templates. The run command fills each later prompt with the arm's real observations before sending it.

| Round | File | Observations added at runtime |
|---:|---|---|
| 1 | [Full initial prompt](round_1_complete.txt) | None |
| 2 | [Round 2 template](round_2_template.txt) | Round 1 decisions and FOPT, plus round 1 feedback |
| 3 | [Round 3 template](round_3_template.txt) | Decisions and FOPT from rounds 1–2, plus round 2 feedback |
| 4 | [Round 4 template](round_4_template.txt) | Decisions and FOPT from rounds 1–3, plus round 3 feedback |
| 5 | [Round 5 template](round_5_template.txt) | Decisions and FOPT from rounds 1–4, plus round 4 feedback |

Feedback contains the complete accepted-substep production history and three final 50-row by 60-column fields: absolute reservoir pressure, oil saturation, and water saturation. When the preceding proposal has no valid simulation output, the prompt records its status. The history table lists the proposals from the current arm.

The [response example](../examples/output_format.json) is for experiment operators. The task specifies the JSON fields and feasible ranges. Each round starts a new model process with the current prompt. For manual submission, use a fresh conversation with the same named model.

Regenerate the review files with `python materialize_prompts.py`. To preview the exact next prompt for a study, use `python -m fopt5 prompt --arm llm --study runs/jutuldarcy_pso --output next_prompt.txt`.
