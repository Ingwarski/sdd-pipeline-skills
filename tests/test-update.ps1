$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$TestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('sdd-update-' + [guid]::NewGuid().ToString('N'))
$Publisher = Join-Path $TestRoot 'publisher'
$Checkout = Join-Path $TestRoot 'checkout'
$Remote = Join-Path $TestRoot 'remote.git'
$NativeGit = (Get-Command git -CommandType Application).Source
$OldResult = $env:SDD_UPDATE_TEST_RESULT

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
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'retired-skills.tsv') -Destination (Join-Path $Publisher 'retired-skills.tsv')
    Set-Content -LiteralPath (Join-Path $Publisher 'install.ps1') -Value 'throw "Old installer must not run"'
    Test-Git $Publisher @('init','--quiet','--initial-branch=main')
    Test-Git $Publisher @('add','--','update.ps1','install.ps1','scripts/retired-skills.ps1','retired-skills.tsv')
    Commit-Fixture $Publisher initial
    & $NativeGit clone --quiet --bare $Publisher $Remote
    Assert-True ($LASTEXITCODE -eq 0) 'Fixture bare clone failed.'
    & $NativeGit clone --quiet $Remote $Checkout
    Assert-True ($LASTEXITCODE -eq 0) 'Fixture checkout failed.'
    Test-Git $Checkout @('remote','set-url','origin','https://github.com/Ingwarski/sdd-pipeline-skills.git')
    $Stub = @(
        'param([switch]$Repair, [switch]$Codex)',
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
    Write-Host 'Windows updater tests passed.'
} finally {
    Remove-Item -Path Function:git -ErrorAction SilentlyContinue
    $env:SDD_UPDATE_TEST_RESULT = $OldResult
    if ($TestRoot.StartsWith([System.IO.Path]::GetTempPath(), [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $TestRoot) -like 'sdd-update-*') {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
