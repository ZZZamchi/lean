param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetPath,
    [string]$ApiBaseUrl = "https://api.ofox.ai/v1",
    [string]$ApiModel = "anthropic/claude-opus-4.7",
    [string]$ApiKeyEnv = "OPENAI_API_KEY",
    [string]$MathlibPath = "mathlib4",
    [string]$OutputPrefix = "results/prover/fate_h_v6_stable",
    [switch]$SkipTimeoutRerun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-CommandExists([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-PythonRun([string]$ProblemIds, [string]$OutDir, [int]$ApiTimeout, [int]$ApiRetries) {
    $args = @(
        "-u", "-m", "prover.run",
        "--dataset", $DatasetPath,
        "--problem-ids", $ProblemIds,
        "--backend", "openai_compat",
        "--api-base-url", $ApiBaseUrl,
        "--api-key-env", $ApiKeyEnv,
        "--api-model", $ApiModel,
        "--api-timeout-s", "$ApiTimeout",
        "--api-max-retries", "$ApiRetries",
        "--mathlib-path", $MathlibPath,
        "--strategies", "draft_formalize",
        "--draft-enable-sketch-first",
        "--draft-sketch-samples", "3",
        "--draft-min-sketch-lemmas", "3",
        "--draft-samples", "1",
        "--formalize-samples", "6",
        "--draft-rounds", "4",
        "--draft-repair-steps", "8",
        "--draft-sorry-candidates", "10",
        "--draft-feedback-chars", "3000",
        "--max-tokens", "4096",
        "--temperature", "0.15",
        "--verifier-timeout", "300",
        "--output-dir", $OutDir
    )

    Write-Host ">>> Running $OutDir"
    & python @args
}

function Get-TimeoutLikeIds([string]$ProofResultsPath) {
    if (-not (Test-Path $ProofResultsPath)) { return @() }
    $json = Get-Content $ProofResultsPath -Raw | ConvertFrom-Json
    $ids = @()
    foreach ($r in $json) {
        $attempts = 0
        if ($null -ne $r.attempts) { $attempts = [int]$r.attempts }
        if ($attempts -eq 0 -and $null -ne $r.problem_id -and "$($r.problem_id)".Length -gt 0) {
            $ids += "$($r.problem_id)"
        }
    }
    return $ids
}

if (-not (Test-CommandExists "python")) {
    throw "python is not available in PATH."
}

if (-not (Test-Path $DatasetPath)) {
    throw "Dataset not found: $DatasetPath"
}

if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($ApiKeyEnv))) {
    throw "Environment variable $ApiKeyEnv is empty. Set API key first."
}

$batches = @(
    @{ Start = 1; End = 20 },
    @{ Start = 21; End = 40 },
    @{ Start = 41; End = 60 },
    @{ Start = 61; End = 80 },
    @{ Start = 81; End = 100 }
)

foreach ($b in $batches) {
    $start = [int]$b.Start
    $end = [int]$b.End
    $ids = @()
    for ($i = $start; $i -le $end; $i++) { $ids += "FATE-H_$i" }
    $idsCsv = [string]::Join(",", $ids)

    $mainOut = "$OutputPrefix`_batch${start}_${end}"
    Invoke-PythonRun -ProblemIds $idsCsv -OutDir $mainOut -ApiTimeout 90 -ApiRetries 2

    if ($SkipTimeoutRerun) { continue }

    $mainProof = Join-Path $mainOut "proof_results.json"
    $timeoutIds = Get-TimeoutLikeIds -ProofResultsPath $mainProof
    if ($timeoutIds.Count -eq 0) {
        Write-Host "No timeout-like records for $mainOut"
        continue
    }

    $rerunOut = "$mainOut`_timeout_rerun"
    $rerunCsv = [string]::Join(",", $timeoutIds)
    Write-Host "Timeout-like rerun count: $($timeoutIds.Count)"
    Invoke-PythonRun -ProblemIds $rerunCsv -OutDir $rerunOut -ApiTimeout 120 -ApiRetries 3
}

Write-Host "All FATE-H batches finished."

