# Each worker receives a Python-validated DATA deck and an empty output directory.
using Jutul, JutulDarcy, LinearAlgebra, SHA, TOML

const WELLS = (:INJ1, :INJ2, :PROD1, :PROD2)
const PRODUCERS = (:PROD1, :PROD2)
const DAY = 86400.0

function watercut_limits(deck)
    # This reader skips WECON. Apply the whole-well permanent shut-in form used by this benchmark.
    block = match(r"(?ms)^WECON\s*\n(.*?)^\s*/\s*$", deck)
    isnothing(block) && error("The DATA deck has no economic shut-in records")
    limits = Dict{Symbol, Float64}()
    for line in split(strip(block.captures[1]), '\n')
        rec = match(r"^\s*'(PROD[12])'\s+2\*\s+([0-9.]+)\s+2\*\s+'WELL'\s+'NO'\s*/\s*$", line)
        isnothing(rec) && error("Unrecognized WECON record")
        key = Symbol(rec.captures[1])
        haskey(limits, key) && error("Duplicate economic limit")
        limits[key] = parse(Float64, rec.captures[2])
    end
    @assert Set(keys(limits)) == Set(PRODUCERS) && all(==(0.78), values(limits))
    return limits
end

facility(forces, w) = haskey(forces, :Facility) ? :Facility : Symbol(w, "_ctrl")

function describe_case(case, mesh)
    model = case.model
    @assert Set(JutulDarcy.well_symbols(model)) == Set(WELLS)
    @assert length(case.dt) == 100 && all(t -> isapprox(t, 36.5*DAY), case.dt)
    @assert sort(mesh.cell_map) == collect(1:3000)
    wells = Dict{String, Any}()
    for w in WELLS
        perf = only(Jutul.physical_representation(model[w]).perforations.reservoir)
        cart = CartesianIndices((60, 50, 1))[mesh.cell_map[perf]]
        targets = Float64[]
        for (index, f) in enumerate(case.forces)
            ctrl = f[facility(f, w)].control[w]
            @assert ctrl.target isa BottomHolePressureTarget
            target = ctrl.target.value / 1e5
            if mod1(index, 20) == 1
                push!(targets, target)
            else
                @assert target == last(targets)
            end
        end
        wells[String(w)] = Dict("ijk" => collect(Tuple(cart)), "bhp_bar" => targets)
    end
    return wells
end

function write_cells(path, state, order, pv, water, oil)
    open(path, "w") do io
        println(io, "cell,PV_m3,PRESSURE_Pa,SOIL,SWAT")
        for (cart, ix) in enumerate(order)
            println(io, join((cart, pv[ix], state[:Pressure][ix],
                state[:Saturations][oil, ix], state[:Saturations][water, ix]), ','))
        end
    end
end

function evaluate(deck, out)
    @assert pkgversion(JutulDarcy) == v"0.4.1" && pkgversion(Jutul) == v"0.5.9"
    mkpath(out)
    isempty(readdir(out)) || error("The solver output directory must be empty")
    limits = watercut_limits(read(deck, String))
    case = setup_case_from_data_file(deck; simple_well = true)
    model = case.model
    mesh = Jutul.physical_representation(JutulDarcy.reservoir_domain(case))
    order = sortperm(mesh.cell_map)
    phases = JutulDarcy.get_phases(model[:Reservoir].system)
    @assert length(phases) == 2
    water = only(findall(p -> p isa AqueousPhase, phases))
    oil = only(findall(p -> p isa LiquidPhase, phases))
    pv = pore_volume(JutulDarcy.reservoir_domain(model))
    wells = describe_case(case, mesh)
    write_cells(joinpath(out, "initial.csv"), case.state0[:Reservoir], order, pv, water, oil)

    # Count only converged, accepted substeps. Record the end-of-step surface rates before applying new shut-ins to later substeps.
    elapsed = Ref(0.0)
    events = Dict{String, Float64}()
    open(joinpath(out, "steps.csv"), "w") do io
        names = [string(w, "_", k) for w in WELLS for k in ("qo_m3s", "qw_m3s", "bhp_Pa", "open_bhp")]
        println(io, join(["time_s", "dt_s", "FPR_Pa", names...], ','))
        function after_ministep(done, report, sim, dt, f, max_iter, config)
            done || return (done, report)
            elapsed[] += dt
            state = sim.storage.state
            p = state[:Reservoir][:Pressure]
            sw = state[:Reservoir][:Saturations]
            # FPR is the hydrocarbon-pore-volume-weighted pressure in Pa.
            hc = sum(i -> pv[i]*(1.0-Jutul.value(sw[water, i])), eachindex(pv))
            hp = sum(i -> pv[i]*(1.0-Jutul.value(sw[water, i]))*Jutul.value(p[i]), eachindex(pv))
            row = Float64[elapsed[], dt, hp/hc]
            to_close = Symbol[]
            for w in WELLS
                key = facility(f, w)
                group = state[key]
                values = JutulDarcy.FacilityVariablesForWell(model[key], group, w; drop_ad = true)
                qo, qw = values.surface_liquid_rate, values.surface_aqueous_rate
                ctrl = group.WellGroupConfiguration.operating_controls[w]
                append!(row, (qo, qw, values.bottom_hole_pressure, ctrl isa JutulDarcy.DisabledControl ? 0.0 : 1.0))
                if w in PRODUCERS && !haskey(events, String(w)) && qo+qw < -1e-14
                    qw/(qw+qo) >= limits[w] && push!(to_close, w)
                end
            end
            println(io, join(row, ','))
            for w in to_close
                events[String(w)] = elapsed[]/DAY
                key = facility(f, w)
                closed = DisabledControl()
                # Controls can share a dictionary within a BHP period. The original targets for all five periods are already captured.
                for future in case.forces
                    future[facility(future,w)].control[w] = closed
                end
                f[key].control[w] = closed
                cfg = state[key].WellGroupConfiguration
                cfg.operating_controls[w] = closed
                cfg.requested_controls[w] = closed
            end
            return (done, report)
        end
        sim, cfg = setup_reservoir_simulator(case; info_level = -1, post_ministep_hook = after_ministep)
        result = Jutul.simulate!(sim, case.dt; forces = case.forces, config = cfg)
        @assert length(result.states) == length(case.dt) && isapprox(elapsed[], sum(case.dt); atol=1e-5)
        write_cells(joinpath(out, "final.csv"), last(result.states)[:Reservoir], order, pv, water, oil)
    end
    record = Dict("simulator"=>"JutulDarcy", "version"=>string(pkgversion(JutulDarcy)),
        "jutul"=>string(pkgversion(Jutul)), "julia"=>string(VERSION), "wells"=>wells,
        "closure_day"=>events, "horizon_days"=>elapsed[]/DAY, "report_steps"=>length(case.dt),
        "data_sha256"=>bytes2hex(sha256(read(deck))))
    open(joinpath(out, "complete.tmp"), "w") do io
        TOML.print(io, record)
    end
    mv(joinpath(out, "complete.tmp"), joinpath(out, "complete.toml"))
end

function run_worker()
    # Reuse the loaded Julia libraries and rebuild the full reservoir initial state from the DATA deck for each plan.
    for job in eachline(stdin)
        deck, out = split(job, '\t'; limit=2)
        try
            evaluate(String(deck), String(out))
        catch err
            mkpath(out)
            open(joinpath(out, "error.tmp"), "w") do io
                showerror(io, err, catch_backtrace())
            end
            mv(joinpath(out, "error.tmp"), joinpath(out, "error.txt"))
        end
    end
end

if abspath(PROGRAM_FILE) == @__FILE__
    BLAS.set_num_threads(1)
    if ARGS == ["--worker"]
        run_worker()
    else
        length(ARGS) == 2 || error("Expected a model path and a results directory")
        evaluate(abspath(ARGS[1]), abspath(ARGS[2]))
    end
end
