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
            Set-Content -LiteralPath $FetchMarker -Value fetched
            $Output = & $NativeGit -C $GitArgs[1] fetch --quiet $Remote main
        } else { $Output = & $NativeGit @GitArgs }
        $global:LASTEXITCODE = $LASTEXITCODE
        return $Output
    }.GetNewClosure()
    Set-Item -Path Function:git -Value $GitDelegate

    Run-Update
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
    & (Join-Path $Student 'update.ps1') -All -CodexDir $StudentRoots[0] -ClaudeDir $StudentRoots[1]
    Assert-True ($LASTEXITCODE -eq 0) 'Source copies blocked their own retirement.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $Student 'skills/communications-audit'))) 'Source copy remains.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $Student '.agents/skills/issue-happypro-certificate'))) 'Repo-local copy remains.'
    Assert-True ([string]::IsNullOrWhiteSpace(((Test-Git $Student @('status','--porcelain')) -join "`n"))) 'Student checkout is not clean.'
    Write-Host 'Windows updater tests passed.'
} finally {
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
