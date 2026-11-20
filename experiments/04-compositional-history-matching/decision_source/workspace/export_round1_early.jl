# Analyze completed report steps independently without starting simulations or disturbing the three running simulations.
using JutulDarcy,Jutul
function main()
    root=abspath(ARGS[1])
    for name in ["round1_full","round1_k_only"]
        arguments=[joinpath(root,"import_"*name,"imported_case.jls"),
            joinpath(root,"runs",name,"checkpoints"),joinpath(root,"diagnostics_"*name*"_early")]
        empty!(ARGS);append!(ARGS,arguments)
        Base.include(Module(gensym(:ReadOnlyDiagnostics)),joinpath(root,"export_partial.jl"))
        GC.gc()
    end
end
main()
