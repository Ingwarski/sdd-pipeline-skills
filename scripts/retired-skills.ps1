# Permanent retirement of the two accidentally distributed business skills.
# Dot-sourcing alone performs no cleanup.
$script:RetiredNames = @('communications-audit', 'issue-happypro-certificate')
$script:RetiredRoots = @()
$script:RetiredBackupRoots = @()
$script:RetiredRemoved = 0
$script:RetiredBackupsRemoved = 0

function Test-RetiredSddOrigin([string]$Origin) {
    return $Origin -match '^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)ingwarski/(sdd-pipeline-skills|codex-skills)(\.git)?/?$'
}

function Get-RetiredItem([string]$Path) {
    try { return Get-Item -LiteralPath $Path -Force -ErrorAction Stop }
    catch {
        if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { return $null }
        throw
    }
}

function Get-RetiredAbsolutePath([string]$Path) {
    if (-not [System.IO.Path]::IsPathRooted($Path) -or $Path.Contains([char]10) -or $Path.Contains([char]13)) {
        throw 'Cleanup paths must be absolute.'
    }
    $Full = [System.IO.Path]::GetFullPath($Path)
    if ((Normalize-Path $Full) -eq (Normalize-Path ([System.IO.Path]::GetPathRoot($Full)))) {
        throw 'Cleanup paths cannot be filesystem roots.'
    }
    return Normalize-Path $Full
}

function Add-RetiredRoot([string]$Root) {
    $Root = Get-RetiredAbsolutePath ([System.IO.Path]::GetFullPath($Root))
    $Item = Get-RetiredItem $Root
    if ($null -ne $Item -and -not $Item.PSIsContainer) { throw "Cleanup root is not a directory: $Root" }
    if ($script:RetiredRoots -notcontains $Root) { $script:RetiredRoots += $Root }
}

function Initialize-RetiredCleanup {
    $PolicyPath = Join-Path $RepoRoot 'retired-skills.txt'
    $PolicyItem = Get-RetiredItem $PolicyPath
    if ($null -eq $PolicyItem -or ($PolicyItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw 'Missing or linked retirement policy.'
    }
    $Policy = @(Get-Content -LiteralPath $PolicyPath)
    if (($Policy -join '|') -cne ($script:RetiredNames -join '|')) {
        throw 'Invalid retirement policy: only the two retired business skills are allowed.'
    }
    foreach ($Name in $script:RetiredNames) {
        if (@($Manifest.skills | Where-Object { $_.name -eq $Name }).Count -gt 0) { throw "Retired skill is still active: $Name" }
    }
    Add-RetiredRoot (Join-Path $RepoRoot 'skills')
    if ($Codex) {
        Add-RetiredRoot $CodexDir
        Add-RetiredRoot (Join-Path $RepoRoot '.agents/skills')
        Add-RetiredRoot (Join-Path $RepoRoot '.codex/skills')
        if (-not $CodexDirExplicit) {
            Add-RetiredRoot (Join-Path $HOME '.agents/skills')
            Add-RetiredRoot (Join-Path $HOME '.codex/skills')
            if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) { Add-RetiredRoot (Join-Path $env:CODEX_HOME 'skills') }
        }
    }
    if ($Claude) {
        Add-RetiredRoot $ClaudeDir
        Add-RetiredRoot (Join-Path $RepoRoot '.claude/skills')
    }
    foreach ($Root in $CleanupDir) { Add-RetiredRoot (Get-RetiredAbsolutePath $Root) }
    if ($RetiredSource.Count -gt 0) {
        Write-Host '-RetiredSource is no longer needed. Use -CleanupDir OLD_CLONE/skills to include another clone.'
    }
    # Only inspect these locations for backups made by the former updater.
    foreach ($Root in @((Join-Path $HOME '.sdd-pipeline/retired-skills'), $env:SDD_SKILL_BACKUP_DIR)) {
        if (-not [string]::IsNullOrWhiteSpace($Root)) {
            $Root = Get-RetiredAbsolutePath $Root
            if ($script:RetiredBackupRoots -notcontains $Root) { $script:RetiredBackupRoots += $Root }
        }
    }
}

function Remove-RetiredTree([string]$Path) {
    $Item = Get-RetiredItem $Path
    if ($null -eq $Item) { return }
    if ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        # Do not recurse through a junction or symbolic link, even inside a copy.
        if ($Item.PSIsContainer) { [System.IO.Directory]::Delete($Path) }
        else { [System.IO.File]::Delete($Path) }
    } elseif ($Item.PSIsContainer) {
        foreach ($Child in Get-ChildItem -LiteralPath $Path -Force) { Remove-RetiredTree $Child.FullName }
        $Item.Attributes = $Item.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly)
        [System.IO.Directory]::Delete($Path)
    } else {
        Remove-Item -LiteralPath $Path -Force
    }
}

function Remove-RetiredSkill([string]$Root, [string]$Name) {
    if ($Name -cnotin @('communications-audit', 'issue-happypro-certificate')) { throw 'Not an authorized retired skill.' }
    $Root = Get-RetiredAbsolutePath $Root
    $Path = Join-Path $Root $Name
    if ($null -eq (Get-RetiredItem $Path)) { return }
    Write-Host "Retirement: permanently deleting $Path"
    Remove-RetiredTree $Path
    if ($null -ne (Get-RetiredItem $Path)) { throw "Retired skill still exists: $Path" }
    $script:RetiredRemoved++
}

function Remove-FormerRetirementBackups {
    foreach ($Base in $script:RetiredBackupRoots) {
        if ($null -eq (Get-RetiredItem $Base)) { continue }
        foreach ($Entry in Get-ChildItem -LiteralPath $Base -Force) {
            if (-not $Entry.PSIsContainer -or ($Entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { continue }
            $Marker = Join-Path $Entry.FullName 'original-path.txt'
            $MarkerItem = Get-RetiredItem $Marker
            if ($null -eq $MarkerItem -or $MarkerItem.PSIsContainer -or ($MarkerItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { continue }
            $Original = ''
            try { $Original = Get-RetiredAbsolutePath (Get-Content -LiteralPath $Marker -TotalCount 1) } catch { continue }
            foreach ($Name in $script:RetiredNames) {
                if ($Entry.Name -cnotmatch ('^' + [regex]::Escape($Name) + '\.([a-zA-Z0-9]{6}|[a-fA-F0-9]{32})$')) { continue }
                $MatchesRoot = @($script:RetiredRoots | Where-Object { $Original -eq (Join-Path $_ $Name) }).Count -gt 0
                if (-not $MatchesRoot) { continue }
                if ($null -ne (Get-RetiredItem (Join-Path $Entry.FullName $Name))) {
                    Remove-RetiredSkill $Entry.FullName $Name
                    $script:RetiredBackupsRemoved++
                }
                Remove-Item -LiteralPath $Marker -Force
                if (@(Get-ChildItem -LiteralPath $Entry.FullName -Force).Count -eq 0) {
                    [System.IO.Directory]::Delete($Entry.FullName)
                }
            }
        }
    }
}

function Invoke-RetiredCleanup {
    foreach ($Root in $script:RetiredRoots) {
        foreach ($Name in $script:RetiredNames) { Remove-RetiredSkill $Root $Name }
    }
    Remove-FormerRetirementBackups
    foreach ($Root in $script:RetiredRoots) {
        foreach ($Name in $script:RetiredNames) {
            if ($null -ne (Get-RetiredItem (Join-Path $Root $Name))) { throw "Retirement incomplete: $(Join-Path $Root $Name)" }
        }
    }
    Write-Host "Retirement summary: permanently-deleted=$RetiredRemoved former-backups-deleted=$RetiredBackupsRemoved remaining=0 backups-created=0"
}
