# Export the original model's grid connections and transmissibilities for spatial connectivity analysis.
using JutulDarcy,Jutul,Serialization,TOML
function main()
    case=deserialize(ARGS[1]);output=ARGS[2];mkpath(output)
    rm=JutulDarcy.reservoir_model(case.model)
    neighbors=Int64.(rm.domain.representation.neighborship)
    transmissibility=case.parameters[:Reservoir][:Transmissibilities]
    @assert size(neighbors,2)==length(transmissibility)
    open(joinpath(output,"neighbors.bin"),"w") do io
        write(io,neighbors)
    end
    open(joinpath(output,"transmissibility.bin"),"w") do io
        write(io,transmissibility)
    end
    open(joinpath(output,"topology.toml"),"w") do io
        TOML.print(io,Dict("cells"=>size(case.state0[:Reservoir][:OverallMoleFractions],2),
            "connections"=>length(transmissibility),"transmissibility_range"=>collect(extrema(transmissibility)),
            "source"=>pathof(JutulDarcy)))
    end
    println("Exported grid connections and transmissibilities to ",output)
end
main()
