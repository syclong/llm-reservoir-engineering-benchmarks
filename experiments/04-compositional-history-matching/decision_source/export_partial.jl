# Export the original simulator responses available so far as read-only, partial-history diagnostics.
using JutulDarcy,Jutul,Serialization,TOML
function main()
    case=deserialize(ARGS[1]);checkpoint=ARGS[2];output=ARGS[3];mkpath(output)
    indices=sort([parse(Int,match(r"jutul_(\d+)\.jld2",f)[1]) for f in readdir(checkpoint) if occursin(r"^jutul_\d+\.jld2$",f)])
    n=last(indices)-1 # Skip the newest file because its checkpoint may still be open for writing.
    if length(ARGS)>=4
        n=min(n,parse(Int,ARGS[4]))
    end
    states,_=Jutul.read_results(checkpoint;range=1:n,read_reports=false,verbose=false)
    wells=JutulDarcy.full_well_outputs(case.model,states,case.forces[1:n])
    times=cumsum(case.dt[1:n])/86400
    open(joinpath(output,"well_results_si.csv"),"w") do io
        println(io,"time_days,well,variable,value_si")
        for (well,variables) in wells, (key,values) in variables
            if values isa AbstractVector{<:Real} && length(values)==n
                for index in eachindex(times)
                    println(io,join((times[index],well,key,values[index]),','))
                end
            end
        end
    end
    open(joinpath(output,"well_reference.csv"),"w") do io
        println(io,"well,reference_depth,initial_pressure_pa")
        for well in [:P11,:P12,:P13,:P14,:P15,:P16]
            sm=case.model[well]
            println(io,join((well,sm.data_domain[:cell_centroids][3,1],only(case.state0[well][:Pressure])),','))
        end
    end
    shapes=Dict{String,Any}()
    state=last(states)[:Reservoir]
    for (key,value) in state
        if value isa AbstractArray{<:AbstractFloat}
            name=String(key)
            open(joinpath(output,name*".bin"),"w") do io
                write(io,value)
            end
            shapes[name]=collect(size(value))
        end
    end
    open(joinpath(output,"state_shapes.toml"),"w") do io
        TOML.print(io,shapes)
    end
    open(joinpath(output,"diagnostics.toml"),"w") do io
        TOML.print(io,Dict("partial_history_diagnostic"=>true,"report_steps"=>n,"simulated_days"=>last(times),"full_history_completed"=>false))
    end
    println("Read-only export complete: ",n," report steps, ",last(times)," days.")
end
main()
