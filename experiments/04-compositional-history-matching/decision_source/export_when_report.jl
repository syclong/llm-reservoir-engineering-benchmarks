# Wait for the requested number of reports, then export read-only diagnostics without creating or updating simulation states.
using JutulDarcy, Jutul, TOML
function main()
    case_file, checkpoint, output, status_file = ARGS[1:4]
    minimum_report = parse(Int, ARGS[5])
    while true
        if isfile(status_file) && !TOML.parsefile(status_file)["success"]
            error("The simulation failed while waiting for partial diagnostics")
        end
        if isdir(checkpoint)
            indices = [parse(Int, match(r"jutul_(\d+)\.jld2", f)[1]) for f in readdir(checkpoint) if occursin(r"^jutul_\d+\.jld2$", f)]
            if !isempty(indices) && maximum(indices)-1 >= minimum_report
                break
            end
        end
        sleep(3)
    end
    script = joinpath(@__DIR__, "export_partial.jl")
    empty!(ARGS)
    append!(ARGS, [case_file, checkpoint, output, string(minimum_report)])
    Base.include(Module(gensym(:PartialReportExport)), script)
end
main()
