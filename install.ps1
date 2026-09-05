[CmdletBinding()]
param(
    [switch]$All,
    [switch]$Codex,
    [switch]$Claude,
    [switch]$Repair,
    [switch]$Uninstall,
    [switch]$RetireOnly,
    [string]$CodexDir,
    [string]$ClaudeDir,
    [string[]]$RetiredSource = @(),
    [string[]]$CleanupDir = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$CodexDirExplicit = -not [string]::IsNullOrWhiteSpace($CodexDir) -or -not [string]::IsNullOrWhiteSpace($env:CODEX_SKILLS_DIR)

if ($Repair -and $Uninstall) {
    throw '--Repair and --Uninstall cannot be used together.'
}
if ($Uninstall -and ($RetireOnly -or $RetiredSource.Count -gt 0 -or $CleanupDir.Count -gt 0)) {
    throw 'Retirement options apply to install/update, not -Uninstall.'
}

if ($All -or (-not $Codex -and -not $Claude)) {
    $Codex = $true
    $Claude = $true
}

$RepoRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$ManifestPath = Join-Path $RepoRoot 'skills-manifest.json'
$ReceiptName = '.codex-sdd-skills-source'

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Missing manifest: $ManifestPath"
}

# Use the same strict parser and source/reference preflight as the Unix installer.
# Detect Python before cleanup or any link/receipt write; never install it silently.
$PythonCommand = $null
$PythonPrefix = @()
foreach ($Candidate in @('python3', 'python', 'py')) {
    $Executable = Get-Command $Candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $Executable) { continue }
    $Prefix = if ($Candidate -eq 'py') { @('-3') } else { @() }
    try {
        & $Executable.Source @Prefix -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>$null
        if ($LASTEXITCODE -eq 0) { $PythonCommand = $Executable.Source; $PythonPrefix = $Prefix; break }
    } catch { }
}
if ($null -eq $PythonCommand) { throw 'Python 3.12+ is required. Install Python 3, then rerun; no installation changes made.' }
$ParserArgs = @((Join-Path $RepoRoot 'scripts/install_manifest.py'), '--root', $RepoRoot)
if ($RetireOnly) { $ParserArgs += '--metadata-only' }
$Rows = @(& $PythonCommand @PythonPrefix @ParserArgs)
if ($LASTEXITCODE -ne 0) { throw 'Installation preflight failed; no installation changes made.' }
$Skills = @($Rows | ForEach-Object {
    $Fields = $_ -split '\|', 3
    [pscustomobject]@{ name=$Fields[0]; path=$Fields[1]; legacy_name=if ($Fields[2]) { $Fields[2] } else { $null } }
})
$Manifest = [pscustomobject]@{ schema_version=1; skill_set='sdd-pipeline'; skill_count=13; skills=$Skills }

if ([string]::IsNullOrWhiteSpace($CodexDir)) {
    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_SKILLS_DIR)) {
        $CodexDir = $env:CODEX_SKILLS_DIR
    } elseif (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        $CodexDir = Join-Path $env:CODEX_HOME 'skills'
    } else {
        $LegacyCodexDir = Join-Path $HOME '.codex\skills'
        $OfficialCodexDir = Join-Path $HOME '.agents\skills'
        if ((Test-Path -LiteralPath $LegacyCodexDir) -and -not (Test-Path -LiteralPath $OfficialCodexDir)) {
            $CodexDir = $LegacyCodexDir
        } else {
            $CodexDir = $OfficialCodexDir
        }
    }
}

if ([string]::IsNullOrWhiteSpace($ClaudeDir)) {
    if (-not [string]::IsNullOrWhiteSpace($env:CLAUDE_SKILLS_DIR)) {
        $ClaudeDir = $env:CLAUDE_SKILLS_DIR
    } else {
        $ClaudeDir = Join-Path $HOME '.claude\skills'
    }
}

function Normalize-Path([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path).TrimEnd(
        [char[]]@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    )
}

function Get-InstallItem([string]$Path) {
    return (Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue)
}

function Get-LinkTarget([string]$Path) {
    $Item = Get-InstallItem $Path
    if ($null -eq $Item -or [string]::IsNullOrWhiteSpace([string]$Item.LinkType)) {
        return $null
    }
    $Target = @($Item.Target)[0]
    if ([string]::IsNullOrWhiteSpace([string]$Target)) {
        return $null
    }
    if (-not [System.IO.Path]::IsPathRooted($Target)) {
        $Target = Join-Path (Split-Path -Parent $Path) $Target
    }
    return Normalize-Path $Target
}

function Test-LinkPointsTo([string]$Path, [string]$ExpectedTarget) {
    $ActualTarget = Get-LinkTarget $Path
    return $null -ne $ActualTarget -and $ActualTarget -eq (Normalize-Path $ExpectedTarget)
}

function Get-ReceiptRoot([string]$InstallRoot) {
    $ReceiptPath = Join-Path $InstallRoot $ReceiptName
    if (Test-Path -LiteralPath $ReceiptPath -PathType Leaf) {
        return (Get-Content -LiteralPath $ReceiptPath -TotalCount 1).Trim()
    }
    return ''
}

function Test-RepairAuthorized([string]$Path, [string]$RelativePath, [string]$PriorRoot) {
    if (-not $Repair -or [string]::IsNullOrWhiteSpace($PriorRoot)) {
        return $false
    }
    $ExpectedPriorTarget = Normalize-Path (Join-Path $PriorRoot $RelativePath)
    $ActualTarget = Get-LinkTarget $Path
    return $null -ne $ActualTarget -and $ActualTarget -eq $ExpectedPriorTarget
}

if ($RetireOnly) {
    . (Join-Path $RepoRoot 'scripts/retired-skills.ps1')
    Initialize-RetiredCleanup
    Invoke-RetiredCleanup
    exit 0
}

Write-Host 'Validated 13 source skills and their shared references.'

function Test-DestinationRoot([string]$InstallRoot) {
    $Conflicts = 0
    $PriorRoot = Get-ReceiptRoot $InstallRoot
    foreach ($Skill in $Manifest.skills) {
        $Destination = Join-Path $InstallRoot $Skill.name
        $SourceDir = Normalize-Path (Join-Path $RepoRoot $Skill.path)
        $Item = Get-InstallItem $Destination
        if ($null -eq $Item) {
            continue
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$Item.LinkType)) {
            if ((Test-LinkPointsTo $Destination $SourceDir) -or (Test-RepairAuthorized $Destination $Skill.path $PriorRoot)) {
                continue
            }
            Write-Error "$($Skill.name): link points elsewhere: $Destination" -ErrorAction Continue
            $Conflicts++
        } else {
            Write-Error "$($Skill.name): real file/directory exists: $Destination" -ErrorAction Continue
            $Conflicts++
        }
    }
    return $Conflicts
}

if (-not $Uninstall) {
    . (Join-Path $RepoRoot 'scripts/retired-skills.ps1')
    Initialize-RetiredCleanup
    Invoke-RetiredCleanup
    $DestinationConflicts = 0
    if ($Codex) { $DestinationConflicts += Test-DestinationRoot $CodexDir }
    if ($Claude) { $DestinationConflicts += Test-DestinationRoot $ClaudeDir }
    if ($DestinationConflicts -ne 0) {
        throw "Installation stopped before SDD link changes: $DestinationConflicts conflict(s)"
    }
}

$script:Created = 0
$script:AlreadyInstalled = 0
$script:Migrated = 0
$script:Removed = 0
$script:PostFailures = 0

function New-DirectoryLink([string]$Destination, [string]$SourceDir) {
    try {
        New-Item -ItemType SymbolicLink -Path $Destination -Target $SourceDir -ErrorAction Stop | Out-Null
        return 'symbolic link'
    } catch {
        $SymbolicLinkError = $_.Exception.Message
        try {
            New-Item -ItemType Junction -Path $Destination -Target $SourceDir -ErrorAction Stop | Out-Null
            return 'directory junction'
        } catch {
            throw "Unable to link $Destination to $SourceDir. Symbolic-link error: $SymbolicLinkError Junction error: $($_.Exception.Message)"
        }
    }
}

function Remove-DirectoryLink([string]$Path) {
    $Item = Get-InstallItem $Path
    if ($null -eq $Item -or [string]::IsNullOrWhiteSpace([string]$Item.LinkType)) {
        throw "Refusing to remove a non-link destination: $Path"
    }

    # Windows PowerShell 5.1 can throw a NullReferenceException when Remove-Item
    # handles a directory symbolic link. Directory.Delete removes the reparse
    # point itself and does not recurse into its target.
    [System.IO.Directory]::Delete($Path)
    if ($null -ne (Get-InstallItem $Path)) {
        throw "Failed to remove directory link: $Path"
    }
}

function Install-Root([string]$InstallRoot, [string]$ToolLabel) {
    $PriorRoot = Get-ReceiptRoot $InstallRoot
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null

    foreach ($Skill in $Manifest.skills) {
        $SourceDir = Normalize-Path (Join-Path $RepoRoot $Skill.path)
        $Destination = Join-Path $InstallRoot $Skill.name

        if ($Uninstall) {
            if ((Test-LinkPointsTo $Destination $SourceDir) -or (Test-RepairAuthorized $Destination $Skill.path $PriorRoot)) {
                Remove-DirectoryLink $Destination
                $script:Removed++
                Write-Host "$ToolLabel $($Skill.name): removed"
            } elseif ($null -ne (Get-InstallItem $Destination)) {
                Write-Host "$ToolLabel $($Skill.name): preserved unrelated destination"
            }

            if ($null -ne $Skill.legacy_name -and -not [string]::IsNullOrWhiteSpace([string]$Skill.legacy_name)) {
                $LegacyDestination = Join-Path $InstallRoot $Skill.legacy_name
                $LegacyTarget = Get-LinkTarget $LegacyDestination
                $CurrentLegacySource = Normalize-Path (Join-Path $RepoRoot "skills/$($Skill.legacy_name)")
                $PriorLegacySource = if ([string]::IsNullOrWhiteSpace($PriorRoot)) { '' } else { Normalize-Path (Join-Path $PriorRoot "skills/$($Skill.legacy_name)") }
                if ($null -ne $LegacyTarget -and ($LegacyTarget -eq $CurrentLegacySource -or (-not [string]::IsNullOrWhiteSpace($PriorLegacySource) -and $LegacyTarget -eq $PriorLegacySource))) {
                    Remove-DirectoryLink $LegacyDestination
                    $script:Removed++
                    Write-Host "$ToolLabel $($Skill.legacy_name): removed legacy repository link"
                } elseif ($null -ne (Get-InstallItem $LegacyDestination)) {
                    Write-Host "$ToolLabel $($Skill.legacy_name): preserved unrelated legacy skill"
                }
            }
            continue
        }

        if (Test-LinkPointsTo $Destination $SourceDir) {
            $script:AlreadyInstalled++
            Write-Host "$ToolLabel $($Skill.name): already installed"
        } else {
            if ($null -ne (Get-InstallItem $Destination) -and (Test-RepairAuthorized $Destination $Skill.path $PriorRoot)) {
                Remove-DirectoryLink $Destination
            }
            $LinkType = New-DirectoryLink $Destination $SourceDir
            $script:Created++
            Write-Host "$ToolLabel $($Skill.name): linked as $LinkType"
        }

        $SourceSkillFile = Join-Path $SourceDir 'SKILL.md'
        $InstalledSkillFile = Join-Path $Destination 'SKILL.md'
        if (-not (Test-Path -LiteralPath $InstalledSkillFile -PathType Leaf)) {
            Write-Error "$ToolLabel $($Skill.name): post-install SKILL.md missing" -ErrorAction Continue
            $script:PostFailures++
        } else {
            $SourceHash = (Get-FileHash -LiteralPath $SourceSkillFile -Algorithm SHA256).Hash
            $InstalledHash = (Get-FileHash -LiteralPath $InstalledSkillFile -Algorithm SHA256).Hash
            if ($SourceHash -ne $InstalledHash) {
                Write-Error "$ToolLabel $($Skill.name): post-install hash mismatch" -ErrorAction Continue
                $script:PostFailures++
            }
        }

        if ($null -ne $Skill.legacy_name -and -not [string]::IsNullOrWhiteSpace([string]$Skill.legacy_name)) {
            $LegacyDestination = Join-Path $InstallRoot $Skill.legacy_name
            $LegacyTarget = Get-LinkTarget $LegacyDestination
            $CurrentLegacySource = Normalize-Path (Join-Path $RepoRoot "skills/$($Skill.legacy_name)")
            $PriorLegacySource = if ([string]::IsNullOrWhiteSpace($PriorRoot)) { '' } else { Normalize-Path (Join-Path $PriorRoot "skills/$($Skill.legacy_name)") }
            if ($null -ne $LegacyTarget -and ($LegacyTarget -eq $CurrentLegacySource -or (-not [string]::IsNullOrWhiteSpace($PriorLegacySource) -and $LegacyTarget -eq $PriorLegacySource))) {
                Remove-DirectoryLink $LegacyDestination
                $script:Migrated++
                Write-Host "$ToolLabel $($Skill.legacy_name): removed legacy repository link"
            } elseif ($null -ne (Get-InstallItem $LegacyDestination)) {
                Write-Host "$ToolLabel $($Skill.legacy_name): preserved unrelated legacy skill"
            }
        }
    }

    $ReceiptPath = Join-Path $InstallRoot $ReceiptName
    if ($Uninstall) {
        if (Test-Path -LiteralPath $ReceiptPath -PathType Leaf) {
            $RecordedRoot = (Get-Content -LiteralPath $ReceiptPath -TotalCount 1).Trim()
            if ($RecordedRoot -eq $RepoRoot) {
                Remove-Item -LiteralPath $ReceiptPath -Force
            }
        }
    } elseif ($script:PostFailures -eq 0) {
        Set-Content -LiteralPath $ReceiptPath -Value $RepoRoot -Encoding UTF8
    }
}

if ($Codex) { Install-Root $CodexDir 'Codex' }
if ($Claude) { Install-Root $ClaudeDir 'Claude Code' }

Write-Host "Summary: created=$Created already-installed=$AlreadyInstalled migrated=$Migrated removed=$Removed failed=$PostFailures"
if ($PostFailures -ne 0) {
    exit 1
}

if (-not $Uninstall) {
    Write-Host 'Skills are linked to this clone. Use .\update.ps1 for updates and retirement cleanup.'
    Write-Host 'Codex normally discovers new skills automatically. Restart only if they do not appear.'
    Write-Host 'Claude Code reloads SKILL.md changes live; restart if its top-level skills directory was created during this session.'
}
exit 0
