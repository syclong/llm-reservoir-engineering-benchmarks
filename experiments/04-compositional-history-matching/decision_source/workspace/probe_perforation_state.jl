# Inspect only the state and parameters needed for flux postprocessing, without running a simulation.
using JutulDarcy,Jutul,Serialization
case=deserialize(ARGS[1])
states,reports=Jutul.read_results(ARGS[2];range=516:516,read_reports=true,verbose=false)
saved=only(states)
for well in [:Reservoir,:P11,:P15,:P16]
    model=case.model[well];before=saved[well]
    after=Jutul.evaluate_all_secondary_variables(model,before,case.parameters[well])
    println("Model: ",well)
    println("Saved fields: ",collect(keys(before)))
    println("Primary variables: ",collect(keys(Jutul.get_primary_variables(model))))
    println("Parameters: ",collect(keys(case.parameters[well])))
    for key in [:Pressure,:ImmiscibleSaturation,:OverallMoleFractions,:TotalMasses,:Saturations,
                :PhaseMassDensities,:RelativePermeabilities,:WellIndices,:PerforationGravityDifference,
                :ConnectionPressureDrop,:Temperature,:FluidVolume]
        if haskey(after,key)
            value=after[key]
            if value isa AbstractArray{<:Real}
                print(key," recomputed range: ",extrema(value),", shape: ",size(value))
                if haskey(before,key) && before[key] isa AbstractArray{<:Real} && size(before[key])==size(value)
                    print(", maximum difference from saved value: ",maximum(abs.(before[key].-value)))
                end
                println()
            end
        end
    end
    println("Grid cell volume range: ",extrema(model.data_domain[:volumes]))
end
println("Final report keys: ",collect(keys(only(reports))))
mini=last(only(reports)[:ministeps]);println("Final internal step keys: ",collect(keys(mini)))
println("Final internal step duration: ",get(mini,:dt,"not recorded"))
