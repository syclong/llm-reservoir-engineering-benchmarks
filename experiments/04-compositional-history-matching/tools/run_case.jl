# Run the case and export results using the original simulator. The script defines no solver equations, method overrides or parameter optimizer.
using JutulDarcy, Jutul, Serialization, TOML, LinearAlgebra
function main()
    BLAS.set_num_threads(4)
    case_file=abspath(ARGS[1])
    output=abspath(ARGS[2])
    last_step=length(ARGS)>=3 ? parse(Int,ARGS[3]) : 0
    case=deserialize(case_file)
    if last_step>0
        case=case[1:last_step]
    end
    mkpath(output)
    rm=JutulDarcy.reservoir_model(case.model)
    domain=rm.data_domain
    grid=physical_representation(domain)
    initial=case.state0[:Reservoir]
    z=initial[:OverallMoleFractions]
    @assert minimum(z)>=0 && maximum(abs.(sum(z;dims=1).-1))<1e-12 "Invalid initial composition"
    @assert all(isfinite,initial[:Pressure]) && minimum(initial[:Pressure])>0
    println("Simulator: ",pathof(JutulDarcy))
    println("Active cells: ",length(grid.cell_map),", report steps: ",length(case.dt),", days: ",sum(case.dt)/86400)
    println("Initial composition range: ",extrema(z),", maximum composition sum deviation: ",maximum(abs.(sum(z;dims=1).-1)))
    flush(stdout)
    shapes=Dict{String,Any}()
    function save_array(name,value)
        array=Array(value)
        open(joinpath(output,name*".bin"),"w") do io
            write(io,array)
        end
        shapes[name]=Dict("dimensions"=>collect(size(array)),"element_type"=>string(eltype(array)),"order"=>"F")
    end
    save_array("cell_map",Int64.(grid.cell_map))
    save_array("centroids",domain[:cell_centroids])
    save_array("porosity",domain[:porosity])
    save_array("permeability",domain[:permeability])
    for key in keys(Jutul.get_primary_variables(rm))
        value=initial[key]
        if value isa AbstractArray{<:Real}
            save_array("initial_"*String(key),value)
        end
    end
    save_array("volumes",domain[:volumes])
    open(joinpath(output,"initial_arrays.toml"),"w") do io
        TOML.print(io,shapes)
    end
    open(joinpath(output,"well_connections.csv"),"w") do io
        println(io,"well,active_index,cartesian_index")
        for (key,submodel) in pairs(case.model.models)
            if JutulDarcy.model_or_domain_is_well(submodel)
                well=physical_representation(submodel.data_domain)
                for ix in well.perforations.reservoir
                    println(io,join((key,ix,grid.cell_map[ix]),','))
                end
            end
        end
    end
    report_index=Ref(0)
    maximum_composition_error=Ref(0.0)
    maximum_saturation_error=Ref(0.0)
    function report_progress(state,report)
        reservoir=state[:Reservoir]
        p=reservoir[:Pressure]
        @assert all(isfinite,p) && minimum(p)>0 "Invalid pressure at a report step"
        fractions=reservoir[:OverallMoleFractions]
        composition_error=maximum(abs.(sum(fractions;dims=1).-1))
        @assert all(isfinite,fractions) && minimum(fractions)>=-1e-8 && composition_error<1e-10 "Composition check failed at a report step"
        maximum_composition_error[]=max(maximum_composition_error[],composition_error)
        if haskey(reservoir,:Saturations)
            saturation=reservoir[:Saturations]
            saturation_error=maximum(abs.(sum(saturation;dims=1).-1))
            @assert all(isfinite,saturation) && minimum(saturation)>=-1e-8 && maximum(saturation)<=1+1e-8 && saturation_error<1e-10
            maximum_saturation_error[]=max(maximum_saturation_error[],saturation_error)
        end
        report_index[]+=1
        index=report_index[]
        nfail=count(ms->!get(ms,:success,false),report[:ministeps])
        println("Completed report steps: ",index,"/",length(case.dt),", history days: ",sum(case.dt[1:index])/86400,
            ", failed retries in this interval: ",nfail)
        flush(stdout)
        return state
    end
    elapsed=@elapsed result=simulate_reservoir(case; info_level=1,output_path=joinpath(output,"checkpoints"),output_function=report_progress)
    expected=sum(case.dt)
    complete=!isempty(result.time) && isapprox(last(result.time),expected;rtol=1e-9,atol=1e-6)
    open(joinpath(output,"well_results_si.csv"),"w") do io
        println(io,"time_days,well,variable,value_si")
        for (well,variables) in pairs(result.wells)
            for (variable,values) in pairs(variables)
                if values isa AbstractVector{<:Real} && length(values)==length(result.time)
                    for index in eachindex(result.time)
                        println(io,join((result.time[index]/86400,well,variable,values[index]),','))
                    end
                end
            end
        end
    end
    record=Dict("full_simulation_passed"=>complete,"expected_days"=>expected/86400,"simulated_days"=>isempty(result.time) ? 0.0 : last(result.time)/86400,
        "elapsed_seconds"=>elapsed,"active_grid"=>length(grid.cell_map),"report_state_count"=>length(result.states),
        "reports_with_composition_checks"=>report_index[],"all_reports_max_composition_sum_deviation"=>maximum_composition_error[],
        "all_reports_max_saturation_sum_deviation"=>maximum_saturation_error[],
        "simulator_source"=>pathof(JutulDarcy),"simulator_version"=>string(pkgversion(JutulDarcy)))
    if complete
        final=last(result.states)
        p=final[:Pressure]
        @assert all(isfinite,p) && minimum(p)>0 "Invalid final pressure"
        for (key, metric) in ((:Saturations, "saturations_max_sum_deviation"),
                              (:OverallMoleFractions, "overall_mole_fractions_max_sum_deviation"))
            if haskey(final,key)
                value=final[key]
                @assert all(isfinite,value) && minimum(value)>=-1e-8 && maximum(value)<=1+1e-8
                @assert maximum(abs.(sum(value;dims=1).-1))<1e-8
                record[metric]=maximum(abs.(sum(value;dims=1).-1))
            end
        end
        serialize(joinpath(output,"final_state.jls"),final)
    end
    serialize(joinpath(output,"well_results.jls"),Dict("time"=>result.time,"wells"=>result.wells.wells))
    open(joinpath(output,"run_validation.toml"),"w") do io
        TOML.print(io,record)
    end
    complete || error("The simulation did not complete the full history. Full-period scoring requires a complete run.")
    println("Full run passed. Days: ",expected/86400,", elapsed seconds: ",elapsed)
    flush(stdout)
    return nothing
end
main()
