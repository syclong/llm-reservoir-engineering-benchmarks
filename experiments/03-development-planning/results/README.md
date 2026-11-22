# Recorded development-planning results

[Download the full simulation archive (ZIP, 7.71 MiB)](https://raw.githubusercontent.com/syclong/llm-reservoir-engineering-benchmarks/main/experiments/03-development-planning/results/simulation-results.zip)

The archive contains all 30 evaluations in the final comparison. Each candidate was simulated for 3,650 days with JutulDarcy 0.4.1 from the same initial state. The objective is field cumulative surface oil production (FOPT), in standard cubic meters.

| Arm | Simulations | Best FOPT (sm³) | Best proposal |
|---|---:|---:|---|
| LLM (`gpt-6-astra`) | 5 | 1,794,847.76 | Round 3 |
| Particle swarm (5 particles × 5 generations) | 25 | 1,648,907.20 | Generation 4, particle 2 (evaluation 17) |

The best LLM plan produced 145,940.55 sm³ more oil over ten years, or 8.85% relative to the best particle swarm plan. From round two, the LLM received production history and final cell fields from its preceding plan. The swarm updated from its own generation scores with seed 20261118. [Study design](../docs/experiment-design.md)

## Score tables

- [Final comparison and both best plans](comparison.json)
- [All five LLM plans, scores, and incumbents](llm_rounds.csv)
- [All 25 particle plans and scores](particles.csv)
- [Five generation summaries](generations.csv)

## Inside the archive

The folders `llm/r01` through `llm/r05` and `pso25/r01` through `pso25/r25` each contain the following files.

| File | Contents |
|---|---|
| `MODEL.DATA`, `record.json` | Executable deck, 28 well-location and pressure variables, run status, and FOPT |
| `history.csv` | Field and well production, injection, cumulative oil, water cut, and pressure over all accepted time steps |
| `jutul/steps.csv` | Substep duration and time in seconds, signed surface rates (m³/s), absolute pressures (Pa), and well status |
| `jutul/initial.csv`, `jutul/final.csv` | Cell index, pore volume (m³), absolute pressure (Pa), oil saturation, and water saturation for every one of the 3,000 active cells |
| `jutul/complete.toml`, `verification.json` | Solver completion, well controls, shut-in dates, integrated volumes, and checksums of the raw solver files |
| `feedback.txt` | Production history and final pressure (bar) and saturation matrices in the text format used for round feedback |

Each LLM round includes `prompt.txt` for replay and the submitted plan in `response.json.txt`. `llm/calls.json` records the single input message and zero registered tools for each completed response. The particle folders include the submitted plans. `pso25/generations/` contains the five batches as registered before evaluation.

## Replay the recorded scores

Run the following command from the repository root with Python 3.12 and NumPy 2.4.2.

~~~sh
python experiments/03-development-planning/reproduce.py verify
~~~

The command integrates the recorded surface oil rates over accepted substeps, checks the grid inventories and well controls, reconstructs the prompts and the five seeded particle generations, and verifies the public comparison tables. It runs offline from the supplied ZIP.
