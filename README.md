# LLM Reservoir Benchmarks

This repository collects experiments on language models for reservoir development and history matching. The first two experiments in the four-experiment study are available below. Each lives in its own directory under [experiments](experiments/) with its inputs, prompts, code, and instructions.

| Experiment | Decision made by the model | Simulator and evaluation |
|---|---|---|
| [01 · Development planning](experiments/01-development-planning/) | Choose four well locations and five BHP targets per well in a SPE10 submodel | JutulDarcy. Compare the best ten-year cumulative oil from five model evaluations with 25 synchronous PSO evaluations. |
| [02 · Single-step history matching](experiments/02-history-matching/) | Propose one set of porosity and directional permeability edits for the PUNQ model | OPM Flow. Compare well-level and field-level production errors before and after that one update. |

For the planning benchmark, start with its [README](experiments/01-development-planning/README.md) or [first-round English prompt](experiments/01-development-planning/prompts/round_1_complete.txt). For the history-matching experiment, inspect the [exact prompt](experiments/02-history-matching/prompts/single_step.txt), [model reply](experiments/02-history-matching/results/edits.json), and [well and field results](experiments/02-history-matching/README.md#recorded-results).

To verify the recorded history match from the repository root, run the following command with Python 3.10 or later. The verifier reads the bundled numerical outputs and runs offline.

~~~sh
python experiments/02-history-matching/reproduce.py verify
~~~

Run the other commands in the directory of the corresponding experiment. The earlier standalone layout of experiment 01 remains available at [its original commit](https://github.com/syclong/llm-reservoir-planning-benchmark/tree/4ba53b8c602bfbc398a469fe17f5ffec276d7720).

The [MIT license](LICENSE) covers the project's original code, prompts, and documentation. The experiment READMEs identify the numerical data and third-party simulators and their provenance.
