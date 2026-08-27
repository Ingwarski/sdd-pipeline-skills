$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$TestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('sdd-retirement-' + [guid]::NewGuid().ToString('N'))
$CodexDir = Join-Path $TestRoot 'codex'
$ClaudeDir = Join-Path $TestRoot 'claude'
$History = Join-Path $TestRoot 'history'
$ExportDest = Join-Path $TestRoot 'export installs'
$OriginalBackup = $env:SDD_SKILL_BACKUP_DIR

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Assert-Absent([string]$Path) {
    $Parent = Split-Path -Parent $Path
    $Name = Split-Path -Leaf $Path
    Assert-True (@(Get-ChildItem -LiteralPath $Parent -Force | Where-Object { $_.Name -eq $Name }).Count -eq 0) "Retired path still exists: $Path"
}
function Run-Install([hashtable]$Extra = @{}) {
    & (Join-Path $RepoRoot 'install.ps1') -All -Repair -CodexDir $CodexDir -ClaudeDir $ClaudeDir @Extra
}
function Expect-Review([hashtable]$Extra = @{}) {
    $Detected = $false
    try { Run-Install $Extra } catch {
        if ($_.Exception.Message -notlike '*Cleanup needs review*') { throw }
        $Detected = $true
    }
    Assert-True $Detected 'Expected a review-required failure.'
}
function Assert-SameTree([string]$Source, [string]$Destination) {
    $SourceFiles = @(Get-ChildItem -LiteralPath $Source -Recurse -File)
    $DestinationFiles = @(Get-ChildItem -LiteralPath $Destination -Recurse -File)
    Assert-True ($SourceFiles.Count -eq $DestinationFiles.Count) 'Backup inventory changed.'
    foreach ($File in $SourceFiles) {
        $Relative = $File.FullName.Substring($Source.Length + 1)
        Assert-True ((Get-FileHash -LiteralPath $File.FullName).Hash -eq (Get-FileHash -LiteralPath (Join-Path $Destination $Relative)).Hash) "Backup changed: $Relative"
    }
}

try {
    foreach ($Directory in @($CodexDir, $ClaudeDir, $History)) { New-Item -ItemType Directory -Path $Directory -Force | Out-Null }
    $env:SDD_SKILL_BACKUP_DIR = Join-Path $TestRoot 'backups'
    $Archive = Join-Path $TestRoot 'history.tar'
    & git -C $RepoRoot archive -o $Archive 31ae0fefe00e5b79c99a6a39d418125a291731fd skills/communications-audit skills/issue-happypro-certificate
    Assert-True ($LASTEXITCODE -eq 0) 'Historical fixtures require Git history (fetch-depth: 0 in CI).'
    & tar -xf $Archive -C $History
    Assert-True ($LASTEXITCODE -eq 0) 'Could not extract historical fixtures.'
    Run-Install

    # Both live and broken junctions to a recorded old clone must be removed.
    $OldRoot = Join-Path $TestRoot 'old combined clone'
    foreach ($Name in @('communications-audit', 'issue-happypro-certificate')) {
        New-Item -ItemType Directory -Path (Join-Path $OldRoot "skills/$Name") -Force | Out-Null
    }
    New-Item -ItemType Junction -Path (Join-Path $CodexDir 'communications-audit') -Target (Join-Path $OldRoot 'skills/communications-audit') | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $ClaudeDir 'issue-happypro-certificate') -Target (Join-Path $OldRoot 'skills/issue-happypro-certificate') | Out-Null
    [System.IO.Directory]::Delete((Join-Path $OldRoot 'skills/issue-happypro-certificate'))
    foreach ($Root in @($CodexDir, $ClaudeDir)) { Set-Content -LiteralPath (Join-Path $Root '.codex-sdd-skills-source') -Value $OldRoot }
    Run-Install
    Assert-Absent (Join-Path $CodexDir 'communications-audit')
    Assert-Absent (Join-Path $ClaudeDir 'issue-happypro-certificate')
    Assert-True (Test-Path -LiteralPath (Join-Path $OldRoot 'skills/communications-audit')) 'Cleanup deleted a link target.'
    Assert-True (-not (Test-Path -LiteralPath $env:SDD_SKILL_BACKUP_DIR)) 'Link-only cleanup created an unnecessary backup.'
    Run-Install

    Copy-Item -LiteralPath (Join-Path $History 'skills/communications-audit') -Destination (Join-Path $CodexDir 'communications-audit') -Recurse
    Copy-Item -LiteralPath (Join-Path $History 'skills/issue-happypro-certificate') -Destination (Join-Path $ClaudeDir 'issue-happypro-certificate') -Recurse
    $CertificateFile = Join-Path $ClaudeDir 'issue-happypro-certificate/SKILL.md'
    $CrlfText = [System.IO.File]::ReadAllText($CertificateFile) -replace '\r?\n', "`r`n"
    [System.IO.File]::WriteAllText($CertificateFile, $CrlfText, (New-Object System.Text.UTF8Encoding($false)))
    $CrlfHash = (Get-FileHash -LiteralPath $CertificateFile).Hash
    Run-Install
    Assert-Absent (Join-Path $CodexDir 'communications-audit')
    Assert-Absent (Join-Path $ClaudeDir 'issue-happypro-certificate')
    $AuditBackup = @(Get-ChildItem -LiteralPath $env:SDD_SKILL_BACKUP_DIR -Directory -Recurse | Where-Object { $_.Name -eq 'communications-audit' })[0].FullName
    $CertificateBackup = @(Get-ChildItem -LiteralPath $env:SDD_SKILL_BACKUP_DIR -Directory -Recurse | Where-Object { $_.Name -eq 'issue-happypro-certificate' })[0].FullName
    Assert-SameTree (Join-Path $History 'skills/communications-audit') $AuditBackup
    Assert-True ((Get-FileHash -LiteralPath (Join-Path $CertificateBackup 'SKILL.md')).Hash -eq $CrlfHash) 'CRLF backup changed.'
    $BackupCount = @(Get-ChildItem -LiteralPath $env:SDD_SKILL_BACKUP_DIR -Directory).Count
    Run-Install
    Assert-True (@(Get-ChildItem -LiteralPath $env:SDD_SKILL_BACKUP_DIR -Directory).Count -eq $BackupCount) 'Repeat created new backups.'

    Copy-Item -LiteralPath (Join-Path $History 'skills/issue-happypro-certificate') -Destination (Join-Path $CodexDir 'issue-happypro-certificate') -Recurse
    $SafeBackup = $env:SDD_SKILL_BACKUP_DIR
    $UnsafeBackup = Join-Path $CodexDir 'recovery'
    $env:SDD_SKILL_BACKUP_DIR = $UnsafeBackup
    $BackupRefused = $false
    try { Run-Install } catch {
        if ($_.Exception.Message -notlike '*outside every skill directory*') { throw }
        $BackupRefused = $true
    } finally { $env:SDD_SKILL_BACKUP_DIR = $SafeBackup }
    Assert-True $BackupRefused 'Unsafe recovery location was accepted.'
    Assert-True (Test-Path -LiteralPath (Join-Path $CodexDir 'issue-happypro-certificate/SKILL.md')) 'Copy changed before recovery check.'
    Assert-True (-not (Test-Path -LiteralPath $UnsafeBackup)) 'Unsafe recovery folder was created.'
    Run-Install

    Copy-Item -LiteralPath (Join-Path $History 'skills/communications-audit') -Destination (Join-Path $CodexDir 'communications-audit') -Recurse
    $Edited = Join-Path $CodexDir 'communications-audit/references/report-contract.md'
    Add-Content -LiteralPath $Edited -Value 'User changes must survive.'
    $EditedHash = (Get-FileHash -LiteralPath $Edited).Hash
    New-Item -ItemType Junction -Path (Join-Path $CodexDir 'issue-happypro-certificate') -Target (Join-Path $History 'skills/issue-happypro-certificate') | Out-Null
    Set-Content -LiteralPath (Join-Path $CodexDir '.codex-sdd-skills-source') -Value $History
    [System.IO.Directory]::Delete((Join-Path $CodexDir 'to-wireframes'))
    Expect-Review
    Assert-True ((Get-FileHash -LiteralPath $Edited).Hash -eq $EditedHash) 'Modified copy was changed.'
    Assert-True (-not [string]::IsNullOrWhiteSpace([string](Get-Item -LiteralPath (Join-Path $CodexDir 'issue-happypro-certificate') -Force).LinkType)) 'Preflight removed another link.'
    Assert-Absent (Join-Path $CodexDir 'to-wireframes')
    Move-Item -LiteralPath (Join-Path $CodexDir 'communications-audit') -Destination (Join-Path $TestRoot 'preserved-user-copy')
    Run-Install

    New-Item -ItemType Junction -Path (Join-Path $CodexDir 'communications-audit') -Target (Join-Path $OldRoot 'skills/communications-audit') | Out-Null
    Expect-Review
    Run-Install @{ RetiredSource=@($OldRoot) }
    Assert-Absent (Join-Path $CodexDir 'communications-audit')

    $ProjectSkills = Join-Path $TestRoot 'project/.agents/skills'
    New-Item -ItemType Directory -Path $ProjectSkills -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $History 'skills/issue-happypro-certificate') -Destination (Join-Path $ProjectSkills 'issue-happypro-certificate') -Recurse
    Set-Content -LiteralPath (Join-Path $ProjectSkills 'unrelated.txt') -Value 'keep'
    Run-Install
    Assert-True (Test-Path -LiteralPath (Join-Path $ProjectSkills 'issue-happypro-certificate/SKILL.md')) 'Unrequested root was changed.'
    Run-Install @{ CleanupDir=@($ProjectSkills) }
    Assert-Absent (Join-Path $ProjectSkills 'issue-happypro-certificate')
    Assert-True (Test-Path -LiteralPath (Join-Path $ProjectSkills 'unrelated.txt')) 'Unrelated file was deleted.'

    $ExportRoot = Join-Path $TestRoot 'source export'
    New-Item -ItemType Directory -Path $ExportRoot | Out-Null
    foreach ($File in @('install.ps1', 'skills-manifest.json', 'retired-skills.tsv')) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot $File) -Destination (Join-Path $ExportRoot $File)
    }
    foreach ($Directory in @('scripts', 'skills')) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot $Directory) -Destination (Join-Path $ExportRoot $Directory) -Recurse
    }
    Copy-Item -LiteralPath (Join-Path $History 'skills/communications-audit') -Destination (Join-Path $ExportRoot 'skills/communications-audit') -Recurse
    & (Join-Path $ExportRoot 'install.ps1') -Codex -CodexDir $ExportDest
    Assert-Absent (Join-Path $ExportRoot 'skills/communications-audit')
    Assert-True (Test-Path -LiteralPath (Join-Path $ExportDest 'to-sdd-pipeline/SKILL.md')) 'Source export did not install.'
    $CustomRoot = Join-Path $TestRoot 'custom clone'
    New-Item -ItemType Directory -Path (Join-Path $CustomRoot 'skills') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $CustomRoot 'skills-manifest.json') -Value '{"skill_set":"custom-agent-skills"}'
    foreach ($Name in @('communications-audit', 'issue-happypro-certificate')) {
        Copy-Item -LiteralPath (Join-Path $History "skills/$Name") -Destination (Join-Path $CustomRoot "skills/$Name") -Recurse
    }
    New-Item -ItemType Junction -Path (Join-Path $CodexDir 'communications-audit') -Target (Join-Path $CustomRoot 'skills/communications-audit') | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $ClaudeDir 'issue-happypro-certificate') -Target (Join-Path $CustomRoot 'skills/issue-happypro-certificate') | Out-Null
    Set-Content -LiteralPath (Join-Path $CodexDir '.custom-agent-skills-source') -Value $CustomRoot
    Set-Content -LiteralPath (Join-Path $ClaudeDir '.codex-sdd-skills-source') -Value $CustomRoot
    Run-Install @{ RetiredSource=@($CustomRoot) }
    Assert-True (Test-Path -LiteralPath (Join-Path $CodexDir 'communications-audit/SKILL.md')) 'Independent audit install was removed.'
    Assert-True (Test-Path -LiteralPath (Join-Path $ClaudeDir 'issue-happypro-certificate/SKILL.md')) 'Independent certificate install was removed.'
    Assert-SameTree (Join-Path $History 'skills/communications-audit') (Join-Path $CustomRoot 'skills/communications-audit')
    Assert-True ((Get-Content -LiteralPath (Join-Path $CodexDir '.custom-agent-skills-source') -Raw).Trim() -eq $CustomRoot) 'Independent receipt changed.'
    Write-Host 'Windows retirement tests passed.'
} finally {
    $env:SDD_SKILL_BACKUP_DIR = $OriginalBackup
    foreach ($Root in @($CodexDir, $ClaudeDir, $ExportDest)) {
        if (Test-Path -LiteralPath $Root) {
            foreach ($Item in Get-ChildItem -LiteralPath $Root -Force) {
                if (-not [string]::IsNullOrWhiteSpace([string]$Item.LinkType)) { [System.IO.Directory]::Delete($Item.FullName) }
            }
        }
    }
    if ($TestRoot.StartsWith([System.IO.Path]::GetTempPath(), [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $TestRoot) -like 'sdd-retirement-*') {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
