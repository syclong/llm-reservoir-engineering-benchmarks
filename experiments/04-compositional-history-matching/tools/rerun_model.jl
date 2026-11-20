# Build the original DATA case and invoke the same simulation tool using the original simulator methods.
using JutulDarcy, Jutul, Serialization, LinearAlgebra
function main()
    pkgversion(JutulDarcy)==v"0.4.1" || error("This reproduction requires unmodified JutulDarcy 0.4.1. Check the runtime environment.")
    input, output = abspath.(ARGS[1:2])
    isfile(input) || error("Model file does not exist: $input")
    isdir(output) && !isempty(readdir(output)) && error("The output directory already contains files. Choose an empty directory: $output")
    mkpath(output)
    BLAS.set_num_threads(4)
    case = setup_case_from_data_file(input; repair_zcorn=false, verbose=true)
    case_file = joinpath(output, "native_input.jls")
    serialize(case_file, case)
    empty!(ARGS)
    append!(ARGS, [case_file, output])
    Base.include(Module(gensym(:OriginalFullPeriodRerun)), joinpath(@__DIR__, "run_case.jl"))
end
main()
