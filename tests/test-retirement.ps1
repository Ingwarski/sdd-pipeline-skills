$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$TestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('sdd-retirement-' + [guid]::NewGuid().ToString('N'))
$CodexDir = Join-Path $TestRoot 'codex'
$ClaudeDir = Join-Path $TestRoot 'claude'
$History = Join-Path $TestRoot 'history'
$ExportDest = Join-Path $TestRoot 'export installs'
$OriginalBackup = $env:SDD_SKILL_BACKUP_DIR
$LockedFile = $null

function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Assert-Absent([string]$Path) {
    $Parent = Split-Path -Parent $Path
    $Name = Split-Path -Leaf $Path
    Assert-True (@(Get-ChildItem -LiteralPath $Parent -Force | Where-Object { $_.Name -eq $Name }).Count -eq 0) "Retired path still exists: $Path"
}
function Assert-RetiredAbsent {
    foreach ($Root in @($CodexDir, $ClaudeDir)) {
        foreach ($Name in @('communications-audit', 'issue-happypro-certificate')) { Assert-Absent (Join-Path $Root $Name) }
    }
}
function Run-Install([hashtable]$Extra = @{}) {
    & (Join-Path $RepoRoot 'install.ps1') -All -Repair -CodexDir $CodexDir -ClaudeDir $ClaudeDir @Extra
    Assert-True ($LASTEXITCODE -eq 0) 'Installer returned failure.'
}

try {
    foreach ($Directory in @($CodexDir, $ClaudeDir, $History, (Join-Path $TestRoot 'external'))) {
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    }
    $External = Join-Path $TestRoot 'external'
    Set-Content -LiteralPath (Join-Path $External 'marker.txt') -Value keep
    $env:SDD_SKILL_BACKUP_DIR = Join-Path $TestRoot 'former-backups'
    $Archive = Join-Path $TestRoot 'history.tar'
    & git -C $RepoRoot archive -o $Archive 31ae0fefe00e5b79c99a6a39d418125a291731fd skills/communications-audit skills/issue-happypro-certificate
    Assert-True ($LASTEXITCODE -eq 0) 'Historical fixtures require full Git history.'
    & tar -xf $Archive -C $History
    Assert-True ($LASTEXITCODE -eq 0) 'Could not extract historical fixtures.'

    # Delete originals, edited copies, additional files, and CRLF copies.
    Copy-Item -LiteralPath (Join-Path $History 'skills/communications-audit') -Destination (Join-Path $CodexDir 'communications-audit') -Recurse
    Add-Content -LiteralPath (Join-Path $CodexDir 'communications-audit/references/report-contract.md') -Value 'Edited local content'
    Set-Content -LiteralPath (Join-Path $CodexDir 'communications-audit/local-notes.txt') -Value extra
    New-Item -ItemType Junction -Path (Join-Path $CodexDir 'communications-audit/nested-link') -Target $External | Out-Null
    Copy-Item -LiteralPath (Join-Path $History 'skills/issue-happypro-certificate') -Destination (Join-Path $ClaudeDir 'issue-happypro-certificate') -Recurse
    $CertificateFile = Join-Path $ClaudeDir 'issue-happypro-certificate/SKILL.md'
    $CrlfText = [System.IO.File]::ReadAllText($CertificateFile) -replace '\r?\n', "`r`n"
    [System.IO.File]::WriteAllText($CertificateFile, $CrlfText, (New-Object System.Text.UTF8Encoding($false)))
    (Get-Item -LiteralPath $CertificateFile).IsReadOnly = $true
    Run-Install
    Assert-RetiredAbsent
    Assert-True (Test-Path -LiteralPath (Join-Path $External 'marker.txt')) 'Cleanup followed a nested junction.'
    Assert-True (-not (Test-Path -LiteralPath $env:SDD_SKILL_BACKUP_DIR)) 'Cleanup created a backup.'
    Run-Install

    # Broken links and custom-source receipts are not exceptions.
    $OldSource = Join-Path $TestRoot 'old source/skills/communications-audit'
    New-Item -ItemType Directory -Path $OldSource -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $CodexDir 'communications-audit') -Target $OldSource | Out-Null
    [System.IO.Directory]::Delete($OldSource)
    New-Item -ItemType Junction -Path (Join-Path $ClaudeDir 'issue-happypro-certificate') -Target (Join-Path $History 'skills/issue-happypro-certificate') | Out-Null
    Set-Content -LiteralPath (Join-Path $ClaudeDir '.custom-agent-skills-source') -Value $History
    Run-Install
    Assert-RetiredAbsent
    Assert-True (Test-Path -LiteralPath (Join-Path $History 'skills/issue-happypro-certificate/SKILL.md')) 'Cleanup traversed an external source.'

    $ProjectSkills = Join-Path $TestRoot 'project/.agents/skills'
    New-Item -ItemType Directory -Path (Join-Path $ProjectSkills 'communications-audit') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $ProjectSkills 'unrelated.txt') -Value keep
    Run-Install @{ CleanupDir=@($ProjectSkills) }
    Assert-Absent (Join-Path $ProjectSkills 'communications-audit')
    Assert-True (Test-Path -LiteralPath (Join-Path $ProjectSkills 'unrelated.txt')) 'Unrelated file was deleted.'

    # Remove backup copies produced by the former updater, without replacements.
    foreach ($Name in @('communications-audit', 'issue-happypro-certificate')) {
        $Former = Join-Path $env:SDD_SKILL_BACKUP_DIR "$Name.ABC123"
        New-Item -ItemType Directory -Path $Former -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $History "skills/$Name") -Destination (Join-Path $Former $Name) -Recurse
        Set-Content -LiteralPath (Join-Path $Former 'original-path.txt') -Value (Join-Path $CodexDir $Name) -Encoding UTF8
    }
    Run-Install
    Assert-Absent (Join-Path $env:SDD_SKILL_BACKUP_DIR 'communications-audit.ABC123')
    Assert-Absent (Join-Path $env:SDD_SKILL_BACKUP_DIR 'issue-happypro-certificate.ABC123')

    # A locked file makes the update fail until deletion can actually finish.
    $LockedPath = Join-Path $CodexDir 'communications-audit/SKILL.md'
    New-Item -ItemType Directory -Path (Split-Path -Parent $LockedPath) | Out-Null
    Set-Content -LiteralPath $LockedPath -Value undeleted
    $LockedFile = [System.IO.File]::Open($LockedPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::None)
    $DeletionFailed = $false
    try { Run-Install } catch { $DeletionFailed = $true } finally { $LockedFile.Dispose(); $LockedFile = $null }
    Assert-True $DeletionFailed 'Expected deletion failure.'
    Assert-True (Test-Path -LiteralPath $LockedPath) 'Locked fixture was not present.'
    Run-Install
    Assert-RetiredAbsent

    # Retire the business skills even when unrelated SDD links need attention.
    [System.IO.Directory]::Delete((Join-Path $CodexDir 'to-wireframes'))
    [System.IO.Directory]::Delete((Join-Path $CodexDir 'to-sdd-pipeline'))
    New-Item -ItemType Directory -Path (Join-Path $CodexDir 'to-sdd-pipeline') | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $CodexDir 'issue-happypro-certificate') | Out-Null
    $Conflict = $false
    try { Run-Install } catch { $Conflict = $true }
    Assert-True $Conflict 'Expected active-skill conflict.'
    Assert-Absent (Join-Path $CodexDir 'issue-happypro-certificate')
    Assert-Absent (Join-Path $CodexDir 'to-wireframes')
    [System.IO.Directory]::Delete((Join-Path $CodexDir 'to-sdd-pipeline'))
    Run-Install

    $ExportRoot = Join-Path $TestRoot 'source export'
    New-Item -ItemType Directory -Path (Join-Path $ExportRoot '.agents/skills/issue-happypro-certificate') -Force | Out-Null
    foreach ($File in @('install.ps1', 'skills-manifest.json', 'retired-skills.txt')) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot $File) -Destination (Join-Path $ExportRoot $File)
    }
    foreach ($Directory in @('scripts', 'skills')) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot $Directory) -Destination (Join-Path $ExportRoot $Directory) -Recurse
    }
    Copy-Item -LiteralPath (Join-Path $History 'skills/communications-audit') -Destination (Join-Path $ExportRoot 'skills/communications-audit') -Recurse
    & (Join-Path $ExportRoot 'install.ps1') -Codex -CodexDir $ExportDest
    Assert-Absent (Join-Path $ExportRoot 'skills/communications-audit')
    Assert-Absent (Join-Path $ExportRoot '.agents/skills/issue-happypro-certificate')

    New-Item -ItemType Directory -Path (Join-Path $ExportDest 'communications-audit') | Out-Null
    Set-Content -LiteralPath (Join-Path $ExportRoot 'retired-skills.txt') -Value @('communications-audit', 'issue-happypro-certificate', 'to-wireframes')
    $PolicyFailed = $false
    try { & (Join-Path $ExportRoot 'install.ps1') -Codex -CodexDir $ExportDest } catch { $PolicyFailed = $true }
    Assert-True $PolicyFailed 'Invalid retirement policy was accepted.'
    Assert-True (Test-Path -LiteralPath (Join-Path $ExportDest 'communications-audit')) 'Invalid policy changed files.'
    Assert-True (Test-Path -LiteralPath (Join-Path $ExportDest 'to-wireframes/SKILL.md')) 'Policy retired an unrelated skill.'
    Write-Host 'Windows permanent retirement tests passed.'
} finally {
    if ($null -ne $LockedFile) { $LockedFile.Dispose() }
    $env:SDD_SKILL_BACKUP_DIR = $OriginalBackup
    foreach ($Root in @($CodexDir, $ClaudeDir, $ExportDest)) {
        if (Test-Path -LiteralPath $Root) {
            foreach ($Item in Get-ChildItem -LiteralPath $Root -Force) {
                if ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { [System.IO.Directory]::Delete($Item.FullName) }
            }
        }
    }
    if ($TestRoot.StartsWith([System.IO.Path]::GetTempPath(), [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $TestRoot) -like 'sdd-retirement-*') {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
