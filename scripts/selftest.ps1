# thinkstack: validate an INSTALLED build. Windows.
#
# Mirror of scripts/selftest.sh. Run with ThinkStack already open:
#
#   powershell -ExecutionPolicy Bypass -File selftest.ps1
#
# It checks what has actually broken in shipped builds -- that the backend is
# reachable, that the BUNDLED backend launched (never a system python), that the
# model resolved to a real file, that the embedding model came from inside the
# bundle rather than HuggingFace, and that pdflatex exists for the paper
# writer's PDF tab. Prints a report to paste into a bug thread; uploads nothing.

$ErrorActionPreference = 'Continue'
$api = 'http://127.0.0.1:8000'
$script:pass = 0; $script:fail = 0; $script:warn = 0

function Ok($m)   { Write-Host "  PASS  $m" -ForegroundColor Green;  $script:pass++ }
function Bad($m)  { Write-Host "  FAIL  $m" -ForegroundColor Red;    $script:fail++ }
function Warn($m) { Write-Host "  WARN  $m" -ForegroundColor Yellow; $script:warn++ }
function Info($m) { Write-Host "        $m" -ForegroundColor DarkGray }
function Head($m) { Write-Host ""; Write-Host $m -ForegroundColor Cyan }

$logDir = Join-Path $env:LOCALAPPDATA 'com.thinkstack.app\logs'
$log    = Join-Path $logDir 'backend.log'
$osName = (Get-CimInstance Win32_OperatingSystem).Caption

Write-Host "────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  ThinkStack self-test" -ForegroundColor Cyan
Write-Host "  $osName  |  $env:PROCESSOR_ARCHITECTURE"
Write-Host "────────────────────────────────────────────" -ForegroundColor Cyan

# -- 1. backend --
Head "[1] backend"
try {
    $health = Invoke-RestMethod -Uri "$api/api/system/health" -TimeoutSec 10
    Ok "backend reachable"
} catch {
    Bad "no backend on 127.0.0.1:8000"
    Info "Start ThinkStack first, wait for the window, then re-run this."
    Info "If it never finishes starting, the loading screen shows a log path --"
    Info "send that file."
    Write-Host ""
    Write-Host "  Cannot continue without a running app." -ForegroundColor Red
    exit 1
}

# -- 2. which backend launched --
Head "[2] startup"
if (Test-Path $log) {
    Ok "startup log: $log"
    $lines = Get-Content $log -ErrorAction SilentlyContinue
    $spawn = $lines | Select-String 'spawn: Backend:' | Select-Object -First 1
    if ($spawn) {
        Info ($spawn.Line -replace '.*spawn: ', '')
        Ok "launched the bundled backend"
    } elseif ($lines | Select-String 'falling back to a system python') {
        Bad "fell back to a SYSTEM PYTHON -- the bundled backend was not found"
        Info "This is the v1.0.0 bug on a new platform. Send the log."
    } else {
        Warn "could not tell which backend launched (older build?)"
    }
    $ready = $lines | Select-String 'ready: Engine ready' | Select-Object -First 1
    if ($ready) { Info ($ready.Line -replace '^\[\s*', 'ready at ' -replace 'ms\].*', 'ms') }
} else {
    Warn "no startup log at $log"
    Info "Expected on builds older than v1.0.1."
}

# -- 3. hardware --
Head "[3] hardware diagnosis"
$hw = $health.hardware
if ($hw -and $hw.total_ram_gb -gt 0) {
    Ok ("detected: {0} GB RAM, tier '{1}', gpu '{2}'" -f $hw.total_ram_gb, $hw.tier, $hw.gpu)
    Info "GPU is reported but NOT used: the shipped llama.cpp is CPU-only, so"
    Info "offload would crash at model load. CPU is expected here."
} else {
    Bad "hardware not detected"
}

# -- 4. language model --
Head "[4] language model"
$llm = $health.llm
if ($llm.status -eq 'connected' -and $llm.target_available) {
    Ok ("model resolved ({0} available)" -f $llm.models_available)
    Info $llm.model_path
} else {
    Bad ("model NOT resolved (status='{0}', available='{1}')" -f $llm.status, $llm.target_available)
    Info "path it looked at: $($llm.model_path)"
    Info "If that path looks relative or wrong, this is the model-path bug."
}

# -- 5. embedding model --
Head "[5] embedding model"
if (Test-Path $log) {
    $emb = Get-Content $log | Select-String 'loading embedding model' | Select-Object -First 1
    if ($emb) {
        $src = ($emb.Line -replace '.*loading embedding model: ', '')
        if ($src -match '^[A-Za-z]:\\|^/') {
            Ok "loaded from a real path (bundled)"; Info $src
        } else {
            Bad "resolved to a BARE NAME -- it will try HuggingFace"; Info $src
        }
    } else {
        Warn "not loaded yet -- ingest one PDF, then re-run this"
        Info "That is the only action that exercises the embedding model."
    }
} else {
    Warn "no log to check"
}

# -- 6. pdflatex --
Head "[6] paper writer"
$tex = Get-Command pdflatex -ErrorAction SilentlyContinue
if ($tex) {
    Ok "pdflatex found: $($tex.Source)"
} else {
    Warn "pdflatex NOT installed -- the live preview works, the PDF tab will not"
    Info "install MiKTeX (https://miktex.org) or TeX Live, then reopen ThinkStack"
    Info "ThinkStack does not bundle a TeX engine yet (roadmap: Tectonic)."
}

# -- 7. model setup --
Head "[7] model setup"
try {
    $setup = Invoke-RestMethod -Uri "$api/api/models/setup" -TimeoutSec 10
    $sugg = if ($setup.suggested_upgrade) { $setup.suggested_upgrade.name } else { 'none' }
    Ok ("reachable (needs_permission={0}, suggests={1})" -f $setup.needs_permission, $sugg)
} catch {
    Bad "/api/models/setup did not respond"
}

# -- summary --
Write-Host ""
Write-Host "────────────────────────────────────────────" -ForegroundColor Cyan
if ($script:fail -eq 0) {
    Write-Host "  $($script:pass) passed, $($script:warn) warning(s), 0 failed" -ForegroundColor Green
    Write-Host "  This build works on $osName."
} else {
    Write-Host "  $($script:fail) FAILED, $($script:warn) warning(s), $($script:pass) passed" -ForegroundColor Red
    Write-Host "  Paste this output and $log into the bug thread."
}
Write-Host "────────────────────────────────────────────" -ForegroundColor Cyan
if ($script:fail -gt 0) { exit 1 }
