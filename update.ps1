[CmdletBinding()]
param(
    [switch]$All,
    [switch]$Codex,
    [switch]$Claude,
    [string]$CodexDir,
    [string]$ClaudeDir,
    [string[]]$RetiredSource = @(),
    [string[]]$CleanupDir = @(),
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$RepoRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
if ($Help) {
    Write-Host 'Update a clean SDD main checkout, then repair/install and clean retired skills.'
    Write-Host 'Usage: .\update.ps1 [-All|-Codex|-Claude] [-CodexDir PATH] [-ClaudeDir PATH] [-RetiredSource OLD_CLONE] [-CleanupDir SKILL_ROOT]'
    exit 0
}

# Reuse the origin allowlist; cleanup runs through the current installer below.
. (Join-Path $RepoRoot 'scripts/retired-skills.ps1')
function Invoke-UpdateGit([string[]]$Arguments) {
    $Output = & git -C $RepoRoot @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Git update check failed: $($Arguments[0])" }
    return $Output
}
$Top = Invoke-UpdateGit -Arguments @('rev-parse', '--show-toplevel')
if ([System.IO.Path]::GetFullPath($Top) -ne $RepoRoot) { throw 'Not the SDD clone root.' }
$Origin = Invoke-UpdateGit -Arguments @('remote', 'get-url', 'origin')
if (-not (Test-RetiredSddOrigin $Origin)) { throw 'Origin is not the expected SDD GitHub repository; stopped.' }
$Branch = Invoke-UpdateGit -Arguments @('symbolic-ref', '--quiet', '--short', 'HEAD')
if ($Branch -cne 'main') { throw 'Update requires main; your current checkout is unchanged.' }
$CleanupArgs = @{ RetireOnly=$true }
foreach ($Key in $PSBoundParameters.Keys) {
    if ($Key -ne 'Help') { $CleanupArgs[$Key] = $PSBoundParameters[$Key] }
}
& (Join-Path $RepoRoot 'install.ps1') @CleanupArgs
if ($LASTEXITCODE -ne 0) { throw 'Retirement cleanup failed; update stopped.' }
$Status = (Invoke-UpdateGit -Arguments @('status', '--porcelain', '--untracked-files=normal')) -join "`n"
if (-not [string]::IsNullOrWhiteSpace($Status)) { throw 'Local changes exist; commit or preserve them before updating.' }

Invoke-UpdateGit -Arguments @('fetch', '--quiet', 'origin', 'main')
& git -C $RepoRoot merge-base --is-ancestor HEAD FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw 'Local commits diverge from or are ahead of GitHub; stopped without replacing files.' }
Invoke-UpdateGit -Arguments @('merge', '--ff-only', 'FETCH_HEAD')

$InstallArgs = @{ Repair=$true }
foreach ($Key in $PSBoundParameters.Keys) {
    if ($Key -ne 'Help') { $InstallArgs[$Key] = $PSBoundParameters[$Key] }
}
& (Join-Path $RepoRoot 'install.ps1') @InstallArgs
exit $LASTEXITCODE
