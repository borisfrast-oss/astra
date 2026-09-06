# wiki-publish.ps1 - GitHub Wiki publish for Astra (Handbook + Pipeline Docs)
# paige - Documentation Specialist, V19-1.10-WIKI
# Syncs astra/handbook (37 EN) + astra/docs (12) to GitHub Wiki (astra.wiki.git)
# GFM/Mermaid preserving, 2-menu _Sidebar.md + Home.md, no auto-push.
# Usage:
#   ./scripts/wiki-publish.ps1             # full sync
#   ./scripts/wiki-publish.ps1 -DryRun     # preview diff (PowerShell style)
#   ./scripts/wiki-publish.ps1 --dry-run   # preview diff (unix style, also supported)
#   ./scripts/wiki-publish.ps1 -Check      # validate only
#   ./scripts/wiki-publish.ps1 --check     # validate only
# Notes: UTF-8 without BOM, handles offline clone fallback, never pushes.

param(
    [switch]$DryRun,
    [switch]$Check,
    [string]$WikiDir = "",
    [string]$RemoteUrl = "https://github.com/borisfrast-oss/astra.wiki.git",
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$RemainingArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Support --dry-run / --check / --help via RemainingArgs (unix style)
if ($RemainingArgs) {
    foreach ($a in $RemainingArgs) {
        if ($a -eq "--dry-run") { $DryRun = $true }
        if ($a -eq "--check") { $Check = $true }
        if ($a -eq "--help" -or $a -eq "-h") { $Help = $true }
        if ($a -match "^--WikiDir=(.+)$") { $WikiDir = $Matches[1] }
        if ($a -match "^--RemoteUrl=(.+)$") { $RemoteUrl = $Matches[1] }
    }
}
# Also support single-dash aliases for convenience
if ($Help) {
    Write-Host @"
wiki-publish.ps1 - Astra GitHub Wiki sync
Usage:
  ./scripts/wiki-publish.ps1              # sync handbook+docs -> wiki/
  ./scripts/wiki-publish.ps1 -DryRun      # preview diff (no write)
  ./scripts/wiki-publish.ps1 --dry-run    # same (unix style)
  ./scripts/wiki-publish.ps1 -Check       # validate existing wiki
  ./scripts/wiki-publish.ps1 --check      # same
Options:
  -DryRun / --dry-run   Show what would be copied / _Sidebar diff (no writes)
  -Check / --check      Validate _Sidebar.md (37+12), no DE filenames, GFM fences
  -WikiDir <path>       Override wiki dir (default: astra/wiki)
  -RemoteUrl <url>      Git remote for clone (default: https://github.com/borisfrast-oss/astra.wiki.git)
Behavior:
  - WikiDir default: <repo>/wiki (clone RemoteUrl if missing, else pull --ff-only)
  - Copies handbook 01-37 and docs 01-12 to WikiDir root (GFM, mermaid preserved, UTF-8 no BOM)
  - Generates _Sidebar.md (2 menus) and Home.md (landing + Quickstart)
  - Validates counts, DE filenames, GFM fences
  - NEVER pushes (manual: git -C wiki push, Boris gated)
"@
    exit 0
}

# -- Resolve paths --
$ScriptRoot = $PSScriptRoot
if (-not $ScriptRoot) { $ScriptRoot = (Get-Location).Path }
$RepoRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$HandbookDir = Join-Path $RepoRoot "handbook"
$DocsDir = Join-Path $RepoRoot "docs"

if ([string]::IsNullOrWhiteSpace($WikiDir)) {
    $WikiDir = Join-Path $RepoRoot "wiki"
}
$AltWikiDir = Join-Path (Split-Path $RepoRoot -Parent) "astra.wiki"
if (-not (Test-Path -LiteralPath $WikiDir) -and (Test-Path -LiteralPath $AltWikiDir)) {
    $WikiDir = $AltWikiDir
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    $dir = Split-Path -Path $Path -Parent
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}
function Read-Utf8 {
    param([string]$Path)
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}
function Get-MarkdownTitle {
    param([string]$Path)
    try {
        $lines = [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8) | Select-Object -First 10
        foreach ($l in $lines) {
            if ($l -match '^\s*#\s+(.+)\s*$') {
                $t = $Matches[1].Trim()
                return $t
            }
        }
    } catch {}
    return [System.IO.Path]::GetFileNameWithoutExtension($Path)
}
function Get-PageSlug {
    param([string]$FileName)
    return [System.IO.Path]::GetFileNameWithoutExtension($FileName)
}
function Test-BalancedFences {
    param([string]$Content)
    $count = ([regex]::Matches($Content, '```')).Count
    return ($count % 2 -eq 0)
}

# -- Scan sources --
if (-not (Test-Path -LiteralPath $HandbookDir)) { Write-Error "Handbook dir not found: $HandbookDir"; exit 2 }
if (-not (Test-Path -LiteralPath $DocsDir)) { Write-Error "Docs dir not found: $DocsDir"; exit 2 }

$handbookFiles = Get-ChildItem -LiteralPath $HandbookDir -Filter "*.md" -File | Where-Object { $_.Name -match '^\d{2}-.+\.md$' } | Sort-Object Name
$docsFiles = Get-ChildItem -LiteralPath $DocsDir -Filter "*.md" -File | Where-Object { $_.Name -match '^\d{2}-.+\.md$' } | Sort-Object Name

Write-Host "Sources: handbook $($handbookFiles.Count)/37, docs $($docsFiles.Count)/12"
if ($handbookFiles.Count -ne 37) { Write-Warning "Handbook count !=37 (found $($handbookFiles.Count))" }
if ($docsFiles.Count -ne 12) { Write-Warning "Docs count !=12 (found $($docsFiles.Count))" }

# -- Wiki dir handling --
$wikiExisted = Test-Path -LiteralPath $WikiDir
$wikiIsGit = Test-Path -LiteralPath (Join-Path $WikiDir ".git")

if ($Check) {
    if (-not $wikiExisted) { Write-Error "CHECK: Wiki dir not found: $WikiDir (run without --check to create)"; exit 2 }
} elseif ($DryRun) {
    Write-Host "[dry-run] WikiDir: $WikiDir (existed=$wikiExisted, isGit=$wikiIsGit)"
    if (-not $wikiExisted) {
        Write-Host "[dry-run] Would create wiki dir and attempt: git clone $RemoteUrl $WikiDir"
        Write-Host "[dry-run] Offline fallback: create empty local wiki"
    } elseif ($wikiIsGit) {
        Write-Host "[dry-run] Would run: git -C `"$WikiDir`" pull --ff-only"
    }
} else {
    if (-not $wikiExisted) {
        Write-Host "Wiki dir not found - attempting clone: $RemoteUrl -> $WikiDir"
        $cloned = $false
        try {
            $out = git clone $RemoteUrl $WikiDir 2>&1
            Write-Host $out
            if ($LASTEXITCODE -eq 0) { $cloned = $true }
        } catch {
            Write-Warning "git clone failed: $_"
        }
        if (-not $cloned) {
            Write-Warning "Clone failed (offline or remote not reachable) - creating local wiki directory."
            New-Item -ItemType Directory -Path $WikiDir -Force | Out-Null
            try { git -C $WikiDir init 2>&1 | Out-Null } catch {}
            try { git -C $WikiDir remote add origin $RemoteUrl 2>&1 | Out-Null } catch {}
        }
    } else {
        if ($wikiIsGit) {
            Write-Host "Wiki git repo detected - pulling --ff-only..."
            try {
                $pull = git -C $WikiDir pull --ff-only 2>&1
                Write-Host $pull
                if ($LASTEXITCODE -ne 0) { Write-Warning "git pull non-zero (maybe offline) - continuing with local sync" }
            } catch {
                Write-Warning "git pull failed: $_"
            }
        } else {
            Write-Host "Wiki dir exists (no .git) - treating as local wiki (no pull)."
        }
    }
}

# -- Collect expected copies: handbook 01-37 + docs 01-12 to wiki root --
$expectedCopies = @()
foreach ($f in $handbookFiles) {
    $expectedCopies += @{ src = $f.FullName; dest = (Join-Path $WikiDir $f.Name); kind = "handbook" }
}
foreach ($f in $docsFiles) {
    $expectedCopies += @{ src = $f.FullName; dest = (Join-Path $WikiDir $f.Name); kind = "docs" }
}

# -- Dry-run: show diff --
if ($DryRun) {
    Write-Host ""
    Write-Host "=== DRY-RUN: file sync preview ==="
    $toAdd = 0; $toUpdate = 0; $toDelete = 0
    foreach ($c in $expectedCopies) {
        $src = $c.src; $dest = $c.dest
        if (-not (Test-Path -LiteralPath $dest)) {
            Write-Host "[ADD]    $($c.kind): $(Split-Path $src -Leaf) -> $(Split-Path $dest -Leaf)"
            $toAdd++
        } else {
            # Compare normalized source (LF + fence fix) vs actual wiki file
            $srcContent = Read-Utf8 $src
            $srcContent = $srcContent -replace "`r`n", "`n"
            if (-not $srcContent.EndsWith("`n")) { $srcContent += "`n" }
            if (-not (Test-BalancedFences $srcContent)) { $srcContent += '```' + "`n" }
            $dstContent = Read-Utf8 $dest
            # Hash via content to avoid file hash mismatch from BOM/LF
            $srcHash = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($srcContent))).Replace("-","").Substring(0,8)
            $dstHash = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($dstContent))).Replace("-","").Substring(0,8)
            if ($srcHash -ne $dstHash) {
                Write-Host "[UPDATE] $($c.kind): $(Split-Path $src -Leaf)  src:$srcHash dst:$dstHash"
                $toUpdate++
            }
        }
    }
    if (Test-Path -LiteralPath $WikiDir) {
        $existing = Get-ChildItem -LiteralPath $WikiDir -Filter "*.md" -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -notin @("_Sidebar.md","Home.md") }
        $expectedNames = @($expectedCopies | ForEach-Object { Split-Path $_.dest -Leaf })
        foreach ($e in $existing) {
            if ($e.Name -notin $expectedNames) {
                if ($e.Name -match '^\d{2}-') { Write-Host "[STALE]  wiki has extra: $($e.Name) (would keep, manual cleanup if needed)"; $toDelete++ }
            }
        }
    }
    Write-Host ""
    Write-Host "--- _Sidebar.md / Home.md preview ---"
    # Preview must match real generation (same header/content) for accurate dry-run
    $previewSidebar = @()
    $previewSidebar += "# Astra Wiki"
    $previewSidebar += ""
    $previewSidebar += "## Handbook"
    $previewSidebar += ""
    $previewSidebar += "_37 chapters - Dwarf mini + Siril 1.4.4 Best Practices_"
    $previewSidebar += ""
    foreach ($f in $handbookFiles) {
        $slug = Get-PageSlug $f.Name
        $title = Get-MarkdownTitle $f.FullName
        $previewSidebar += "- [$title]($slug)"
    }
    $previewSidebar += ""
    $previewSidebar += "## Pipeline Docs"
    $previewSidebar += ""
    $previewSidebar += "_12 docs - generated from code (SSOT), see docs/_"
    $previewSidebar += ""
    foreach ($f in $docsFiles) {
        $slug = Get-PageSlug $f.Name
        $title = Get-MarkdownTitle $f.FullName
        $previewSidebar += "- [$title]($slug)"
    }
    $previewSidebar += ""
    $previewSidebarText = $previewSidebar -join "`n"
    $sidebarPath = Join-Path $WikiDir "_Sidebar.md"
    if (Test-Path -LiteralPath $sidebarPath) {
        $existingSidebar = Read-Utf8 $sidebarPath
        if ($existingSidebar -ne ($previewSidebarText + "`n")) {
            Write-Host "[UPDATE] _Sidebar.md would be regenerated (37+12 links, 2 menus)"
            $existingLines = $existingSidebar -split "`n"
            $newLines = $previewSidebarText -split "`n"
            Write-Host "  existing: $($existingLines.Count) lines, new: $($newLines.Count) lines"
        } else {
            Write-Host "[OK]     _Sidebar.md up-to-date"
        }
    } else {
        Write-Host "[ADD]    _Sidebar.md (2 menus, 37+12 links)"
    }
    $homePath = Join-Path $WikiDir "Home.md"
    if (-not (Test-Path -LiteralPath $homePath)) { Write-Host "[ADD]    Home.md (landing)" } else { Write-Host "[CHECK]  Home.md exists" }
    Write-Host ""
    Write-Host "Summary: $toAdd to add, $toUpdate to update, _Sidebar/Home pending as above."
    Write-Host "No push - manual: git -C `"$WikiDir`" status ; git -C `"$WikiDir`" diff ; git -C `"$WikiDir`" push (after Boris approval)"
    Write-Host ""
    Write-Host "=== Validation preview ==="
    $dePattern = '(Einleitung|Grundlagen|Ueberblick|Anleitung|Handbuch|Fehler)'
    $deHits = @($expectedCopies | Where-Object { (Split-Path $_.src -Leaf) -match $dePattern })
    if ($deHits.Count -gt 0) { Write-Warning "DE filenames detected: $($deHits.Count)" } else { Write-Host "[OK] No DE filenames in sources (37+12 EN)" }
    $gfmIssues = 0
    foreach ($c in $expectedCopies) {
        $txt = Read-Utf8 $c.src
        if (-not (Test-BalancedFences $txt)) { Write-Host "[WARN] Unbalanced fences (auto-fixed on copy): $($c.src)"; $gfmIssues++ }
    }
    if ($gfmIssues -eq 0) { Write-Host "[OK] GFM fences balanced in all sources" } else { Write-Host "[INFO] $gfmIssues source(s) with unbalanced fences will be auto-closed for wiki GFM" }
    $mermaidSrc = 0; foreach ($c in $expectedCopies) { if ((Read-Utf8 $c.src) -match '```mermaid') { $mermaidSrc++ } }
    Write-Host "[INFO] Sources with mermaid blocks: $mermaidSrc (preserved verbatim on copy)"
    if ($toAdd -eq 0 -and $toUpdate -eq 0 -and (Test-Path -LiteralPath $sidebarPath) -and (Test-Path -LiteralPath $homePath)) {
        Write-Host ""
        Write-Host "DRY-RUN: Wiki up-to-date - nothing to push."
    } else {
        Write-Host ""
        Write-Host "DRY-RUN: Changes would be synced locally. Push gated - Boris approval required."
        Write-Host "To push after approval: git -C `"$WikiDir`" add -A ; git -C `"$WikiDir`" commit -m `"docs(wiki): sync handbook+docs 37+12`" ; git -C `"$WikiDir`" push"
    }
    exit 0
}

if ($Check) {
    Write-Host "=== CHECK: validating existing wiki at $WikiDir ==="
    $ok = $true
    $sidebarPath = Join-Path $WikiDir "_Sidebar.md"
    $homePath = Join-Path $WikiDir "Home.md"
    if (-not (Test-Path -LiteralPath $sidebarPath)) { Write-Error "Missing _Sidebar.md"; $ok = $false } else {
        $sb = Read-Utf8 $sidebarPath
        $totalLinks = ([regex]::Matches($sb, '\[.+?\]\(.+?\)')).Count
        Write-Host "Sidebar links total: $totalLinks (expect 49 = 37+12)"
        if ($totalLinks -lt 49) { Write-Warning "Sidebar has $totalLinks links, expected 49"; $ok = $false } else { Write-Host "[OK] Sidebar 49 links present" }
        if ($sb -notmatch 'Handbook' -or $sb -notmatch 'Pipeline Docs') { Write-Warning "Sidebar missing 2 menus headers"; $ok = $false } else { Write-Host "[OK] Sidebar has 2 menus: Handbook + Pipeline Docs" }
        if ($sb -match 'Einleitung|Grundlagen|Ueberblick') { Write-Warning "Sidebar contains DE filenames"; $ok = $false } else { Write-Host "[OK] No DE filenames in sidebar" }
    }
    if (-not (Test-Path -LiteralPath $homePath)) { Write-Error "Missing Home.md"; $ok = $false } else {
        $hm = Read-Utf8 $homePath
        if ($hm -notmatch 'Handbook' -or $hm -notmatch 'Pipeline Docs' -or $hm -notmatch 'Quickstart|quickstart') { Write-Warning "Home.md missing Handbook/Pipeline/Quickstart refs"; $ok = $false } else { Write-Host "[OK] Home.md references both menus + Quickstart" }
        Write-Host "[OK] Home.md exists"
    }
    $issues = 0
    foreach ($f in (Get-ChildItem -LiteralPath $WikiDir -Filter "*.md" -File -ErrorAction SilentlyContinue)) {
        $txt = Read-Utf8 $f.FullName
        if (-not (Test-BalancedFences $txt)) { Write-Warning "Unbalanced fences in wiki: $($f.Name)"; $issues++; $ok = $false }
        if ($f.Name -match '[äöüÄÖÜß]') { Write-Warning "DE filename in wiki: $($f.Name)"; $ok = $false }
    }
    if ($issues -eq 0) { Write-Host "[OK] GFM fences balanced in wiki" }
    $wikiPages = @(Get-ChildItem -LiteralPath $WikiDir -Filter "*.md" -File | Where-Object { $_.Name -notin @("Home.md","_Sidebar.md") -and $_.Name -match '^\d{2}-' })
    Write-Host "Wiki pages (numeric): $($wikiPages.Count) (expect 49)"
    if ($wikiPages.Count -ne 49) { Write-Warning "Wiki page count !=49"; $ok = $false } else { Write-Host "[OK] Wiki page count 49" }
    if ($ok) { Write-Host "CHECK PASSED"; exit 0 } else { Write-Error "CHECK FAILED"; exit 1 }
}

# -- Real sync: copy files + generate _Sidebar/Home --
Write-Host "Syncing sources -> $WikiDir ..."

foreach ($c in $expectedCopies) {
    $src = $c.src; $dest = $c.dest
    $content = Read-Utf8 $src
    $content = $content -replace "`r`n", "`n"
    if (-not $content.EndsWith("`n")) { $content += "`n" }
    # GFM fix: auto-close unbalanced fence at EOF (tolerate handbook single-open)
    if (-not (Test-BalancedFences $content)) {
        Write-Warning "GFM auto-fix: unbalanced fences in $(Split-Path $src -Leaf) - appending closing fence for wiki"
        $content += '```' + "`n"
    }
    Write-Utf8NoBom -Path $dest -Content $content
    Write-Host "  copied $($c.kind): $(Split-Path $src -Leaf)"
}

# Generate _Sidebar.md (2 menus)
$sidebarLines = @()
$sidebarLines += "# Astra Wiki"
$sidebarLines += ""
$sidebarLines += "## Handbook"
$sidebarLines += ""
$sidebarLines += "_37 chapters - Dwarf mini + Siril 1.4.4 Best Practices_"
$sidebarLines += ""
foreach ($f in $handbookFiles) {
    $slug = Get-PageSlug $f.Name
    $title = Get-MarkdownTitle $f.FullName
    $sidebarLines += "- [$title]($slug)"
}
$sidebarLines += ""
$sidebarLines += "## Pipeline Docs"
$sidebarLines += ""
$sidebarLines += "_12 docs - generated from code (SSOT), see docs/_"
$sidebarLines += ""
foreach ($f in $docsFiles) {
    $slug = Get-PageSlug $f.Name
    $title = Get-MarkdownTitle $f.FullName
    $sidebarLines += "- [$title]($slug)"
}
$sidebarLines += ""
$sidebarContent = ($sidebarLines -join "`n") + "`n"
$sidebarPath = Join-Path $WikiDir "_Sidebar.md"
Write-Utf8NoBom -Path $sidebarPath -Content $sidebarContent
Write-Host "Generated _Sidebar.md (Handbook 37 + Pipeline Docs 12 = 49 links, 2 menus)"

# Generate Home.md (landing)
$homeLines = @()
$homeLines += "# Astra Wiki - Home"
$homeLines += ""
$homeLines += "> **Astra** - Agentic Astrophotography Processing Pipeline for the DWARFLab Dwarf Mini."
$homeLines += "> 100% local, Python-native, deterministic. This wiki bundles two references:"
$homeLines += ""
$homeLines += "## Quickstart"
$homeLines += ""
$homeLines += "New here? Start with the pipeline quickstart:"
$homeLines += ""
$homeLines += "- **[Quickstart](01-quickstart)** - install, astra init, first astra process run"
$homeLines += "- [CLI Reference](03-cli-reference) - all subcommands and flags"
$homeLines += "- [Configuration](04-configuration) - layered config, presets, env"
$homeLines += ""
$homeLines += "## Handbook (Dwarf mini + Siril 1.4.4)"
$homeLines += ""
$homeLines += "37 chapters covering acquisition, target-specific workflows, and post-processing."
$homeLines += "Browse via the sidebar **Handbook** menu:"
$homeLines += ""
$homeLines += "- **Fundamentals:** [Introduction](01-Introduction) | [Fundamentals](02-Fundamentals) | [Dwarf mini Best Practices](03-Dwarf-mini-Best-Practices) | [Siril Reference](04-Siril-Reference)"
$homeLines += "- **Target workflows:** [Galaxies](05-Galaxies) | [Emission Nebulae](06-Emission-Nebulae) | [Reflection Nebulae](07-Reflection-Nebulae) | [Planetary Nebulae](08-Planetary-Nebulae) | [Globular Clusters](09-Globular-Clusters) | [Open Clusters](10-Open-Clusters) | [Stars and Star Fields](11-Stars-and-Star-Fields) | [Moon and Planets](12-Moon-and-Planets) and more (05-16)"
$homeLines += "- **Processing:** [Multiple Exposures and HDR](17-Multiple-Exposures-and-HDR) | [Mosaics and Panoramas](18-Mosaics-and-Panoramas) | [Color Calibration and Final Processing](19-Color-Calibration-and-Final-Processing)"
$homeLines += "- **Practice & Reference:** [Siril Workflow Decision Tree](22-Siril-Workflow-Decision-Tree) | [Troubleshooting](23-Siril-Troubleshooting) | [Siril Command Quick Reference](37-Siril-Command-Quick-Reference) | all 37 in sidebar"
$homeLines += ""
$homeLines += "See also: [_Sidebar Handbook section](_Sidebar) for the full 37-chapter list."
$homeLines += ""
$homeLines += "## Pipeline Docs (Technical)"
$homeLines += ""
$homeLines += "12 auto-generated docs from the code (SSOT src/ + scripts/generate_docs.py):"
$homeLines += ""
$homeLines += "- [Quickstart](01-quickstart) | [Pipeline Architecture](02-pipeline-architecture) | [CLI Reference](03-cli-reference) | [Configuration](04-configuration)"
$homeLines += "- [Presets](05-presets) | [Multi-Group](06-multi-group) | [Registration](07-registration) | [Gradient Removal](08-gradient-removal)"
$homeLines += "- [Darks Library](09-darks-library) | [Output Structure](10-output-structure) | [Troubleshooting](11-troubleshooting) | [Migration](12-migration)"
$homeLines += ""
$homeLines += "Browse via the sidebar **Pipeline Docs** menu or start at [Quickstart](01-quickstart)."
$homeLines += ""
$homeLines += "## Source vs Wiki"
$homeLines += ""
$homeLines += "- **Sources (SSOT):** astra/handbook/ (37 EN chapters) + astra/docs/ (12 generated docs)"
$homeLines += "- **This wiki:** GitHub Wiki at https://github.com/borisfrast-oss/astra/wiki (repo astra.wiki.git)"
$homeLines += "- **Mermaid diagrams** are preserved as mermaid blocks and render natively on GitHub."
$homeLines += "- **GFM** compatible - all pages are plain Markdown with GitHub Flavored Markdown tables, code fences, and links."
$homeLines += ""
$homeLines += "## Contributing"
$homeLines += ""
$homeLines += "Wiki content is generated - edit the sources, not the wiki directly:"
$homeLines += ""
$homeLines += '```bash'
$homeLines += "# edit handbook or code, then regenerate docs if needed"
$homeLines += "python scripts/generate_docs.py all"
$homeLines += "# sync to local wiki"
$homeLines += "powershell ./scripts/wiki-publish.ps1"
$homeLines += "# preview diff"
$homeLines += "powershell ./scripts/wiki-publish.ps1 --dry-run"
$homeLines += "# validate"
$homeLines += "powershell ./scripts/wiki-publish.ps1 --check"
$homeLines += '```'
$homeLines += ""
$homeLines += "> **No auto-push** - this script never pushes. After validation, Boris gates push:"
$homeLines += "> git -C wiki status -> git -C wiki diff -> git -C wiki push (only after Quality-Gate approval)."
$homeLines += ""
$homeContent = ($homeLines -join "`n") + "`n"
$homePath = Join-Path $WikiDir "Home.md"
Write-Utf8NoBom -Path $homePath -Content $homeContent
Write-Host "Generated Home.md (landing, both menus + Quickstart)"

# -- Validation --
Write-Host ""
Write-Host "=== Validation ==="
$valid = $true
$sbText = Read-Utf8 $sidebarPath
$linkCount = ([regex]::Matches($sbText, '\[.+?\]\(.+?\)')).Count
Write-Host "Sidebar links: $linkCount (expect 49)"
if ($linkCount -ne 49) { Write-Warning "Sidebar link count !=49"; $valid = $false } else { Write-Host "[OK] Sidebar 49 links" }
if ($sbText -notmatch '## Handbook' -or $sbText -notmatch '## Pipeline Docs') { Write-Warning "Sidebar missing 2 menu headers"; $valid = $false } else { Write-Host "[OK] Sidebar 2 menus present" }
try {
    $handbookSection = ($sbText -split '## Pipeline Docs')[0]
    $docsSection = ($sbText -split '## Pipeline Docs')[1]
    $hbLinks = ([regex]::Matches($handbookSection, '\[.+?\]\(.+?\)')).Count
    $docLinks = ([regex]::Matches($docsSection, '\[.+?\]\(.+?\)')).Count
    Write-Host "  Handbook links in sidebar: $hbLinks (expect 37)"
    Write-Host "  Pipeline Docs links: $docLinks (expect 12)"
    if ($hbLinks -ne 37) { Write-Warning "Handbook links !=37"; $valid = $false } else { Write-Host "[OK] Handbook 37" }
    if ($docLinks -ne 12) { Write-Warning "Docs links !=12"; $valid = $false } else { Write-Host "[OK] Pipeline Docs 12" }
} catch { Write-Warning "Could not split sidebar for per-menu counts: $_" }
$deHits = 0
foreach ($f in $handbookFiles) { if ($f.Name -match 'Einleitung|Grundlagen|Ueberblick|Anleitung|Handbuch|Fehler') { $deHits++ } }
foreach ($f in $docsFiles) { if ($f.Name -match 'Einleitung|Grundlagen') { $deHits++ } }
if ($deHits -gt 0) { Write-Warning "DE filenames detected: $deHits"; $valid = $false } else { Write-Host "[OK] No DE filenames (EN only)" }
if ($sbText -match 'Einleitung|Grundlagen') { Write-Warning "DE filename in _Sidebar.md"; $valid = $false } else { Write-Host "[OK] Sidebar no DE filenames" }
$gfmBad = 0
foreach ($f in (Get-ChildItem -LiteralPath $WikiDir -Filter "*.md" -File)) {
    $t = Read-Utf8 $f.FullName
    if (-not (Test-BalancedFences $t)) { Write-Host "[WARN] Unbalanced fences (should be auto-fixed): $($f.Name)"; $gfmBad++ }
}
if ($gfmBad -eq 0) { Write-Host "[OK] GFM fences balanced (all wiki .md)" } else { Write-Host "[INFO] Wiki GFM auto-fix ensures balanced fences on next sync" }
$mermaidSrc = 0; $mermaidWiki = 0
foreach ($c in $expectedCopies) { if ((Read-Utf8 $c.src) -match '```mermaid') { $mermaidSrc++ } }
foreach ($f in (Get-ChildItem -LiteralPath $WikiDir -Filter "*.md" -File)) { if ((Read-Utf8 $f.FullName) -match '```mermaid') { $mermaidWiki++ } }
Write-Host "Mermaid blocks - src: $mermaidSrc, wiki: $mermaidWiki (preserved verbatim)"
if ($mermaidSrc -ne $mermaidWiki) { Write-Warning "Mermaid block count mismatch (src $mermaidSrc vs wiki $mermaidWiki)" } else { Write-Host "[OK] Mermaid preserved" }
$bomFound = 0
foreach ($f in (Get-ChildItem -LiteralPath $WikiDir -Filter "*.md" -File)) {
    $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { Write-Warning "BOM found: $($f.Name)"; $bomFound++; $valid = $false }
}
if ($bomFound -eq 0) { Write-Host "[OK] UTF-8 without BOM (all wiki .md)" }
$wikiPages = @(Get-ChildItem -LiteralPath $WikiDir -Filter "*.md" -File | Where-Object { $_.Name -notin @("Home.md","_Sidebar.md") -and $_.Name -match '^\d{2}-' })
Write-Host "Wiki numeric pages: $($wikiPages.Count) (expect 49 = 37+12)"
if ($wikiPages.Count -ne 49) { Write-Warning "Wiki page count mismatch"; $valid = $false } else { Write-Host "[OK] Wiki page count 49" }
$hmText = Read-Utf8 $homePath
if ($hmText -notmatch 'Handbook' -or $hmText -notmatch 'Pipeline Docs' -or $hmText -notmatch 'Quickstart') { Write-Warning "Home.md missing menu/Quickstart refs"; $valid = $false } else { Write-Host "[OK] Home.md has both menus + Quickstart" }
Write-Host ""
if ($valid) { Write-Host "VALIDATION PASSED - wiki ready, no push." } else { Write-Warning "VALIDATION ISSUES - see warnings above." }
Write-Host ""
Write-Host "Done. WikiDir: $WikiDir"
Write-Host "Next (gated, Boris):"
Write-Host "  git -C `"$WikiDir`" status"
Write-Host "  git -C `"$WikiDir`" diff --stat"
Write-Host "  # after Quality-Gate approval:"
Write-Host "  git -C `"$WikiDir`" add -A ; git -C `"$WikiDir`" commit -m `"docs(wiki): sync handbook 37 + docs 12`"; git -C `"$WikiDir`" push"
Write-Host "  # (no auto-push by this script - Publish-Sperre until 1.10 Quality-Gate)"
if (-not $valid) { exit 1 } else { exit 0 }
