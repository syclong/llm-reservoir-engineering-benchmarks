# LLM Reservoir Benchmarks

This repository contains the first three experiments in a four-experiment study of reservoir interpretation, history matching, and development planning. Each experiment includes its numerical inputs, model prompts, code, and reproduction instructions.

| Experiment | Task given to the model | Evaluation |
|---|---|---|
| [01 · Reservoir interpretation and interwell connectivity](experiments/01-reservoir-connectivity/) | Interpret one complete numerical deck and identify connected well pairs in each reservoir layer and between open completions. | Compare one JSON reply with face-connected components of the grid. |
| [02 · Single-step history matching](experiments/02-history-matching/) | Propose one set of porosity and directional permeability edits for the PUNQ model. | Use OPM Flow to compare well-level and field-level production errors before and after the update. |
| [03 · Development planning](experiments/03-development-planning/) | Choose four well locations and five bottom-hole pressure targets per well in a SPE10 submodel. | Use JutulDarcy to compare the best ten-year cumulative oil from five model proposals with 25 synchronous particle swarm evaluations. |

For experiment 01, see the [complete prompt](experiments/01-reservoir-connectivity/prompts/single_step.txt), [original model reply](experiments/01-reservoir-connectivity/results/model_reply.json), and [item-level scores](experiments/01-reservoir-connectivity/results/score.json). For experiment 02, see the [complete prompt](experiments/02-history-matching/prompts/single_step.txt), [model edits](experiments/02-history-matching/results/edits.json), and [well and field results](experiments/02-history-matching/README.md#recorded-results). For experiment 03, see the [first-round prompt](experiments/03-development-planning/prompts/round_1_complete.txt) and [experimental design](experiments/03-development-planning/docs/experiment-design.md).

## Reproduce the recorded results

Run the following commands from the repository root to verify experiments 01 and 02 offline.

~~~sh
python experiments/01-reservoir-connectivity/reproduce.py verify
python experiments/02-history-matching/reproduce.py verify
~~~

For experiment 03, run the installation, test, and simulation commands from its [experiment directory](experiments/03-development-planning/README.md). The earlier standalone development-planning benchmark is available at [its original commit](https://github.com/syclong/llm-reservoir-planning-benchmark/tree/4ba53b8c602bfbc398a469fe17f5ffec276d7720).

The [MIT license](LICENSE) covers the project's original code, prompts, and documentation. The experiment READMEs identify the numerical data and third-party simulators and their provenance.
