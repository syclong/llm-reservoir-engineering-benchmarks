# Experiment design

## Reservoir and objective

The benchmark tests whether a language model can propose feasible well locations and bottom-hole pressure (BHP) schedules with a limited number of reservoir simulations. Each proposal is a new ten-year development plan evaluated from the same initial state. The objective is field cumulative oil production at surface conditions (FOPT) on day 3650 in standard cubic meters (sm³).

The model has 60 × 50 × 1 active cells, each 32 × 32 × 10 m. Initial pressure is 260 bar. Initial oil and water saturations are 0.8 and 0.2. The plan has two vertical water injectors and two vertical oil producers, all completed in layer 1. Any pair of well centers must be at least 250 m apart.

A proposal supplies 28 numbers. Each of the four wells has an integer grid location (I,J) and five absolute BHP targets. Each target applies for 730 days. Injector BHP is 275–450 bar and producer BHP is 100–250 bar. Both ranges include their endpoints. Case 1A has no per-well rate cap. [Complete base deck](../inputs/BASE.DATA) · [Data provenance](data-and-software.md)

## Simulation and shut-in

Both arms use JutulDarcy 0.4.1 with Jutul 0.5.9. The Julia bridge reads the economic water-cut limits in WECON. At the end of each accepted solver substep it calculates the surface water cut of each producer from its surface water and liquid rates. The first substep reaching a water cut of 0.78 contributes its full production. The well closes permanently from the next substep onward, including across BHP schedule changes. The shut-in time is reported at substep resolution. [Julia evaluator](../solver/evaluate.jl)

## Language-model arm

The first round provides the task, the output format, the operating constraints, and the complete base deck. The model returns a JSON object containing all 28 decision variables. From the second round onward the prompt includes every earlier plan, its status, and its FOPT from the same arm. Only the immediately preceding round contributes the complete production history and the final PRESSURE, SOIL, and SWAT fields. Each field contains 50 rows in J and 60 columns in I, with I varying fastest. Pressure is absolute in bar. The text representation preserves the recorded floating-point values.

Each round supplies the complete prompt to the named model and accepts one response. Automatic and manual runs record the same model label from the [model file](../model.json). The harness validates the proposal, renders a DATA deck, runs the simulator, and assembles the following prompt. An invalid or duplicate proposal consumes a proposal slot and receives a missing score. A failed simulation that was dispatched counts against the simulation budget. A missing feedback field is identified by the status of that round. [Prompt templates](../prompts/README.md) · [Five-round protocol](../protocol.json)

## Synchronous PSO with 25 evaluations

There are five particles and five generations. Generation 1 evaluates the five initial positions. Generations 2–5 each update and evaluate the entire swarm. The runner saves all five plans before dispatching a generation. After all five results settle, the optimizer updates personal and global bests in particle order. Feedback to PSO consists of FOPT from its own completed generations.

The default seed is 20261118. Initial positions are uniform on the 28-dimensional unit cube. Initial velocities are uniform on [−0.1, 0.1]. The inertia coefficient is 0.7298 and the cognitive and social coefficients are both 1.49618, with independent random draws by dimension. Each normalized velocity component is limited to ±0.25. A step that crosses a boundary is reflected.

Positions map to integer grid cells and pressure targets rounded to two decimal places. Wells are placed in the order INJ1, INJ2, PROD1, PROD2. If a proposed cell violates the spacing constraint, the repair chooses the nearest feasible cell, breaking ties first by I and then by J. [Synchronous protocol](../pso25/protocol.json) · [Swarm update](../pso25/swarm.py)

## Equal-budget alternative

The five-evaluation alternative uses asynchronous round-robin PSO with two particles. Rounds 1 and 2 evaluate their initial positions. Rounds 3, 4, and 5 update particles 1, 2, and 1, respectively. Each round evaluates one plan. This alternative uses the same seed, position encoding, boundary handling, and velocity coefficients described above. The audit reconstructs each proposal from the scores available at the time.

## Scoring and interpretation

The primary comparison takes the best of five LLM evaluations and the best of 25 synchronous PSO evaluations. The report also compares the five LLM evaluations with PSO's initial generation of five. For the separate asynchronous experiment, both arms have five proposal slots. The fifth proposal's FOPT, each best-so-far value, valid proposal counts, and actual solver calls are recorded. An absolute difference of at most 1 sm³ is a tie.

FOPT is the sum of each producer's surface oil rate multiplied by the accepted substep duration. The audit verifies the sum of well cumulatives, injection and production volume balance, initial and final oil inventories, the actual completion cells, flowing BHP, and persistent shut-in. The oil-inventory change must agree with integrated oil production within the larger of 2 sm³ and 0.02% of cumulative oil. [Score extraction](../fopt5/engine.py) · [Independent PSO audit](../pso25/audit.py)

The two methods receive different feedback. The LLM also sees production dynamics and final spatial fields, while PSO uses the scalar objective. Report the evaluation budgets and the geological realization alongside any comparison. A five-round trajectory is one experiment with dependent observations. Independent runs and geological realizations are needed to estimate performance across cases.
