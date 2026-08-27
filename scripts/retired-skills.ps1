# Dot-sourced by install.ps1 after its source/destination preflight.
$script:RetiredPolicy = @(Import-Csv -LiteralPath (Join-Path $RepoRoot 'retired-skills.tsv') -Delimiter "`t")
$script:RetiredRoots = @()
$script:RetiredActions = @()
$script:RetiredRemoved = 0
$script:RetiredArchived = 0
$script:RetiredPreserved = 0

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

function Read-RetiredReceipt([string]$Path) {
    $Item = Get-InstallItem $Path
    if ($null -eq $Item -or $Item.PSIsContainer -or -not [string]::IsNullOrWhiteSpace([string]$Item.LinkType)) { return '' }
    try { return Get-RetiredAbsolutePath ((Get-Content -LiteralPath $Path -TotalCount 1).Trim()) }
    catch { return '' }
}

function Test-RetiredSddOrigin([string]$Origin) {
    return $Origin -match '^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)ingwarski/(sdd-pipeline-skills|codex-skills)(\.git)?/?$'
}

function Get-RetiredSourceOwner([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return 'unknown' }
    $SourceManifest = Join-Path $Root 'skills-manifest.json'
    $Identity = ''
    if (Test-Path -LiteralPath $SourceManifest -PathType Leaf) {
        try { $Identity = (Get-Content -LiteralPath $SourceManifest -Raw | ConvertFrom-Json).skill_set } catch {}
    }
    if ($Identity -eq 'custom-agent-skills') { return 'foreign' }
    $Top = ''
    try {
        $Top = & git -C $Root rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -ne 0) { $Top = '' }
    } catch { $Top = '' }
    if (-not [string]::IsNullOrWhiteSpace($Top) -and (Normalize-Path $Top) -eq (Normalize-Path $Root)) {
        $Origin = ''
        try { $Origin = & git -C $Root remote get-url origin 2>$null } catch {}
        if (-not [string]::IsNullOrWhiteSpace($Origin)) {
            if (Test-RetiredSddOrigin $Origin) { return 'sdd' }
            return 'foreign'
        }
    }
    if ($Identity -eq 'sdd-pipeline') { return 'sdd' }
    return 'unknown'
}

function Test-RetiredKnownCopy([string]$Folder, [string]$Name) {
    $Rows = @($script:RetiredPolicy | Where-Object { $_.skill -ceq $Name })
    if ($Rows.Count -eq 0) { return $false }
    $Pending = @($Folder)
    $Seen = 0
    while ($Pending.Count -gt 0) {
        $Current = $Pending[0]
        $Pending = @($Pending | Select-Object -Skip 1)
        foreach ($Item in Get-ChildItem -LiteralPath $Current -Force) {
            if (-not [string]::IsNullOrWhiteSpace([string]$Item.LinkType)) { return $false }
            $Relative = $Item.FullName.Substring($Folder.Length + 1).Replace('\', '/')
            if ($Item.PSIsContainer) {
                if (@($Rows | Where-Object { $_.file.StartsWith("$Relative/", [System.StringComparison]::Ordinal) }).Count -eq 0) {
                    return $false
                }
                $Pending += $Item.FullName
            } else {
                $Match = @($Rows | Where-Object { $_.file -ceq $Relative })
                if ($Match.Count -ne 1) { return $false }
                $Hash = (Get-FileHash -LiteralPath $Item.FullName -Algorithm SHA256).Hash
                if ($Hash -ne $Match[0].sha256_lf -and $Hash -ne $Match[0].sha256_crlf) { return $false }
                $Seen++
            }
        }
    }
    return $Seen -eq $Rows.Count
}

function Get-RetiredClassification([string]$Root, [string]$Name) {
    $Path = Join-Path $Root $Name
    $Item = Get-InstallItem $Path
    if ($null -eq $Item) { return 'absent' }
    if (-not [string]::IsNullOrWhiteSpace([string]$Item.LinkType)) {
        $Target = Get-LinkTarget $Path
        if ([string]::IsNullOrWhiteSpace($Target)) { return 'review' }
        $CustomRoot = Read-RetiredReceipt (Join-Path $Root '.custom-agent-skills-source')
        if (-not [string]::IsNullOrWhiteSpace($CustomRoot) -and $Target -eq (Normalize-Path (Join-Path $CustomRoot "skills/$Name"))) {
            return 'preserve'
        }
        $Owner = 'unknown'
        $Suffix = [System.IO.Path]::DirectorySeparatorChar + 'skills' + [System.IO.Path]::DirectorySeparatorChar + $Name
        if ($Target.EndsWith($Suffix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $SourceRoot = $Target.Substring(0, $Target.Length - $Suffix.Length)
            $Owner = Get-RetiredSourceOwner $SourceRoot
            if ($Owner -eq 'foreign') { return 'preserve' }
        }
        $PriorRoot = Read-RetiredReceipt (Join-Path $Root $ReceiptName)
        if ($Target -eq (Normalize-Path (Join-Path $RepoRoot "skills/$Name")) -or
            (-not [string]::IsNullOrWhiteSpace($PriorRoot) -and $Target -eq (Normalize-Path (Join-Path $PriorRoot "skills/$Name")))) {
            return 'unlink'
        }
        foreach ($Source in $RetiredSource) {
            if ($Target -eq (Normalize-Path (Join-Path $Source "skills/$Name"))) { return 'unlink' }
        }
        if ($Owner -eq 'sdd') { return 'unlink' }
        return 'review'
    }
    if ($Item.PSIsContainer) {
        if ((Split-Path -Leaf $Root) -eq 'skills' -and (Get-RetiredSourceOwner (Split-Path -Parent $Root)) -eq 'foreign') {
            return 'preserve'
        }
        if (Test-RetiredKnownCopy $Path $Name) { return 'archive' }
    }
    return 'review'
}

function Add-RetiredRoot([string]$Root) {
    $Root = Get-RetiredAbsolutePath ([System.IO.Path]::GetFullPath($Root))
    if ($script:RetiredRoots -notcontains $Root) { $script:RetiredRoots += $Root }
}

function Initialize-RetiredCleanup {
    $Lines = @(Get-Content -LiteralPath (Join-Path $RepoRoot 'retired-skills.tsv'))
    if (@($Lines | Select-Object -Skip 1 | Where-Object { $_.Split([char]9).Count -ne 4 }).Count -gt 0) {
        throw 'Invalid retirement policy field count.'
    }
    $Header = Get-Content -LiteralPath (Join-Path $RepoRoot 'retired-skills.tsv') -TotalCount 1
    if ($Header -ne "skill`tfile`tsha256_lf`tsha256_crlf" -or $script:RetiredPolicy.Count -eq 0) {
        throw 'Invalid retirement policy.'
    }
    $Seen = @{}
    foreach ($Row in $script:RetiredPolicy) {
        $Key = "$($Row.skill)/$($Row.file)"
        if ($Row.skill -cnotmatch '^[a-z0-9-]+$' -or $Row.file -cnotmatch '^[a-zA-Z0-9_./-]+$' -or
            $Row.file.StartsWith('/') -or $Row.file.Contains('..') -or
            $Row.sha256_lf -cnotmatch '^[a-f0-9]{64}$' -or $Row.sha256_crlf -cnotmatch '^[a-f0-9]{64}$' -or $Seen.ContainsKey($Key)) {
            throw 'Invalid retirement policy row.'
        }
        $Seen[$Key] = $true
    }
    foreach ($Source in $RetiredSource) { $null = Get-RetiredAbsolutePath $Source }
    Add-RetiredRoot (Join-Path $RepoRoot 'skills')
    if ($Codex) {
        Add-RetiredRoot $CodexDir
        if (-not $CodexDirExplicit) {
            foreach ($Default in @((Join-Path $HOME '.agents/skills'), (Join-Path $HOME '.codex/skills'))) {
                if (Test-Path -LiteralPath $Default -PathType Container) { Add-RetiredRoot $Default }
            }
            if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
                $ExtraCodex = Join-Path $env:CODEX_HOME 'skills'
                if (Test-Path -LiteralPath $ExtraCodex -PathType Container) { Add-RetiredRoot $ExtraCodex }
            }
        }
    }
    if ($Claude) { Add-RetiredRoot $ClaudeDir }
    foreach ($Root in $CleanupDir) { Add-RetiredRoot (Get-RetiredAbsolutePath $Root) }

    $NeedsReview = 0
    foreach ($Name in @($script:RetiredPolicy.skill | Select-Object -Unique)) {
        if (@($Manifest.skills | Where-Object { $_.name -eq $Name }).Count -gt 0) { throw "Retired skill is still active: $Name" }
        foreach ($Root in $script:RetiredRoots) {
            $Kind = Get-RetiredClassification $Root $Name
            switch ($Kind) {
                'absent' {}
                'preserve' {
                    $script:RetiredPreserved++
                    Write-Host "Retirement: preserved independent skill $(Join-Path $Root $Name)"
                }
                'review' {
                    $NeedsReview++
                    Write-Warning "REVIEW REQUIRED: $(Join-Path $Root $Name) (modified copy or unproven source; preserved)"
                }
                default {
                    $script:RetiredActions += [pscustomobject]@{ Root=$Root; Name=$Name; Kind=$Kind }
                }
            }
        }
    }
    if ($NeedsReview -gt 0) {
        throw 'Cleanup needs review; no installation changes made. Confirm unknown old clone paths with -RetiredSource, or resolve modified copies first.'
    }
}

function Invoke-RetiredCleanup {
    $BackupBase = ''
    if (@($script:RetiredActions | Where-Object { $_.Kind -eq 'archive' }).Count -gt 0) {
        $BackupBase = if ([string]::IsNullOrWhiteSpace($env:SDD_SKILL_BACKUP_DIR)) {
            Join-Path $HOME '.sdd-pipeline/retired-skills'
        } else { $env:SDD_SKILL_BACKUP_DIR }
        $BackupBase = Get-RetiredAbsolutePath $BackupBase
        foreach ($Root in $script:RetiredRoots) {
            if ($BackupBase -eq $Root -or $BackupBase.StartsWith($Root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw 'Recovery backup must be outside every skill directory.'
            }
        }
        New-Item -ItemType Directory -Path $BackupBase -Force | Out-Null
        $BackupItem = Get-Item -LiteralPath $BackupBase -Force
        if (-not [string]::IsNullOrWhiteSpace([string]$BackupItem.LinkType)) { throw 'Recovery backup directory must not be a link.' }
    }
    foreach ($Action in $script:RetiredActions) {
        $Path = Join-Path $Action.Root $Action.Name
        if ((Get-RetiredClassification $Action.Root $Action.Name) -ne $Action.Kind) { throw "Retired skill changed after preflight: $Path" }
        if ($Action.Kind -eq 'unlink') {
            Remove-DirectoryLink $Path
            $script:RetiredRemoved++
            Write-Host "Retirement: removed old SDD-owned link $Path"
        } else {
            $Backup = Join-Path $BackupBase ($Action.Name + '.' + [guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $Backup | Out-Null
            Set-Content -LiteralPath (Join-Path $Backup 'original-path.txt') -Value $Path -Encoding UTF8
            $BackupSkill = Join-Path $Backup $Action.Name
            Move-Item -LiteralPath $Path -Destination $BackupSkill
            $script:RetiredArchived++
            Write-Host "Retirement: removed copied skill $Path; recovery backup: $BackupSkill"
        }
    }
    Write-Host "Retirement summary: links-removed=$RetiredRemoved copies-archived=$RetiredArchived independent-preserved=$RetiredPreserved review-required=0"
}
