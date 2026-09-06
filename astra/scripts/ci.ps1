<#
.SYNOPSIS
  astra lokales CI-Gate (V1.3-7, ADR-047-konform) - pytest-Suite + Golden-Master-Regression.

.DESCRIPTION
  Rein lokales Test-Gate (kein Git-Remote, kein CI/CD-Provider, kein Netzwerk,
  kein Real-Daten-Pfad). Muster: archibald/scripts/build-all.ps1
  (conventions.md Z. 147-152: PowerShell, scripts/, idempotent, Exit-Code + Summary).

  Schritte:
    1. Env-Selbstcheck (OQ-CI-7): Python >= 3.11, pytest, astroalign importierbar
       -> bei Fehlen klare Meldung und Exit != 0 (roter Lauf wegen fehlendem Env
          wird nicht faelschlich als Produkt-Regression gedeutet).
    2. pytest-Gesamtlauf mit astra/pyproject.toml-Konfiguration
   (testpaths = ["tests"], addopts). Erwartung: 767 passed + 0 skipped
   (Stand v1.5-Sprint-2, 767+0). Die Erwartung ist eine dokumentierte
       Report-Erwartung, KEIN Hard-Assert: Gate-Kriterium ist allein der
       Exit-Code.
    3. GM-Regressions-Status wird aus dem Gesamtlauf abgeleitet (GM-Tests sind
       Teil der Suite: tests/test_quality_foundation.py, tests/test_synthetic.py,
       tests/test_synthetic_injection.py; grun <=> Gesamtlauf grun, bei Rot wird
       anhand fehlgeschlagener GM-Testdateien unterschieden) — deterministisch,
       Seed 42, kein zweiter pytest-Lauf (Laufzeit-optimiert, Spec CI-A
       Lasungsrichtung 2: "Oder als Ausweis aus dem Gesamtlauf").

  Exit-Code-Semantik (maschinelles Gate-Kriterium):
    0  = gruen  (Suite gruen + GM-Regression negativ)
    1  = rot    (Test-Fehler oder GM-Regression erkannt -> STOP -> Maintainer,
                 GM Abs. 6.1: roter Test ist nie Anlass fuer Erwartungswert-Anpassung)
    2  = Env-/Config-Fehler (kein Produkt-Regressions-Urteil)

  Kompakte Status-Ausgabe (CI-D / AC-CI-A7 / AC-CI-D1) am Ende: Testergebnis
  (tatsaechlicher Lauf), GM-Regressions-Status, Dauer. Kein Log-File (OQ-CI-5).

.PARAMETER Verbose
  Zeigt die vollstaendige pytest-Ausgabe (Default: kompakt - nur Summary +
  bei Rot die fehlgeschlagenen Tests).

.EXAMPLE
  .\astra\scripts\ci.ps1
    -> Volles lokales CI-Gate (gruen/rot via Exit-Code)

.NOTES
  Version: 1.0 (V1.3-7)
  Abhaengigkeiten: Python >= 3.11 mit Extras dev + astroalign
   (die Umgebung, in der 767+0 verifiziert wurde); astra/pyproject.toml
   Gemessene Laufzeit (2026-08-08, 5 volle Laeufe, Python 3.12):
     Gesamtlauf 175-293 s (~3-5 min); Erstlauf 292,9 s, Wiederholungen
     175,5-201,9 s (Warmup/Maschinenlast). 767+0 Stand v1.5-Sprint-2.
    Ergebnis ist deterministisch (Exit 0) - nur die Dauer variiert.
  Hinweis: Datei ist bewusst ASCII-only (PS 5.1 parst .ps1 ohne BOM sonst als
  Windows-1252 und versteht mehrbyte-UTF-8-Zeichen falsch).
#>

param(
  [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$startTime = Get-Date

# -- Pfade -------------------------------------------------------------
$scriptDir = $PSScriptRoot                     # astra/scripts
$astraRoot = Split-Path -Parent $PSScriptRoot  # astra/ (Projekt-Wurzel mit pyproject.toml)
$python = "python"

# Dokumentierte Erwartung fuer den aktuellen Stand (Spec v13-astra-ci.md,
# R2/AC-CI-A1, aktualisiert v1.5-Sprint-1). Report-Zahl, KEIN Hard-Assert
# - Exit-Code ist das Kriterium.
# v1.2-Baseline: 449+1; aktueller Stand v1.5 (Sprint-2): 767+0.
$expectedPassed = 767
$expectedSkipped = 0

# Status-Tracking (script-scope, da in Funktionen gesetzt)
$script:exitCode = 0
$script:results = @()
$script:runPassed = $null
$script:runSkipped = $null
$script:gmStatus = "n/a"

# -- Helper: Schritt ausfuehren (Muster build-all.ps1 Run-Step) --------
function Run-Step {
  param([string]$Name, [scriptblock]$Block)

  Write-Host ""
  Write-Host "--- $Name ---" -ForegroundColor Yellow
  $stepStart = Get-Date

  & $Block

  $dur = (Get-Date) - $stepStart
  if ($script:exitCode -ne 0) {
    Write-Host "  [FAIL] $Name ($($dur.TotalSeconds.ToString('F1'))s)" -ForegroundColor Red
    $script:results += @{ Name = $Name; Status = "Failed"; Duration = $dur }
  } else {
    Write-Host "  [PASS] $Name ($($dur.TotalSeconds.ToString('F1'))s)" -ForegroundColor Green
    $script:results += @{ Name = $Name; Status = "Passed"; Duration = $dur }
  }
}

# =====================================================================
#  BANNER
# =====================================================================
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  astra CI-Gate (lokal, ADR-047) - V1.3-7" -ForegroundColor Cyan
Write-Host "  $($startTime.ToString('yyyy-MM-dd HH:mm'))" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

# =====================================================================
#  STEP 1: Env-Selbstcheck (OQ-CI-7)
# =====================================================================
Run-Step -Name "Env-Selbstcheck (Python >= 3.11 + pytest + astroalign)" -Block {
  # 1a: python im PATH?
  if (-not (Get-Command $python -ErrorAction SilentlyContinue)) {
    Write-Host "  [ENV] FEHLER: '$python' nicht im PATH gefunden." -ForegroundColor Red
    Write-Host "  [ENV] Bitte Python >= 3.11 installieren und das Skript mit der" -ForegroundColor Red
    Write-Host "  [ENV] Projekt-Umgebung ausfuehren (Extras: dev + astroalign)." -ForegroundColor Red
    $script:exitCode = 2
    return
  }

  # 1b: Python-Version >= 3.11
  $pyVer = (& $python --version 2>&1 | Out-String).Trim()
  if ($pyVer -match "Python\s+(\d+)\.(\d+)") {
    $pyMajor = [int]$Matches[1]
    $pyMinor = [int]$Matches[2]
  } else {
    Write-Host "  [ENV] FEHLER: Python-Version nicht lesbar: '$pyVer'" -ForegroundColor Red
    $script:exitCode = 2
    return
  }
  if (-not (($pyMajor -gt 3) -or ($pyMajor -eq 3 -and $pyMinor -ge 11))) {
    Write-Host "  [ENV] FEHLER: Python $pyMajor.$pyMinor - benoetigt >= 3.11." -ForegroundColor Red
    $script:exitCode = 2
    return
  }
  Write-Host "  -> Python $pyMajor.$pyMinor OK"

  # 1c: pytest-Modul (Extra dev)
  $pytestErr = (& $python -c "import pytest" 2>&1 | Out-String).Trim()
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ENV] FEHLER: pytest nicht installiert (Extra 'dev')." -ForegroundColor Red
    if ($pytestErr) { Write-Host "  $pytestErr" -ForegroundColor Red }
    Write-Host "  [ENV] Fix: pip install -e '.[dev,astroalign]' in astra/" -ForegroundColor Red
    $script:exitCode = 2
    return
  }

  # 1d: astroalign (Extra astroalign)
  $aaErr = (& $python -c "import astroalign" 2>&1 | Out-String).Trim()
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ENV] FEHLER: astroalign nicht installiert (Extra 'astroalign')." -ForegroundColor Red
    if ($aaErr) { Write-Host "  $aaErr" -ForegroundColor Red }
    Write-Host "  [ENV] Fix: pip install -e '.[dev,astroalign]' in astra/" -ForegroundColor Red
    $script:exitCode = 2
    return
  }
  Write-Host "  -> pytest + astroalign importierbar"
}

# =====================================================================
#  STEP 2: pytest-Gesamtlauf (testpaths = tests) + GM-Status-Ableitung
# =====================================================================
if ($script:exitCode -eq 0) {
  Run-Step -Name "pytest-Gesamtlauf (testpaths = tests, inkl. GM-Status)" -Block {
    Push-Location $astraRoot
    Write-Host "  pytest laeuft (767+0-Suite; Dauer wird im Summary gemessen) - Ergebnis folgt am Ende des Schritts ..."
    $output = @(& $python -m pytest 2>&1 | ForEach-Object { "$_" })
    $pyExit = $LASTEXITCODE
    Pop-Location

    $summaryLine = $output | Where-Object { $_ -match "passed|failed|error" } | Select-Object -Last 1

    if ($Verbose) {
      $output | ForEach-Object { Write-Host $_ }
    } elseif ($pyExit -eq 0) {
      if ($summaryLine) { Write-Host "  $summaryLine" }
    } else {
      $output | Where-Object { $_ -match "FAILED|ERROR" } | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
      Write-Host "  --- letzte Ausgabezeilen ---"
      $output | Select-Object -Last 25 | ForEach-Object { Write-Host "  $_" }
    }

    # Zaehlung aus tatsaechlichem Lauf ableiten (Report; Skip-Drift beachten:
    # bei vorhandenen M13-Referenzdaten entfaellt der Skip).
    $passed = 0; $skipped = 0; $failed = 0; $errors = 0
    if ($summaryLine -match "(\d+)\s+passed")  { $passed  = [int]$Matches[1] }
    if ($summaryLine -match "(\d+)\s+skipped") { $skipped = [int]$Matches[1] }
    if ($summaryLine -match "(\d+)\s+failed")  { $failed  = [int]$Matches[1] }
    if ($summaryLine -match "(\d+)\s+error")   { $errors  = [int]$Matches[1] }

    # GM-Regressions-Status aus dem Gesamtlauf ableiten (GM-Tests sind Teil
    # der Suite: test_quality_foundation.py, test_synthetic*.py). Gruen <=>
    # Gesamtlauf gruen (alle Tests, also auch GM-Tests, bestanden); bei Rot:
    # GM-rot nur, wenn eine GM-Testdatei fehlgeschlagen ist.
    $gmFailedLines = @($output | Where-Object { $_ -match "FAILED|ERROR" -and $_ -match "test_quality_foundation|test_synthetic" })

    if ($pyExit -ne 0) {
      Write-Host "  [GATE] pytest-Exit $pyExit - ROT" -ForegroundColor Red
      if ($failed -gt 0) { Write-Host "  [GATE] $failed Test(s) fehlgeschlagen" -ForegroundColor Red }
      if ($errors -gt 0) { Write-Host "  [GATE] $errors Fehler (Collection/Setup)" -ForegroundColor Red }
      if ($gmFailedLines.Count -gt 0) {
        $script:gmStatus = "rot"
        Write-Host "  [GATE] GM-Regression ROT - STOP -> Maintainer" -ForegroundColor Red
        Write-Host "  [GATE] GM Abs. 6.1: roter Test ist NIE Anlass fuer Erwartungswert-Anpassung." -ForegroundColor Red
      }
      # Report-Zaehlung aus dem tatsaechlichen Lauf (auch bei Rot; CI-D).
      $script:runPassed = $passed
      $script:runSkipped = $skipped
      $script:exitCode = $pyExit
      return
    }

    $script:gmStatus = "gruen"
    $script:runPassed = $passed
    $script:runSkipped = $skipped
    Write-Host "  -> Testergebnis: $passed passed, $skipped skipped" -ForegroundColor Cyan
    Write-Host "  -> GM-Regression negativ (gruen, aus Gesamtlauf abgeleitet)" -ForegroundColor Cyan
    if (($passed -ne $expectedPassed) -or ($skipped -ne $expectedSkipped)) {
      Write-Host "  -> Hinweis: Zaehlung weicht von der dokumentierten Erwartung" -ForegroundColor DarkYellow
      Write-Host "     ($expectedPassed passed + $expectedSkipped skipped) ab - Skip-Drift oder" -ForegroundColor DarkYellow
      Write-Host "     Test-Ergaenzung. Gate-Kriterium bleibt der Exit-Code (Report, kein Hard-Assert)." -ForegroundColor DarkYellow
    }
  }
}

# =====================================================================
#  SUMMARY (CI-D / AC-CI-A7 / AC-CI-D1)
# =====================================================================
$endTime = Get-Date
$total = ($endTime - $startTime).TotalSeconds

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  astra CI-Gate - SUMMARY (V1.3-7, lokal, ADR-047)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

foreach ($r in $script:results) {
  $icon = if ($r.Status -eq "Passed") { "[PASS]" } else { "[FAIL]" }
  $color = if ($r.Status -eq "Passed") { "Green" } else { "Red" }
  Write-Host "  $icon $($r.Name) -- $($r.Duration.TotalSeconds.ToString('F1'))s" -ForegroundColor $color
}

if ($null -ne $script:runPassed) {
  $testText = "$($script:runPassed) passed, $($script:runSkipped) skipped (Erwartung laut Spec: $expectedPassed + $expectedSkipped - Report, kein Hard-Assert)"
} else {
  $testText = "n/a (Abbruch vor pytest)"
}
if ($script:gmStatus -eq "gruen") {
  $gmText = "gruen (negativ, aus Gesamtlauf abgeleitet)"
} elseif ($script:gmStatus -eq "rot") {
  $gmText = "rot/STOP"
} else {
  $gmText = "n/a (Suite rot, keine GM-Test-Fehler)"
}
$statusText = if ($script:exitCode -eq 0) { "GRUEN (Exit 0)" } else { "ROT (Exit $($script:exitCode))" }
$statusColor = if ($script:exitCode -eq 0) { "Green" } else { "Red" }

Write-Host ""
Write-Host "  Testergebnis: $testText"
Write-Host "  GM-Regression: $gmText"
Write-Host "  Dauer: $($total.ToString('F1'))s"
Write-Host "  Status: $statusText" -ForegroundColor $statusColor
if ($script:exitCode -eq 0) {
  $machineStatus = "gruen"
} else {
  $machineStatus = "rot"
}
Write-Host "  Maschinenzeile: ASTRA-CI status=$machineStatus exit=$($script:exitCode) tests=$($script:runPassed)+$($script:runSkipped) expected=$expectedPassed+$expectedSkipped gm=$($script:gmStatus) duration=$($total.ToString('F1'))s"
Write-Host ""

exit $script:exitCode
