# Recompute constitutive quantities and native well-to-cell fluxes for saved states without advancing time or changing the simulator.
using JutulDarcy, Jutul, Serialization, TOML
function main()
    case_file, checkpoint, output = ARGS[1:3]
    step = parse(Int, ARGS[4])
    mkpath(output)
    case = deserialize(case_file)
    states, _ = Jutul.read_results(checkpoint; range=step:step, read_reports=false, verbose=false)
    saved = only(states)
    model = case.model[:Reservoir]
    domain = model.data_domain
    grid = physical_representation(domain)
    reservoir_data = Jutul.evaluate_all_secondary_variables(model, saved[:Reservoir], case.parameters[:Reservoir])
    reservoir = Jutul.as_value(Jutul.JutulStorage(reservoir_data))
    @assert maximum(abs.(reservoir.Pressure.-saved[:Reservoir][:Pressure]))==0
    @assert maximum(abs.(reservoir.ImmiscibleSaturation.-saved[:Reservoir][:ImmiscibleSaturation]))<1e-12
    @assert maximum(abs.(reservoir.OverallMoleFractions.-saved[:Reservoir][:OverallMoleFractions]))<1e-12
    system = model.system
    rhoS = JutulDarcy.reference_densities(system)
    A, L, V = JutulDarcy.phase_indices(system)
    nc = size(reservoir.LiquidMassFractions, 1)
    native_wells = JutulDarcy.full_well_outputs(case.model, states, case.forces[step:step])
    comparison = Dict{String,Any}()
    open(joinpath(output,"perforation_flux.csv"),"w") do io
        println(io,"well,perforation,active_index,I,J,K,x_m,y_m,depth_m,Sw,Sg,pressure_bar,well_pressure_bar,WI_m3,water_drawdown_bar,water_mobility_per_Pa_s,water_mass_kg_s,water_std_m3_day,hydrocarbon_mass_kg_s")
        for well in [:P11,:P12,:P13,:P14,:P15,:P16]
            well_model = case.model[well]
            well_data = Jutul.evaluate_all_secondary_variables(well_model, saved[well], case.parameters[well])
            state_well = Jutul.as_value(Jutul.JutulStorage(well_data))
            force = case.forces[step]
            haskey(force,:outer) && (force=force.outer)
            group = haskey(force,:Facility) ? :Facility : Symbol("$(well)_ctrl")
            control = force[group].control[well]
            well_force = get(force,well,nothing)
            mask = isnothing(well_force) ? nothing : get(well_force,:mask,nothing)
            # Normal secondary-variable updates omit this quantity. Supply it with the original wellbore gravity integration function.
            JutulDarcy.update_before_step_well!(state_well,well_model,reservoir,model,control,mask;well_symbol=well)
            representation = physical_representation(well_model.data_domain)
            cells = vec(representation.perforations.reservoir)
            local_cells = vec(representation.perforations.self)
            term = JutulDarcy.ReservoirFromWellFlowCT(cells, local_cells)
            flux = zeros(nc+1)
            water_total = 0.
            positive_water = 0.; negative_water = 0.
            for i in eachindex(cells)
                Jutul.update_cross_term_in_entity!(flux,i,reservoir,reservoir,state_well,state_well,
                    model,well_model,term,model.equations[:mass_conservation],1.)
                !isnothing(mask) && (flux .*= mask.values[i])
                cell = cells[i]; wc = local_cells[i]
                connection = JutulDarcy.cross_term_perforation_get_conn(term,i,state_well,reservoir)
                potential = JutulDarcy.perforation_phase_potential_difference(connection,reservoir,state_well,A)
                cartesian = grid.cell_map[cell]-1
                I = cartesian%47+1; J = (cartesian÷47)%39+1; K = cartesian÷(47*39)+1
                water = flux[nc+1]/rhoS[A]*86400
                water_total += water
                positive_water += max(water,0.)
                negative_water += min(water,0.)
                xyz = domain[:cell_centroids][:,cell]
                mobility = reservoir.RelativePermeabilities[A,cell]/reservoir.PhaseViscosities[A,cell]
                values = (well,i,cell,I,J,K,xyz[1],xyz[2],xyz[3],reservoir.Saturations[A,cell],
                    reservoir.Saturations[V,cell],reservoir.Pressure[cell]/1e5,state_well.Pressure[wc]/1e5,
                    connection.WI,potential/connection.WI/1e5,mobility,flux[nc+1],water,sum(flux[1:nc]))
                println(io,join(values,','))
            end
            reference = -only(native_wells[well][:wrat])*86400
            comparison[String(well)] = Dict("native_wellhead_water_m3_day"=>reference,
                "water_from_completion_fluxes_m3_day"=>water_total,"absolute_difference_m3_day"=>abs(water_total-reference),
                "relative_difference"=>abs(water_total-reference)/max(abs(reference),1.),
                "sum_layer_water_inflow_m3_day"=>positive_water,"sum_layer_water_backflow_m3_day"=>negative_water)
        end
    end
    max_difference = maximum(c["relative_difference"] for c in values(comparison))
    record = Dict("report_steps"=>step,"simulated_days"=>sum(case.dt[1:step])/86400,
        "analysis_type"=>"Read-only constitutive calculations and native cross-term reevaluation on saved states. No additional forward simulation or parameter update was performed.",
        "wellbore_correction"=>"Recompute ConnectionPressureDrop on the saved state with the native update_before_step_well! wellbore correction. The original calculation used the state at the start of an internal step. Allow the resulting small discretization difference and cross-check against the wellhead rate.",
        "aggregate_verification"=>comparison,"max_relative_difference"=>max_difference,
        "instantaneous_wellhead_water_check_passed"=>max_difference<.01,
        "scope_of_use"=>"Use derived fluxes for fitting or water-source interpretation only if the comparison passes. Use the native wellhead output for scoring.",
        "source_location"=>pathof(JutulDarcy))
    open(joinpath(output,"flux_validation.toml"),"w") do io
        TOML.print(io,record)
    end
    println(record)
end
main()
