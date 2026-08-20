$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$TestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("codex-sdd-installer-" + [guid]::NewGuid().ToString('N'))
$CodexDir = Join-Path $TestRoot 'codex'
$ClaudeDir = Join-Path $TestRoot 'claude'

try {
    New-Item -ItemType Directory -Path $CodexDir -Force | Out-Null
    $UnrelatedPrd = Join-Path $ClaudeDir 'to-prd'
    New-Item -ItemType Directory -Path $UnrelatedPrd -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $UnrelatedPrd 'marker.txt') -Value 'unrelated skill'

    $PriorClone = Join-Path $TestRoot 'prior-clone'
    $PriorLegacySource = Join-Path $PriorClone 'skills/to-prd'
    New-Item -ItemType Directory -Path $PriorLegacySource -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $CodexDir 'to-prd') -Target $PriorLegacySource | Out-Null
    Set-Content -LiteralPath (Join-Path $CodexDir '.codex-sdd-skills-source') -Value $PriorClone

    & (Join-Path $RepoRoot 'install.ps1') -All -CodexDir $CodexDir -ClaudeDir $ClaudeDir

    $Manifest = Get-Content -LiteralPath (Join-Path $RepoRoot 'skills-manifest.json') -Raw | ConvertFrom-Json
    foreach ($Skill in $Manifest.skills) {
        $SourceSkill = Join-Path (Join-Path $RepoRoot $Skill.path) 'SKILL.md'
        $SkillText = Get-Content -LiteralPath $SourceSkill -Raw
        if (-not $SkillText.Contains('working_language') -or -not $SkillText.Contains('For Ukrainian (`uk`)')) {
            throw "$SourceSkill is missing the working-language contract"
        }
        foreach ($InstallRoot in @($CodexDir, $ClaudeDir)) {
            $Destination = Join-Path $InstallRoot $Skill.name
            $Item = Get-Item -LiteralPath $Destination -Force
            if ([string]::IsNullOrWhiteSpace([string]$Item.LinkType)) {
                throw "$Destination is not a symbolic link or directory junction"
            }
            $InstalledSkill = Join-Path $Destination 'SKILL.md'
            if (-not (Test-Path -LiteralPath $InstalledSkill -PathType Leaf)) {
                throw "$InstalledSkill is missing"
            }
            if ((Get-FileHash $SourceSkill).Hash -ne (Get-FileHash $InstalledSkill).Hash) {
                throw "$InstalledSkill hash mismatch"
            }
        }
    }

    $ClaudeHandoff = Get-Content -LiteralPath (Join-Path $RepoRoot 'skills/to-sdd-pipeline/references/claude-design-handoff.md') -Raw
    if (-not $ClaudeHandoff.Contains('working_language') -or -not $ClaudeHandoff.Contains('preserved_english_terms')) {
        throw 'Claude Design handoff is missing the working-language contract.'
    }

    if (-not (Test-Path -LiteralPath (Join-Path $UnrelatedPrd 'marker.txt'))) {
        throw 'Unrelated to-prd skill was modified.'
    }
    if ($null -ne (Get-Item -LiteralPath (Join-Path $CodexDir 'to-prd') -Force -ErrorAction SilentlyContinue)) {
        throw 'Repository-owned legacy to-prd link was not migrated.'
    }

    & (Join-Path $RepoRoot 'install.ps1') -All -CodexDir $CodexDir -ClaudeDir $ClaudeDir

    $RepairSkill = $Manifest.skills | Where-Object { $_.name -eq 'to-screen-map' }
    $RepairDestination = Join-Path $CodexDir $RepairSkill.name
    $PriorRepairSource = Join-Path $PriorClone $RepairSkill.path
    New-Item -ItemType Directory -Path $PriorRepairSource -Force | Out-Null
    [System.IO.Directory]::Delete($RepairDestination)
    New-Item -ItemType Junction -Path $RepairDestination -Target $PriorRepairSource | Out-Null
    Set-Content -LiteralPath (Join-Path $CodexDir '.codex-sdd-skills-source') -Value $PriorClone
    & (Join-Path $RepoRoot 'install.ps1') -Codex -Repair -CodexDir $CodexDir
    if ((Get-FileHash (Join-Path (Join-Path $RepoRoot $RepairSkill.path) 'SKILL.md')).Hash -ne
        (Get-FileHash (Join-Path $RepairDestination 'SKILL.md')).Hash) {
        throw 'Repair did not reconnect the skill to the current clone.'
    }

    $ConflictPath = Join-Path $CodexDir 'to-sdd-pipeline'
    [System.IO.Directory]::Delete($ConflictPath)
    New-Item -ItemType Directory -Path $ConflictPath | Out-Null
    $AtomicityPath = Join-Path $CodexDir 'to-wireframes'
    [System.IO.Directory]::Delete($AtomicityPath)
    $ConflictDetected = $false
    try {
        & (Join-Path $RepoRoot 'install.ps1') -Codex -CodexDir $CodexDir
    } catch {
        $ConflictDetected = $true
    }
    if (-not $ConflictDetected) { throw 'Expected real-directory conflict was not detected.' }
    if ($null -ne (Get-Item -LiteralPath $AtomicityPath -Force -ErrorAction SilentlyContinue)) {
        throw 'Installer changed another destination after detecting a preflight conflict.'
    }
    Remove-Item -LiteralPath $ConflictPath -Force
    & (Join-Path $RepoRoot 'install.ps1') -Codex -CodexDir $CodexDir

    & (Join-Path $RepoRoot 'install.ps1') -All -Uninstall -CodexDir $CodexDir -ClaudeDir $ClaudeDir
    foreach ($Skill in $Manifest.skills) {
        foreach ($InstallRoot in @($CodexDir, $ClaudeDir)) {
            if ($null -ne (Get-Item -LiteralPath (Join-Path $InstallRoot $Skill.name) -Force -ErrorAction SilentlyContinue)) {
                throw "$($Skill.name) was not uninstalled from $InstallRoot"
            }
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $UnrelatedPrd 'marker.txt'))) {
        throw 'Unrelated to-prd skill was removed during uninstall.'
    }

    Write-Host 'Windows installer tests passed.'
} finally {
    if ($TestRoot.StartsWith([System.IO.Path]::GetTempPath(), [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
