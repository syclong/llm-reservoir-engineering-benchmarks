# Reading and Editing Reservoir Models with Large Language Models

Four benchmarks test how large language models use reservoir geometry, rock properties, well controls, and production history to make engineering decisions. The tasks range from identifying a connected sand body in one model deck to editing a three-dimensional property field over five rounds of history matching.

| Experiment | Model task | Evaluation |
|---|---|---|
| [01 · Reservoir interpretation and interwell connectivity](experiments/01-reservoir-connectivity/) | Interpret a numerical deck and infer connectivity by layer and between open completions. | Compare a single model reply with face-connected components of the reservoir grid. |
| [02 · Single-step history matching](experiments/02-history-matching/) | Propose one set of porosity and directional permeability edits for the PUNQ model. | OPM Flow measures well and field oil/water errors before and after the update. |
| [03 · Development planning](experiments/03-development-planning/) | Choose four well locations and five bottom-hole pressure targets per well in a SPE10 submodel. | The best of five LLM plans produced 1,794,847.76 sm³ in ten years, compared with 1,648,907.20 sm³ for the best of 25 particle swarm evaluations. |
| [04 · Five-round compositional reservoir history matching](experiments/04-compositional-history-matching/) | Use oil and water rates, water saturation, and grid connectivity to choose spatial property edits in UNISIM-IV-2026. | Across 2,891 days, combined field/well NRMSE fell from 37.9776% at baseline to 11.6202% for the selected candidate. |

## Explore the experiments

| Experiment | Materials |
|---|---|
| 01 | [Complete prompt](experiments/01-reservoir-connectivity/prompts/single_step.txt) · [Model reply](experiments/01-reservoir-connectivity/results/model_reply.json) · [Item-level scores](experiments/01-reservoir-connectivity/results/score.json) |
| 02 | [Prompt for new runs](experiments/02-history-matching/prompts/single_step.txt) · [Model edits](experiments/02-history-matching/results/edits.json) · [Well and field results](experiments/02-history-matching/README.md#recorded-results) |
| 03 | [First-round prompt](experiments/03-development-planning/prompts/round_1_complete.txt) · [Recorded results and download](experiments/03-development-planning/results/) · [Final comparison](experiments/03-development-planning/results/comparison.json) |
| 04 | [Five decisions](experiments/04-compositional-history-matching/decisions/) · [Round-five editing code](experiments/04-compositional-history-matching/decision_source/edit_round5.py) · [Production curves](experiments/04-compositional-history-matching/results/) · [Full-period scores](experiments/04-compositional-history-matching/evidence/full_period_candidate_ranking.json) |

## Reproduce the recorded results

Run these commands from the repository root. Experiments 01 and 02 support Python 3.11 or later. Experiment 03 uses Python 3.12 and NumPy 2.4.2. Experiment 04 uses NumPy and pandas for score replay.

~~~sh
python experiments/01-reservoir-connectivity/reproduce.py verify
python experiments/02-history-matching/reproduce.py verify
python experiments/03-development-planning/reproduce.py verify
python experiments/04-compositional-history-matching/reproduce.py verify
~~~

For new experiment 03 simulations, see the [installation and run instructions](experiments/03-development-planning/README.md). The earlier standalone development-planning benchmark is available at [its original commit](https://github.com/syclong/llm-reservoir-engineering-benchmarks/tree/4ba53b8c602bfbc398a469fe17f5ffec276d7720).

The [MIT license](LICENSE) covers the project's original code, prompts, and documentation. The experiments document their numerical inputs and third-party simulators in their respective directories.
