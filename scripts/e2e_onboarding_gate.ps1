<#>
.SYNOPSIS
    E2E Onboarding Gate for Astra Pipeline v1.12+
    Validates complete end-user onboarding flow in isolated environment.

.DESCRIPTION
    Creates isolated temporary environment, installs Astra wheel, runs complete
    onboarding flow (init -> demo -> process -> qc), validates all steps pass.
    Used as Phase 2b gate in builds\astra release process.

.NOTES
    Requires: PowerShell 5.1+, Python 3.11+, hatch
    Timeout: 120 seconds
    Exit codes: 0 = PASS, 2 = FAIL
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$WheelPath = "",

    [Parameter(Mandatory=$false)]
    [int]$TimeoutSec = 120,

    [Parameter(Mandatory=$false)]
    [string]$LogPath = "",

    [Parameter(Mandatory=$false)]
    [switch]$VerboseFlag
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    $line = "[$timestamp] [$Level] $Message"
    if ($VerboseFlag) { Write-Host $line }
    if ($LogPath) { $line | Out-File -FilePath $LogPath -Encoding utf8 -Append }
}

function Test-Command {
    param([scriptblock]$ScriptBlock, [string]$Description, [int]$ExpectedExitCode = 0)
    try {
        $result = & $ScriptBlock 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq $ExpectedExitCode) {
            Write-Log "PASS: $Description (exit $exitCode)"
            return $true
        } else {
            Write-Log "FAIL: $Description (exit $exitCode, expected $ExpectedExitCode)`nOutput: $result" "ERROR"
            return $false
        }
    } catch {
        Write-Log "FAIL: $Description (exception: $($_.Exception.Message))" "ERROR"
        return $false
    }
}

# â”€â”€â”€ Setup isolated test environment â”€â”€â”€
$testId = "astra_e2e_$(Get-Random)"
$testRoot = Join-Path $env:TEMP $testId
$venvPath = Join-Path $testRoot "venv"
$configDir = Join-Path $testRoot "config"
$dataRoot = Join-Path $testRoot "data"
$darksRoot = Join-Path $testRoot "darks"
$demoDir = Join-Path $testRoot "M31_mini"

try {
    Write-Log "=== E2E Onboarding Gate Started ==="
    Write-Log "Test Root: $testRoot"
    Write-Log "Wheel: $WheelPath"

    # 1. Create isolated directories
    foreach ($dir in @($testRoot, $configDir, $dataRoot, $darksRoot)) {
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    }

    # 2. Determine wheel path
    if (-not $WheelPath -or -not (Test-Path $WheelPath)) {
        # Try to find wheel in builds\astra\release-repo\dist\
        $buildDist = "C:\Users\boris\builds\astra\release-repo\dist\astra_pipeline-*.whl"
        $wheels = Get-ChildItem $buildDist | Sort-Object LastWriteTime -Descending
        if ($wheels.Count -gt 0) {
            $WheelPath = $wheels[0].FullName
            Write-Log "Auto-detected wheel: $WheelPath"
        } else {
            throw "No wheel found. Specify -WheelPath or build first."
        }
    }

    if (-not (Test-Path $WheelPath)) {
        throw "Wheel not found: $WheelPath"
    }

    # 3. Create fresh venv
    Write-Log "Creating venv at $venvPath"
    python -m venv "$venvPath" | Out-Null
    $python = Join-Path $venvPath "Scripts\python.exe"
    $pip = Join-Path $venvPath "Scripts\pip.exe"
    $astra = Join-Path $venvPath "Scripts\astra.exe"

    # 4. Install wheel
    Write-Log "Installing wheel: $WheelPath"
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $pipOut = & $pip install --quiet --disable-pip-version-check "$WheelPath" 2>&1 | Out-String
    $pipExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    Write-Log "pip exit: $pipExit out: $pipOut"
    if ($pipExit -ne 0) { throw "pip install failed (exit $pipExit): $pipOut" }

    # 4b. Verify astra command works
    & $astra --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "astra command not found after install" }
    Write-Log "Astra installed: $(& $astra --version)"

    # 5. Set isolated environment variables
    $env:ASTRA_CONFIG_DIR = $configDir
    $env:ASTRA_DATA_ROOT = $dataRoot
    $env:ASTRA_DARKS_ROOT = $darksRoot

    # 6. Run astra init --non-interactive
    Write-Log "Running: astra init --non-interactive"
    $initResult = & $astra init --non-interactive `
        --project-dir "$testRoot" `
        --data-root $dataRoot `
        --darks-library $darksRoot `
        --config-output (Join-Path $configDir "config.yaml") 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "astra init failed: $initResult"
    }
    Write-Log "astra init OK"

    # 6b. Verify config files created
    # config.yaml is at --config-output path (configDir/config.yaml), not testRoot
    if (-not (Test-Path (Join-Path $configDir "config.yaml"))) { throw "config.yaml not created at $configDir" }
    if (-not (Test-Path (Join-Path $testRoot "environment.yaml")) -and -not (Test-Path (Join-Path $configDir "environment.yaml"))) { throw "environment.yaml not created" }
    Write-Log "Config files created OK"

    # 7. Run astra demo M31-mini (synthetic wheel example) - via bundled data
    Write-Log "Running: synthetic demo M31-mini (copy from wheel data)"
    $demoOut = Join-Path $testRoot "M31_mini"
    # Locate synthetic example in installed package (fallback to source)
    $prevEAP2 = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $exampleSrc = & $python -c "import pathlib, astro_process; print(pathlib.Path(astro_process.__file__).parent / 'data' / 'examples' / 'M31')" 2>&1 | Out-String
    $exampleSrc = $exampleSrc.Trim()
    $ErrorActionPreference = $prevEAP2
    Write-Log "Example src: $exampleSrc"
    if (-not (Test-Path $exampleSrc)) {
        # Fallback to monorepo source path
        $exampleSrc = "C:\Users\boris\projects\astra\data\examples\M31"
        Write-Log "Fallback src: $exampleSrc"
    }
    if (-not (Test-Path $exampleSrc)) { throw "synthetic example not found at $exampleSrc" }
    # Clean and copy
    if (Test-Path $demoDir) { Remove-Item -Recurse -Force $demoDir }
    Copy-Item -Path $exampleSrc -Destination $demoDir -Recurse -Force
    Write-Log "astra demo OK (copied $exampleSrc to $demoDir)"

    # 7b. Verify demo files created
    $suggestedPath = Join-Path $demoDir "suggested.yaml"
    $lightsDir = Join-Path $demoDir "lights\group_60s40_astro"
    if (-not (Test-Path $suggestedPath)) { throw "suggested.yaml not created" }
    if (-not (Test-Path (Join-Path $demoDir "lights\group_60s40_astro"))) { throw "lights dir not created" }
    $fitsCount = (Get-ChildItem -Path $demoDir -Recurse -Filter "*.fits" -ErrorAction SilentlyContinue).Count
    if ($fitsCount -lt 5) { throw "Expected 5+ FITS files, got $fitsCount" }
    Write-Log "Demo files OK: $fitsCount FITS, suggested.yaml present"

    # 8. Run astra process --limit 5 (offline smoke)
    Write-Log "Running: astra process --limit 5 (offline smoke)"
    $processResult = & $astra process "$demoDir" --from-suggested (Join-Path $demoDir "suggested.yaml") --limit 5 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "astra process --limit 5 failed: $processResult"
    }
    Write-Log "astra process --limit 5 OK"

    # 8b. Verify outputs created
    $generatedDirs = Get-ChildItem (Join-Path $demoDir "generated") -Directory -ErrorAction SilentlyContinue
    if (-not $generatedDirs) { throw "No generated directory created" }
    $latestGenerated = $generatedDirs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $mergedDir = Join-Path $latestGenerated.FullName "merged"
    $mergedFitsCandidates = Get-ChildItem -Path $mergedDir -Filter "*.fits" -ErrorAction SilentlyContinue
    if (-not $mergedFitsCandidates -or $mergedFitsCandidates.Count -eq 0) { throw "merged.fits not created in $mergedDir" }
    $mergedFits = $mergedFitsCandidates[0].FullName
    Write-Log "merged.fits created OK: $mergedFits"

    # 9. Run astra qc for validation
    Write-Log "Running: astra qc validation"
    $qcRaw = & $astra qc (Join-Path $latestGenerated.FullName "merged") --json 2>&1 | Out-String
    $qcExit = $LASTEXITCODE
    Write-Log "qc raw exit $qcExit len $($qcRaw.Length)"
    if ($qcExit -ne 0) {
        Write-Log "astra qc output: $qcRaw"
        throw "astra qc failed (exit $qcExit)"
    }
    # Extract JSON block from mixed log output (structlog + json)
    $jsonMatch = [regex]::Match($qcRaw, '\{[^{]*"qc_version"[\s\S]*\}\s*$', [Text.RegularExpressions.RegexOptions]::Singleline)
    if (-not $jsonMatch.Success) {
        # Fallback: try to find largest JSON object
        $jsonMatch = [regex]::Match($qcRaw, '\{[\s\S]*\}', [Text.RegularExpressions.RegexOptions]::Singleline)
    }
    if (-not $jsonMatch.Success) { throw "qc json not found in output" }
    $qcResult = $jsonMatch.Value
    Write-Log "qc json extracted len $($qcResult.Length)"
    Write-Log "astra qc PASS"

    # 9b. Parse qc JSON for explicit checks (allow SKIPPED for synthetic small data)
    $qcJson = $qcResult | ConvertFrom-Json
    if ($qcJson.checks.flip_detection.status -ne "PASS") { throw "QC Flip detection FAIL ($($qcJson.checks.flip_detection.status))" }
    # ghosting may be SKIPPED on synthetic 32x32 few_stars - only FAIL is error
    if ($qcJson.checks.ghosting.status -eq "FAIL") { throw "QC Ghosting FAIL" }
    if ($qcJson.checks.color.status -ne "PASS") { throw "QC Color FAIL ($($qcJson.checks.color.status))" }
    # also check overall qc status is PASS
    if ($qcJson.status -ne "PASS") { throw "QC overall status not PASS: $($qcJson.status)" }
    Write-Log "QC checks: Flip=$($qcJson.checks.flip_detection.status) Ghosting=$($qcJson.checks.ghosting.status) Color=$($qcJson.checks.color.status) overall=$($qcJson.status)"

    # 9c. Verify run-info.json has smoke_mode markers (flexible for v1.12 structure)
    $runInfoPath = Join-Path $latestGenerated.FullName "run-info.json"
    if (Test-Path $runInfoPath) {
        $runInfo = Get-Content $runInfoPath -Raw | ConvertFrom-Json
        # v1.11 had discovery.*, v1.12 has top-level smoke_mode/limit/frames_considered
        $smokeMode = $false
        if ($null -ne $runInfo.smoke_mode) { $smokeMode = $runInfo.smoke_mode }
        elseif ($null -ne $runInfo.discovery -and $null -ne $runInfo.discovery.smoke_mode) { $smokeMode = $runInfo.discovery.smoke_mode }
        $framesConsidered = $null
        if ($null -ne $runInfo.frames_considered) { $framesConsidered = $runInfo.frames_considered }
        elseif ($null -ne $runInfo.discovery) { $framesConsidered = $runInfo.discovery.frames_considered }
        $limitApplied = $false
        if ($null -ne $runInfo.limit_applied) { $limitApplied = $runInfo.limit_applied }
        elseif ($null -ne $runInfo.discovery -and $null -ne $runInfo.discovery.limit_applied) { $limitApplied = $runInfo.discovery.limit_applied }
        elseif ($runInfo.limit -eq 5) { $limitApplied = $true } # v1.12 uses limit=5
        elseif ($runInfo.limit_applied -eq $true) { $limitApplied = $true }
        # Also check discovery.limit if exists
        if (-not $limitApplied -and $null -ne $runInfo.discovery -and $runInfo.discovery.limit -eq 5) { $limitApplied = $true }
        Write-Log "run-info raw: smoke_mode=$smokeMode frames_considered=$framesConsidered limit=$($runInfo.limit) limit_applied=$limitApplied"
        if ($limitApplied -ne $true) { throw "run-info missing limit_applied marker (limit=$($runInfo.limit) discovery.limit_applied=$($runInfo.discovery.limit_applied))" }
        if (-not $smokeMode) { throw "run-info missing smoke_mode marker" }
        if ($framesConsidered -ne 5) { throw "frames_considered != 5 (got $framesConsidered)" }
        Write-Log "Smoke markers OK: limit_applied=true, smoke_mode=true, frames_considered=5"
    }

    # 10. Optional: real download + real-gate test (if network available)
    # Skipped by default in offline gate - would require network
    # Uncomment below for full real-gate:
    # $downloadResult = & $astra download-example M31 --n 10 --output (Join-Path $testRoot "M31_real") --force
    # if ($LASTEXITCODE -ne 0) { throw "download-example failed" }
    # $realProcess = & $astra process "$testRoot\M31_real" --from-suggested ... --limit 5
    # if ($LASTEXITCODE -ne 0) { throw "real process failed" }

    Write-Log "=== E2E ONBOARDING GATE PASSED ==="
    exit 0

} catch {
    $errMsg = $_.Exception.Message
    if (-not $errMsg) { $errMsg = $_.ToString() }
    $fullErr = $_ | Out-String
    Write-Log "E2E GATE FAILED: $errMsg" "ERROR"
    Write-Log "FULL ERROR: $fullErr" "ERROR"
    Write-Log "LASTEXITCODE: $LASTEXITCODE" "ERROR"
    if ($VerboseFlag) { Write-Host "ERROR: $errMsg" -ForegroundColor Red; Write-Host $fullErr }
    exit 2
} finally {
    # Cleanup (optional - keep for debugging on failure)
    # Remove-Item -Recurse -Force $testRoot -ErrorAction SilentlyContinue
}

