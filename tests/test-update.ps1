$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$TestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('sdd-update-' + [guid]::NewGuid().ToString('N'))
$Publisher = Join-Path $TestRoot 'publisher'
$Checkout = Join-Path $TestRoot 'checkout'
$Remote = Join-Path $TestRoot 'remote.git'
$NativeGit = (Get-Command git -CommandType Application | Select-Object -First 1).Source
$OldResult = $env:SDD_UPDATE_TEST_RESULT
$OldBackup = $env:SDD_SKILL_BACKUP_DIR
$OriginalEvidenceHome = $env:SDD_EVIDENCE_HOME
$StudentRoots = @()

function Test-Git([string]$Root, [string[]]$Arguments) {
    $Output = & $NativeGit -C $Root @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Fixture Git failed: $($Arguments -join ' ')" }
    return $Output
}
function Commit-Fixture([string]$Root, [string]$Message) {
    Test-Git $Root @('-c','user.name=SDD tests','-c','user.email=sdd-tests@example.invalid','commit','--quiet','-m',$Message)
}
function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Run-Update {
    & (Join-Path $Checkout 'update.ps1') -Codex
}
function Expect-Failure([string]$Message) {
    $Detected = $false
    try { Run-Update } catch {
        if ($_.Exception.Message -notlike "*$Message*") { throw }
        $Detected = $true
    }
    Assert-True $Detected "Expected updater to stop: $Message"
    Assert-True (-not (Test-Path -LiteralPath $env:SDD_UPDATE_TEST_RESULT)) 'Installer ran after a failed update check.'
}
try {
    $env:SDD_EVIDENCE_HOME = Join-Path $TestRoot 'evidence-machine-state'
    New-Item -ItemType Directory -Path (Join-Path $Publisher 'scripts') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'update.ps1') -Destination (Join-Path $Publisher 'update.ps1')
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'scripts/retired-skills.ps1') -Destination (Join-Path $Publisher 'scripts/retired-skills.ps1')
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'retired-skills.txt') -Destination (Join-Path $Publisher 'retired-skills.txt')
    $OldStub = @(
        'param([switch]$RetireOnly, [switch]$Codex, [switch]$All, [string]$CodexDir, [string]$ClaudeDir)',
        'if (-not $RetireOnly) { throw "Old installer must not install" }',
        'exit 0'
    )
    Set-Content -LiteralPath (Join-Path $Publisher 'install.ps1') -Value $OldStub
    Test-Git $Publisher @('init','--quiet','--initial-branch=main')
    Test-Git $Publisher @('add','--','update.ps1','install.ps1','scripts/retired-skills.ps1','retired-skills.txt')
    Commit-Fixture $Publisher initial
    & $NativeGit clone --quiet --bare $Publisher $Remote
    Assert-True ($LASTEXITCODE -eq 0) 'Fixture bare clone failed.'
    & $NativeGit clone --quiet $Remote $Checkout
    Assert-True ($LASTEXITCODE -eq 0) 'Fixture checkout failed.'
    Test-Git $Checkout @('remote','set-url','origin','https://github.com/Ingwarski/sdd-pipeline-skills.git')
    $Stub = @(
        'param([switch]$Repair, [switch]$Codex, [switch]$RetireOnly, [switch]$All, [string]$CodexDir, [string]$ClaudeDir)',
        'if ($RetireOnly) { exit 0 }',
        'if (-not $Repair -or -not $Codex) { throw "Installer flags were not forwarded" }',
        'Set-Content -LiteralPath $env:SDD_UPDATE_TEST_RESULT -Value new',
        'exit 0'
    )
    Set-Content -LiteralPath (Join-Path $Publisher 'install.ps1') -Value $Stub
    Test-Git $Publisher @('add','--','install.ps1')
    Commit-Fixture $Publisher updated
    Test-Git $Publisher @('push','--quiet',$Remote,'main')
    $env:SDD_UPDATE_TEST_RESULT = Join-Path $TestRoot 'result.txt'
    $FetchMarker = Join-Path $TestRoot 'fetched'

    # Intercept only fetch; other Git operations run normally against the fixture.
    $GitDelegate = {
        $GitArgs = @($args)
        if ($GitArgs.Count -ge 3 -and $GitArgs[0] -eq '-C' -and $GitArgs[2] -eq 'fetch') {
            Set-Content -LiteralPath $FetchMarker -Value $GitArgs[-1]
            $Output = & $NativeGit -C $GitArgs[1] fetch --quiet $Remote $GitArgs[-1]
        } else { $Output = & $NativeGit @GitArgs }
        $global:LASTEXITCODE = $LASTEXITCODE
        # This fixture also leaves a caller-local code, as an enclosing host can.
        # Python native results must not be mistaken for this stale Git success.
        Set-Variable -Name LASTEXITCODE -Value $LASTEXITCODE -Scope 1
        return $Output
    }
    Set-Item -Path Function:git -Value $GitDelegate

    # A missing tested release must stop even when a newer main is available.
    $InitialHead = Test-Git $Checkout @('rev-parse','HEAD')
    Expect-Failure 'Git update check failed: fetch'
    Assert-True ((Test-Git $Checkout @('rev-parse','HEAD')) -eq $InitialHead) 'Missing stable changed the checkout.'
    Assert-True ((Get-Content -LiteralPath $FetchMarker -Raw).Trim() -eq 'stable') 'Default update did not select stable.'
    Remove-Item -LiteralPath $FetchMarker
    Test-Git $Publisher @('push','--quiet',$Remote,'HEAD:refs/heads/stable')

    Run-Update
    Assert-True ((Get-Content -LiteralPath $FetchMarker -Raw).Trim() -eq 'stable') 'Default update did not select stable.'
    Assert-True ((Get-Content -LiteralPath $env:SDD_UPDATE_TEST_RESULT -Raw).Trim() -eq 'new') 'Fresh installer was not executed.'
    Assert-True ((Test-Git $Checkout @('rev-parse','HEAD')) -eq (Test-Git $Publisher @('rev-parse','HEAD'))) 'Checkout did not fast-forward.'
    Remove-Item -LiteralPath $env:SDD_UPDATE_TEST_RESULT, $FetchMarker
    Set-Content -LiteralPath (Join-Path $Checkout 'local.txt') -Value 'user work'
    Expect-Failure 'Local changes exist'
    Assert-True (-not (Test-Path -LiteralPath $FetchMarker)) 'Dirty update attempted a fetch.'
    Remove-Item -LiteralPath (Join-Path $Checkout 'local.txt')
    Test-Git $Checkout @('switch','--quiet','-c','work-in-progress')
    Expect-Failure 'requires main'
    Test-Git $Checkout @('switch','--quiet','main')
    Test-Git $Checkout @('remote','set-url','origin','https://github.com/someone/unrelated.git')
    Expect-Failure 'not the expected SDD'
    Assert-True (-not (Test-Path -LiteralPath $FetchMarker)) 'Unrelated origin was fetched.'
    Test-Git $Checkout @('remote','set-url','origin','https://github.com/Ingwarski/codex-skills.git')
    Run-Update
    Remove-Item -LiteralPath $env:SDD_UPDATE_TEST_RESULT, $FetchMarker

    Set-Content -LiteralPath (Join-Path $Checkout 'local.txt') -Value local-commit
    Test-Git $Checkout @('add','--','local.txt')
    Commit-Fixture $Checkout local
    $LocalHead = Test-Git $Checkout @('rev-parse','HEAD')
    Expect-Failure 'ahead of GitHub'
    Assert-True ((Test-Git $Checkout @('rev-parse','HEAD')) -eq $LocalHead) 'Local history was changed.'
    Set-Content -LiteralPath (Join-Path $Publisher 'upstream.txt') -Value upstream-change
    Test-Git $Publisher @('add','--','upstream.txt')
    Commit-Fixture $Publisher upstream
    Test-Git $Publisher @('push','--quiet',$Remote,'main')
    Test-Git $Publisher @('push','--quiet',$Remote,'HEAD:refs/heads/stable')
    Expect-Failure 'diverge'
    Assert-True ((Test-Git $Checkout @('rev-parse','HEAD')) -eq $LocalHead) 'Diverged history was replaced.'

    # A student's real update must delete the retired copies, not just run a stub.
    $Student = Join-Path $TestRoot 'student'
    $StudentRoots = @((Join-Path $TestRoot 'student-codex'), (Join-Path $TestRoot 'student-claude'))
    & $NativeGit clone --quiet $Remote $Student
    Assert-True ($LASTEXITCODE -eq 0) 'Student fixture clone failed.'
    Test-Git $Student @('remote','set-url','origin','https://github.com/Ingwarski/sdd-pipeline-skills.git')
    foreach ($File in @('install.ps1', 'skills-manifest.json')) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot $File) -Destination (Join-Path $Publisher $File)
    }
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'skills') -Destination (Join-Path $Publisher 'skills') -Recurse
    Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'scripts') -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Publisher 'scripts')
    }
    Test-Git $Publisher @('add','--','install.ps1','skills-manifest.json','scripts','skills')
    Commit-Fixture $Publisher real-installer
    Test-Git $Publisher @('push','--quiet',$Remote,'main')
    Test-Git $Publisher @('push','--quiet',$Remote,'HEAD:refs/heads/stable')
    foreach ($Root in $StudentRoots) {
        foreach ($Name in @('communications-audit', 'issue-happypro-certificate')) {
            $Copy = Join-Path $Root $Name
            New-Item -ItemType Directory -Path $Copy -Force | Out-Null
            Set-Content -LiteralPath (Join-Path $Copy 'SKILL.md') -Value edited-copy
        }
    }
    $env:SDD_SKILL_BACKUP_DIR = Join-Path $TestRoot 'former-backups'
    & (Join-Path $Student 'update.ps1') -All -CodexDir $StudentRoots[0] -ClaudeDir $StudentRoots[1]
    Assert-True ($LASTEXITCODE -eq 0) 'Real student update failed.'
    foreach ($Root in $StudentRoots) {
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $Root 'communications-audit'))) 'Audit copy remains after update.'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $Root 'issue-happypro-certificate'))) 'Certificate copy remains after update.'
        Assert-True (Test-Path -LiteralPath (Join-Path $Root 'to-sdd-pipeline/SKILL.md')) 'SDD was not installed.'
    }
    Assert-True (-not (Test-Path -LiteralPath $env:SDD_SKILL_BACKUP_DIR)) 'Student update created a backup.'
    foreach ($Relative in @('skills/communications-audit', '.agents/skills/issue-happypro-certificate')) {
        $Copy = Join-Path $Student $Relative
        New-Item -ItemType Directory -Path $Copy -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $Copy 'SKILL.md') -Value local-copy
    }
    $UpdateMessages = @(& (Join-Path $Student 'update.ps1') -All -CodexDir $StudentRoots[0] -ClaudeDir $StudentRoots[1] -EvidenceNonInteractive 6>&1)
    Assert-True ($LASTEXITCODE -eq 0) 'Source copies blocked their own retirement.'
    $UpdateText = $UpdateMessages -join "`n"
    Assert-True ($UpdateText -like '*Skills are current; evidence storage setup is required.*') 'Already-current update hid missing evidence setup.'
    Assert-True ($UpdateText -notlike '*Skills and evidence storage setup are current*') 'Missing evidence setup was reported as configured.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $Student 'skills/communications-audit'))) 'Source copy remains.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $Student '.agents/skills/issue-happypro-certificate'))) 'Repo-local copy remains.'
    Assert-True ([string]::IsNullOrWhiteSpace(((Test-Git $Student @('status','--porcelain')) -join "`n"))) 'Student checkout is not clean.'
    Test-Git $Publisher @('push','--quiet',$Remote,'HEAD:refs/heads/stable')
    Set-Content -LiteralPath (Join-Path $Publisher 'unverified.txt') -Value unverified
    Test-Git $Publisher @('add','--','unverified.txt')
    Commit-Fixture $Publisher unverified
    Test-Git $Publisher @('push','--quiet',$Remote,'main')
    & (Join-Path $Student 'update.ps1') -All -CodexDir $StudentRoots[0] -ClaudeDir $StudentRoots[1]
    Assert-True ($LASTEXITCODE -eq 0) 'Tested-channel update failed.'
    Assert-True ((Get-Content -LiteralPath $FetchMarker -Raw).Trim() -eq 'stable') 'Default student update did not select stable.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $Student 'unverified.txt'))) 'Stable consumed an unverified main commit.'
    # Explicit maintenance/testing selection works; a later default cannot downgrade.
    & (Join-Path $Student 'update.ps1') -Channel main -All -CodexDir $StudentRoots[0] -ClaudeDir $StudentRoots[1]
    Assert-True ($LASTEXITCODE -eq 0) 'Explicit main update failed.'
    Assert-True ((Get-Content -LiteralPath $FetchMarker -Raw).Trim() -eq 'main') 'Explicit main selection was not forwarded.'
    Assert-True (Test-Path -LiteralPath (Join-Path $Student 'unverified.txt')) 'Explicit main did not install its revision.'
    $MaintenanceHead = Test-Git $Student @('rev-parse','HEAD')
    $DowngradeStopped = $false
    try { & (Join-Path $Student 'update.ps1') -All -CodexDir $StudentRoots[0] -ClaudeDir $StudentRoots[1] } catch {
        if ($_.Exception.Message -notlike '*ahead of GitHub*') { throw }
        $DowngradeStopped = $true
    }
    Assert-True $DowngradeStopped 'Default stable update did not refuse a downgrade.'
    Assert-True ((Test-Git $Student @('rev-parse','HEAD')) -eq $MaintenanceHead) 'Default stable update replaced newer local history.'
    Assert-True (Test-Path -LiteralPath (Join-Path $Student 'unverified.txt')) 'Default stable update removed newer work.'
    Write-Host 'Windows updater tests passed.'
} finally {
    $env:SDD_EVIDENCE_HOME = $OriginalEvidenceHome
    Remove-Item -Path Function:git -ErrorAction SilentlyContinue
    $env:SDD_UPDATE_TEST_RESULT = $OldResult
    $env:SDD_SKILL_BACKUP_DIR = $OldBackup
    foreach ($Root in $StudentRoots) {
        if (Test-Path -LiteralPath $Root) {
            foreach ($Item in Get-ChildItem -LiteralPath $Root -Force) {
                if ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { [System.IO.Directory]::Delete($Item.FullName) }
            }
        }
    }
    if ($TestRoot.StartsWith([System.IO.Path]::GetTempPath(), [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $TestRoot) -like 'sdd-update-*') {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
