param([switch]$Force)
$ErrorActionPreference = 'Stop'
$previewScript = Join-Path $PSScriptRoot 'build_preview.py'
$previewArgs = @('-X', 'utf8', '-B', $previewScript)
if ($Force) { $previewArgs += '--force' }
$previewPython = Get-Command python -ErrorAction SilentlyContinue
$previewLauncher = Get-Command py -ErrorAction SilentlyContinue
$bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if ($previewPython) {
    & $previewPython.Source @previewArgs
} elseif ($previewLauncher) {
    & $previewLauncher.Source -3 @previewArgs
} elseif (Test-Path -LiteralPath $bundledPython) {
    & $bundledPython @previewArgs
} else {
    throw 'Python 3.10 or later is required. No files have been changed.'
}
exit $LASTEXITCODE
