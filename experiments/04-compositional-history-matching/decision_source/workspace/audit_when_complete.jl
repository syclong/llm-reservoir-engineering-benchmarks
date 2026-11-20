# Wait for the original simulation to finish, then check each saved report. Write a full audit only for complete results.
using JutulDarcy, Jutul, TOML
function main()
    root, status = ARGS[1:2]
    n = ARGS[3]
    verified = joinpath(root, "run_validation.toml")
    while !isfile(verified)
        if isfile(status) && !TOML.parsefile(status)["success"]
            error("Full-period verification requires a successful simulation")
        end
        sleep(3)
    end
    empty!(ARGS)
    append!(ARGS, [root, n])
    Base.include(Module(gensym(:FullStateAudit)), joinpath(@__DIR__, "audit_report_states.jl"))
end
main()
