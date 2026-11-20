# Read and check every saved report state from a complete simulation, including early baseline runs without per-report callbacks.
using JutulDarcy,Jutul,TOML
function main()
    root=ARGS[1];n=parse(Int,ARGS[2])
    verified=TOML.parsefile(joinpath(root,"run_validation.toml"))
    @assert verified["full_simulation_passed"] && verified["report_state_count"]==n
    maximum_z_error=0.;maximum_s_error=0.;minimum_z=Inf;minimum_s=Inf;minimum_p=Inf
    for step in 1:n
        state=Jutul.jldopen(joinpath(root,"checkpoints","jutul_$step.jld2"),"r") do file
            file["state"][:Reservoir]
        end
        p=state[:Pressure];z=state[:OverallMoleFractions];s=state[:Saturations]
        @assert all(isfinite,p) && minimum(p)>0
        z_error=maximum(abs.(sum(z;dims=1).-1));s_error=maximum(abs.(sum(s;dims=1).-1))
        @assert all(isfinite,z) && minimum(z)>=-1e-8 && maximum(z)<=1+1e-8 && z_error<1e-10
        @assert all(isfinite,s) && minimum(s)>=-1e-8 && maximum(s)<=1+1e-8 && s_error<1e-10
        maximum_z_error=max(maximum_z_error,z_error);maximum_s_error=max(maximum_s_error,s_error)
        minimum_z=min(minimum_z,minimum(z));minimum_s=min(minimum_s,minimum(s));minimum_p=min(minimum_p,minimum(p))
        if step%50==0
            println("Report state check: ",step,"/",n);flush(stdout)
        end
    end
    record=Dict("all_report_states_passed"=>true,"verified_report_steps"=>n,"max_composition_sum_deviation"=>maximum_z_error,
        "max_saturation_sum_deviation"=>maximum_s_error,"full_period_min_component_fraction"=>minimum_z,"full_period_min_saturation"=>minimum_s,
        "full_period_min_pressure_bar"=>minimum_p/1e5)
    open(joinpath(root,"report_state_checks.toml"),"w") do io
        TOML.print(io,record)
    end
    println(record)
end
main()
