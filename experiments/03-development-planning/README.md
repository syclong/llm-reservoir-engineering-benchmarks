# Experiment 03 · Reservoir development planning

Compare language-model proposals with particle swarm optimization (PSO) for joint well placement and bottom-hole pressure control. Each plan specifies two injectors, two producers, and five pressure periods per well. JutulDarcy evaluates it from the same initial state over 3,650 days. The objective is field cumulative surface oil production (FOPT) in standard cubic meters.

The recorded comparison uses five LLM proposals and 25 particle swarm evaluations (five particles in each of five generations, including the initial swarm). The best ten-year cumulative oil was **1,794,847.76 sm³** for the LLM and **1,648,907.20 sm³** for the swarm. [Recorded results and full simulation download](results/) · [Final comparison](results/comparison.json) · [Experiment design](docs/experiment-design.md) · [Data provenance](docs/data-and-software.md)

## Model

The model is **gpt-6-astra**. The [model file](model.json) contains a single field.

~~~json
{"model": "gpt-6-astra"}
~~~

Automatic runs use the local `llm` command on PATH. It must already support the named model. Each round runs a new process, writes the complete prompt to standard input, and reads one proposal from standard output. Alternatively, generate the prompt and submit the model's response as a file. Both paths use the same validator, simulator, and scoring code.

## Install

Use Python 3.12 and Julia 1.10.9 to match the development environment. From this experiment directory, install the numerical dependencies and run the tests.

~~~sh
python -m pip install -r requirements.txt
julia --project=solver -e "using Pkg; Pkg.instantiate()"
python -m unittest discover -s tests -v
~~~

The PSO and auditing commands run independently of the local model command. For a Julia installation outside PATH, set `FOPT5_JULIA`. `FOPT5_JULIA_PROJECT`, `FOPT5_JULIA_DEPOT`, and `FOPT5_JULIA_THREADS` can select a Julia environment, package directory, and thread count.

## Run the benchmark

~~~sh
python -m fopt5 run --arm llm --study runs/jutuldarcy_pso
python -m pso25 run --study runs/jutuldarcy_pso25 --workers 5
python -m pso25 audit --study runs/jutuldarcy_pso25
python -m pso25 compare --study runs/jutuldarcy_pso25 --llm-study runs/jutuldarcy_pso --archive dist/PSO25_LLM5_results.zip
~~~

Every PSO particle is one complete 28-variable plan. All five plans are registered before the first result of the generation is used. The default seed is 20261118. Set `--workers` from 1 to 5 for the resources available. The comparison checks that both arms used matching physics, scoring code, and simulator settings. It writes individual plans to `particles.csv`, generation statistics to `generations.csv`, and the comparison to `comparison-report.md`.

For manual LLM evaluation, repeat the following pair of commands for up to five rounds. Give the named model the exact contents of `next_prompt.txt` and save its original JSON reply as `proposal.json`. Each preview incorporates only the observations available at that round. Each valid, unique submission dispatches one simulation.

~~~sh
python -m fopt5 preview --study runs/jutuldarcy_pso --save next_prompt.txt
python -m fopt5 submit --arm llm --study runs/jutuldarcy_pso --response proposal.json
~~~

For the asynchronous five-evaluation alternative, use the LLM study directory.

~~~sh
python -m fopt5 run --arm pso --study runs/jutuldarcy_pso
python -m fopt5 score --study runs/jutuldarcy_pso
python -m fopt5 audit --arm llm --study runs/jutuldarcy_pso
python -m fopt5 audit --arm pso --study runs/jutuldarcy_pso
~~~

## Prompts, results, and recovery

- The [initial prompt](prompts/round_1_complete.txt) and [round 2–5 templates](prompts/README.md) contain the full base deck. The [five-proposal protocol](protocol.json) sets the input budget. The harness checks the UTF-8 byte estimate against the study limit before sending the prompt. The [synchronous PSO protocol](pso25/protocol.json) sets the extended simulation budget.
- In a new run, each valid evaluation saves its `MODEL.DATA`, accepted substep rates, initial and final cell fields, solver receipt, and verification report. The LLM arm also saves the model name, the prompt sent, and the response received. The archives can be audited offline.
- To settle an interrupted round that already has a complete simulation receipt, use `python -m fopt5 recover --arm llm --round N` with the same study directory. To use an original response that has already been delivered, add `--original-response FILE`. Use `--abandon` to mark the round as interrupted.

## Standalone script

The [standalone Python script](fopt5_llm_loop.py) embeds the complete base DATA, prompt, model file, Julia evaluator, and dependency lock. An adjacent `model.json` takes precedence over the embedded copy. Use `python fopt5_llm_loop.py` in place of `python -m fopt5`, or `python fopt5_llm_loop.py pso25` in place of `python -m pso25`. The `unpack FOPT5_local` command exports the embedded sources and Julia project for installation.

~~~sh
python materialize_prompts.py
python build_release.py --output dist --bundle-name reservoir-planning-source.zip
~~~

The release build includes an explicit list of source files. See the [MIT license](LICENSE) for the original code, prompts, and documentation and the [provenance notes](docs/data-and-software.md) for the SPE10 data and simulator.
