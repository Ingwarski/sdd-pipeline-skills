[CmdletBinding()]
param(
    [ValidateSet('main', 'stable')][string]$Channel = 'main',
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
    Write-Host 'Update a clean SDD main checkout, then repair/install and clean retired skills.'
    Write-Host 'Usage: .\update.ps1 [-Channel main|stable] [-All|-Codex|-Claude] [-CodexDir PATH] [-ClaudeDir PATH] [-CleanupDir SKILL_ROOT]'
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
    if ($Key -notin @('Help', 'Channel')) { $CleanupArgs[$Key] = $PSBoundParameters[$Key] }
}
& (Join-Path $RepoRoot 'install.ps1') @CleanupArgs
if ($LASTEXITCODE -ne 0) { throw 'Retirement cleanup failed; update stopped.' }
$Status = (Invoke-UpdateGit -Arguments @('status', '--porcelain', '--untracked-files=normal')) -join "`n"
if (-not [string]::IsNullOrWhiteSpace($Status)) { throw 'Local changes exist; commit or preserve them before updating.' }

Invoke-UpdateGit -Arguments @('fetch', '--quiet', 'origin', $Channel)
& git -C $RepoRoot merge-base --is-ancestor HEAD FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw 'Local commits diverge from or are ahead of GitHub; stopped without replacing files.' }
Invoke-UpdateGit -Arguments @('merge', '--ff-only', 'FETCH_HEAD')

$StatusScript = Join-Path $RepoRoot 'scripts/installation_status.py'
$SetupScript = Join-Path $RepoRoot 'scripts/evidence_setup.py'
if ((Test-Path -LiteralPath $StatusScript) -and (Test-Path -LiteralPath $SetupScript)) {
    $StatusPython = $null
    $StatusPrefix = @()
    foreach ($Candidate in @('python3', 'python', 'py')) {
        $Executable = Get-Command $Candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $Executable) { continue }
        $Prefix = if ($Candidate -eq 'py') { @('-3') } else { @() }
        & $Executable.Source @Prefix -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>$null
        if ($LASTEXITCODE -eq 0) { $StatusPython = $Executable.Source; $StatusPrefix = $Prefix; break }
    }
    $StatusArgs = @($StatusScript, '--root', $RepoRoot, '--exit-on-links', '--installer-args')
    if ($All) { $StatusArgs += '--all' }
    if ($Codex) { $StatusArgs += '--codex' }
    if ($Claude) { $StatusArgs += '--claude' }
    if (-not [string]::IsNullOrWhiteSpace($CodexDir)) { $StatusArgs += @('--codex-dir', $CodexDir) }
    if (-not [string]::IsNullOrWhiteSpace($ClaudeDir)) { $StatusArgs += @('--claude-dir', $ClaudeDir) }
    foreach ($Root in $CleanupDir) { $StatusArgs += @('--cleanup-dir', $Root) }
    foreach ($Root in $RetiredSource) { $StatusArgs += @('--retired-source', $Root) }
    if (-not [string]::IsNullOrWhiteSpace($EvidenceProject)) { $StatusArgs += @('--evidence-project', $EvidenceProject) }
    if ($null -ne $StatusPython) {
        & $StatusPython @StatusPrefix @StatusArgs | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $EvidenceArgs = @($SetupScript, 'ensure')
            if (-not [string]::IsNullOrWhiteSpace($EvidenceProject)) { $EvidenceArgs += @('--project', $EvidenceProject) }
            if ($EvidenceReconfigure) { $EvidenceArgs += '--reconfigure' }
            if ($EvidenceNonInteractive) { $EvidenceArgs += '--non-interactive' }
            & $StatusPython @StatusPrefix @EvidenceArgs
            if ($LASTEXITCODE -eq 2) {
                Write-Host 'Skills are current; evidence storage setup is required. Run scripts/evidence_setup.py wizard.'
            } elseif ($LASTEXITCODE -ne 0) {
                throw 'Evidence setup failed; current skill links do not need repair.'
            } else {
                Write-Host 'Skills and evidence storage setup are current; no link repair needed.'
            }
            exit 0
        }
    }
}

$InstallArgs = @{ Repair=$true }
foreach ($Key in $PSBoundParameters.Keys) {
    if ($Key -notin @('Help', 'Channel')) { $InstallArgs[$Key] = $PSBoundParameters[$Key] }
}
& (Join-Path $RepoRoot 'install.ps1') @InstallArgs
exit $LASTEXITCODE
