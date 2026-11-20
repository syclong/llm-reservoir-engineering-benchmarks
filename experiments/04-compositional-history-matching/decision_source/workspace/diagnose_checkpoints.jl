# Inspect completed report steps without disturbing the running simulator.
using JutulDarcy,Jutul,Serialization,TOML
case=deserialize(ARGS[1])
checkpoint=ARGS[2]
output=ARGS[3]
mkpath(output)
indices=sort([parse(Int,match(r"jutul_(\d+)\.jld2",f)[1]) for f in readdir(checkpoint) if occursin(r"^jutul_\d+\.jld2$",f)])
println("Saved report step: ",last(indices),", days: ",sum(case.dt[1:last(indices)])/86400)
for n in indices[max(1,end-5):end]
    Jutul.jldopen(joinpath(checkpoint,"jutul_$n.jld2"),"r") do file
        report=file["report"]
        println("Report step: ",n,", report fields: ",keys(report))
        for ms in report[:ministeps]
            println(Dict(k=>v for (k,v) in ms if k in (:success,:dt,:stats,:prepare_time,:finalize_time)))
        end
    end
end
n=last(indices)
state=Jutul.jldopen(joinpath(checkpoint,"jutul_$n.jld2"),"r") do file
    file["state"]
end
wells=JutulDarcy.full_well_outputs(case.model,[state],[case.forces[n]])
open(joinpath(output,"latest_wells.csv"),"w") do io
    println(io,"time_days,well,variable,value_si")
    for (well,variables) in wells
        for (key,values) in variables
            if values isa AbstractVector{<:Real}
                println(io,join((sum(case.dt[1:n])/86400,well,key,only(values)),','))
            end
        end
    end
end
println("Read-only diagnostics complete.")
