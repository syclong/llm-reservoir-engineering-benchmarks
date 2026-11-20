# Inspect saved round 1 states without running another simulation or changing parameters.
using JutulDarcy,Jutul,TOML
function main()
    root=abspath(ARGS[1]);label=length(ARGS)>=2 ? ARGS[2] : "mid"
    minimum_report=length(ARGS)>=3 ? parse(Int,ARGS[3]) : 0
    if minimum_report>0
        ready=false
        while !ready
            ready=true
            for (name,status_rel) in [("round1_full","control_ablation_k/05_full_round1.toml.status.toml"),
                                      ("round1_k_only","control_ablation_kphi/03_full_round1_k_only.toml.status.toml")]
                files=readdir(joinpath(root,"runs",name,"checkpoints"))
                indices=[parse(Int,match(r"jutul_(\d+)\.jld2",f)[1]) for f in files if occursin(r"^jutul_\d+\.jld2$",f)]
                ready &= !isempty(indices) && maximum(indices)-1>=minimum_report
                status=joinpath(root,status_rel)
                if isfile(status) && !TOML.parsefile(status)["success"]
                    error("Simulation failed while waiting for read-only diagnostics for $name")
                end
            end
            ready || sleep(3)
        end
    end
    for name in ["round1_full","round1_k_only"]
        arguments=[joinpath(root,"import_"*name,"imported_case.jls"),
            joinpath(root,"runs",name,"checkpoints"),joinpath(root,"diagnostics_"*name*"_"*label)]
        empty!(ARGS);append!(ARGS,arguments)
        Base.include(Module(gensym(:ReadOnlyDiagnostics)),joinpath(root,"export_partial.jl"))
        GC.gc()
    end
end
main()
