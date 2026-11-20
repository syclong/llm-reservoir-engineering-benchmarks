# Execute workspace case scripts in a worker process that reuses the loaded official solver.
using JutulDarcy, Jutul
using TOML, Dates, LinearAlgebra
BLAS.set_num_threads(4)
control=abspath(ARGS[1])
mkpath(control)
println("Original simulator loaded: ",pathof(JutulDarcy))
flush(stdout)
while !isfile(joinpath(control,"stop"))
    for file in sort(readdir(control;join=true))
        endswith(file,".toml") || continue
        endswith(file,".status.toml") && continue
        status=file*".status.toml"
        isfile(status) && continue
        task=TOML.parsefile(file)
        if haskey(task,"ready_file") && !isfile(task["ready_file"])
            continue
        end
        if haskey(task,"ready_checkpoint_directory")
            directory=task["ready_checkpoint_directory"]
            isdir(directory) || continue
            indices=[parse(Int,match(r"jutul_(\d+)\.jld2",f)[1]) for f in readdir(directory) if occursin(r"^jutul_\d+\.jld2$",f)]
            isempty(indices) && continue
            maximum(indices)-1>=task["minimum_report"] || continue
        end
        empty!(ARGS);append!(ARGS,get(task,"arguments",String[]))
        logpath=task["log"]
        mkpath(dirname(logpath))
        started=now()
        success=false
        open(logpath,"w") do io
            redirect_stdout(io) do
                redirect_stderr(io) do
                    try
                        Base.include(Module(gensym(:CaseTask)),task["script"])
                        success=true
                    catch err
                        println(io,"Case task failed:")
                        showerror(io,err,catch_backtrace())
                        println(io)
                    end
                    flush(io)
                end
            end
        end
        open(status,"w") do io
            TOML.print(io,Dict("success"=>success,"started"=>string(started),"ended"=>string(now())))
        end
        println("Case task finished: ",basename(file),", success: ",success)
        flush(stdout)
        GC.gc()
    end
    sleep(1)
end
println("Experiment worker finished.")
