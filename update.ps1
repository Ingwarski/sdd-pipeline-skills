[CmdletBinding()]
param(
    [ValidateSet('main', 'stable')][string]$Channel = 'stable',
    [switch]$All,
    [switch]$Codex,
    [switch]$Claude,
    [string]$CodexDir,
    [string]$ClaudeDir,
    [string[]]$RetiredSource = @(),
    [string[]]$CleanupDir = @(),
    [string]$EvidenceProject,
    [switch]$EvidenceReconfigure,
    [switch]$EvidenceNonInteractive,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$RepoRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
if ($Help) {
    Write-Host 'Update a clean SDD main checkout to the latest tested stable release, then repair/install and clean retired skills.'
    Write-Host 'Usage: .\update.ps1 [-Channel main|stable] [-All|-Codex|-Claude] [-CodexDir PATH] [-ClaudeDir PATH]'
    Write-Host 'Default: stable. Select main explicitly only for skillset maintenance or testing.'
    exit 0
}

# Use the same read-only location and resource preflight as installation, before
# Git fetch can write FETCH_HEAD or advance remote-tracking references.
$InstallArgs = @{}
foreach ($Key in $PSBoundParameters.Keys) {
    if ($Key -notin @('Help', 'Channel')) { $InstallArgs[$Key] = $PSBoundParameters[$Key] }
}
$Preflight = & (Join-Path $RepoRoot 'install.ps1') @InstallArgs -CheckLocationsOnly -Repair
$RepoRoot = $Preflight.Source
$Prefix = $Preflight.PythonPrefix
$AdvanceArgs = @('-B', (Join-Path $RepoRoot 'scripts/install_location.py'), 'advance', '--source', $RepoRoot, '--channel', $Channel)
if ($Preflight.Registrations.ContainsKey('CodexDir')) { $AdvanceArgs += @('--codex-dir', $Preflight.Registrations.CodexDir) }
if ($Preflight.Registrations.ContainsKey('ClaudeDir')) { $AdvanceArgs += @('--claude-dir', $Preflight.Registrations.ClaudeDir) }
foreach ($Key in $Preflight.Registrations.Keys) { $InstallArgs[$Key] = $Preflight.Registrations[$Key] }
& $Preflight.Python @Prefix @AdvanceArgs
if ($global:LASTEXITCODE -ne 0) { throw "Update refused for $RepoRoot on $Channel. See the path and revision details above." }

# Re-run the installer from the selected revision. Current links and receipts
# are left in place, and the report includes every actual installed target.
& (Join-Path $RepoRoot 'install.ps1') @InstallArgs -Repair
exit $LASTEXITCODE
