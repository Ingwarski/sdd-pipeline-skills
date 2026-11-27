$ErrorActionPreference = 'Stop'
& python -B (Join-Path $PSScriptRoot 'installer_update_suite.py')
if ($LASTEXITCODE -ne 0) { throw 'Windows updater tests failed.' }
