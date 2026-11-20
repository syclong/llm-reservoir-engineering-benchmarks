param(
    [string]$SimulatorRoot = '\\<simulator-host>@SSL@1236\DavWWWRoot\XHZ\JutulDarcy',
    [string]$Model = (Join-Path $PSScriptRoot '..\model\UNISIM-IV-2026_E300.DATA'),
    [string]$OutputPath = (Join-Path $PSScriptRoot ('..\output_' + (Get-Date -Format 'yyyyMMdd_HHmmss')))
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$config = Get-Content -LiteralPath (Join-Path $SimulatorRoot 'Runtime-Config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$env:JULIA_DEPOT_PATH = $config.DepotPath + ';'
$env:JULIA_LOAD_PATH = '@;@stdlib'
$env:JULIA_PKG_PRECOMPILE_AUTO = '0'
$env:JULIA_NUM_THREADS = '8'
$env:OPENBLAS_NUM_THREADS = '4'
$inputModel = (Resolve-Path -LiteralPath $Model).Path
$outputDirectory = [IO.Path]::GetFullPath($OutputPath)
if ((Test-Path -LiteralPath $outputDirectory) -and (Get-ChildItem -LiteralPath $outputDirectory -Force | Select-Object -First 1)) {
    throw 'The output directory already contains files. Choose an empty directory.'
}
$project = '--project=' + (Join-Path $SimulatorRoot 'environment')
Write-Host ('Running the original simulator with model ' + $inputModel)
Write-Host ('Results directory: ' + $outputDirectory)
& $config.JuliaExecutable --startup-file=no $project (Join-Path $PSScriptRoot 'rerun_model.jl') $inputModel $outputDirectory
if ($LASTEXITCODE -ne 0) { throw ('Full simulation failed with exit code ' + $LASTEXITCODE) }
Write-Host 'Full simulation passed. The results directory contains the well responses and per-report physical checks.'
