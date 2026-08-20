<#
.SYNOPSIS
    Ralph-style outer loop around the classifier prompt, with an honest ruler.

.DESCRIPTION
    Re-invokes a fresh `claude -p` on the frozen `loop/PROMPT_optimize.md`
    once per iteration. The agent edits the classifier system prompt. The
    script grades the edit with `scripts/loop_metrics.py`, which shows the
    agent split A only and keeps splits B and C in a ledger outside the
    worktree. An iteration is committed only if the hidden B gate passes.

    Every rail in agent-ops ADR-016 is implemented here, in the script,
    not in the prompt:

      1. -MaxIterations           iteration cap
      2. -BudgetUsd / -MaxMinutes budget and time caps
      3. both caps live here, at the call site, not in the prompt
      4. stuck detection: 3 identical failure signatures halt the run and
         write loop/state/stuck.json
      5. worktree isolation: refuses to run in the main working tree
      6. pushes to the loop branch only, never to main
      7. no permission-bypass flag: the run refuses if one is passed
      8. blast radius: a change outside loop/blast-radius.txt halts the run

    The loop never merges and never opens a pull request. Under ADR-016 a
    loop does not inherit the standing merge authorization: it accumulates
    commits on its own branch for a human to review.

.EXAMPLE
    # Smoke test: two iterations, zero-API scoring.
    pwsh loop/loop.ps1 -MaxIterations 2 -DryRunMetrics

.EXAMPLE
    # A real run, still bounded.
    pwsh loop/loop.ps1 -MaxIterations 5 -BudgetUsd 5.00 -MaxMinutes 90
#>
[CmdletBinding()]
param(
    # Rail 1: the iteration cap. Deliberately small by default.
    [int]$MaxIterations = 3,

    # Rail 2: spend cap, in US dollars, summed from each `claude -p` result.
    [double]$BudgetUsd = 2.00,

    # Rail 2: wall-clock cap. The backstop for any spend the loop cannot see.
    [int]$MaxMinutes = 60,

    # Rail 6: the branch every commit and push goes to. Never main.
    [string]$Branch = "loop/prompt-optimize",

    # Model tier for the agent. Sonnet is the SYS-002 default.
    [string]$Model = "sonnet",

    # The agent command. Only reason to change it: substituting a
    # deterministic stub so a rail can be exercised without spending budget.
    # See loop/fixtures/stuck-agent.ps1.
    [string]$AgentCommand = "claude",

    # Score with the zero-API mock backend. Use this for a smoke test.
    [switch]$DryRunMetrics,

    # Skip the worktree check. For a deliberate, supervised smoke test only.
    [switch]$AllowSharedTree,

    # Keep the run local. Rail 6 is "never push to main", which this does not
    # weaken: the loop still commits to its own branch and merges nothing.
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $RepoRoot "loop/state"
$PromptFile = Join-Path $RepoRoot "loop/PROMPT_optimize.md"
$BlastFile = Join-Path $RepoRoot "loop/blast-radius.txt"
$StatusFile = Join-Path $StateDir "status.md"
$StuckFile = Join-Path $StateDir "stuck.json"
$LogFile = Join-Path $StateDir "log.md"
$SIGIL = "LOOP-COMPLETE:"

function Write-Step {
    <#
    .SYNOPSIS
        Print one loop-level status line.
    #>
    param([string]$Message)
    Write-Host "[loop] $Message"
}

function Stop-Loop {
    <#
    .SYNOPSIS
        Halt the run, record why, and exit non-zero.
    #>
    param([string]$Reason, [int]$Code = 2)
    Write-Step "HALT: $Reason"
    exit $Code
}

# --- Rail 7: no permission-bypass flag ------------------------------------
# A bypass flag is a fleet redline (agent-ops ADR-012), and a loop is the
# worst place to remove a guard: it repeats the blocked action instead of
# reconsidering it. The check is here so the refusal is mechanical.
$forbidden = @("dangerously-skip-permissions", "bypassPermissions")
$invocation = @([Environment]::GetCommandLineArgs()) + @($MyInvocation.Line) -join " "
foreach ($flag in $forbidden) {
    if ($invocation -match [regex]::Escape($flag)) {
        Stop-Loop "refusing to run: '$flag' is a permission-bypass flag (ADR-016 rail 7)."
    }
}
if ($env:CLAUDE_CODE_PERMISSION_MODE -eq "bypassPermissions") {
    Stop-Loop "refusing to run: the environment sets bypassPermissions (ADR-016 rail 7)."
}

# --- Rail 5: worktree isolation -------------------------------------------
$gitDir = (git -C $RepoRoot rev-parse --git-dir).Trim()
$commonDir = (git -C $RepoRoot rev-parse --git-common-dir).Trim()
if ($gitDir -eq $commonDir -and -not $AllowSharedTree) {
    Stop-Loop @"
this is the main working tree, not a git worktree (ADR-016 rail 5).
A loop that shares a tree with a live session stages that session's
uncommitted work. Create one first:
  git -C "$RepoRoot" worktree add ../dnc-loop -b $Branch
then run this script from inside that worktree.
Pass -AllowSharedTree only for a supervised smoke test.
"@
}

# --- Rail 6: the loop branch, never main ----------------------------------
$current = (git -C $RepoRoot rev-parse --abbrev-ref HEAD).Trim()
if ($current -eq "main" -or $current -eq "master") {
    Stop-Loop "refusing to run on '$current' (ADR-016 rail 6). Check out $Branch first."
}
if ($current -ne $Branch) {
    Write-Step "note: on branch '$current', not '$Branch'. Commits go to '$current'."
    $Branch = $current
}

# The tree must be clean, or the first iteration's diff is not the agent's.
$dirty = git -C $RepoRoot status --porcelain
if ($dirty) {
    Stop-Loop "the working tree is dirty. Commit or stash first, then re-run."
}

# --- the ledger lives OUTSIDE the worktree --------------------------------
# This is what keeps the hidden B and C scores off the agent's disk during
# the run. It is copied into evals/loop/ after the last iteration.
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$LedgerDir = Join-Path ([System.IO.Path]::GetTempPath()) "dnc-loop"
New-Item -ItemType Directory -Force -Path $LedgerDir | Out-Null
$Ledger = Join-Path $LedgerDir "ledger_$stamp.jsonl"
$env:LOOP_LEDGER = $Ledger

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
if (-not (Test-Path $LogFile)) {
    Set-Content -Path $LogFile -Value "# Iteration log`n" -Encoding utf8
}
if (Test-Path $StatusFile) { Remove-Item $StatusFile }
if (Test-Path $StuckFile) { Remove-Item $StuckFile }

# --- blast radius, declared before iteration 1 ----------------------------
$blast = @(Get-Content $BlastFile |
    Where-Object { $_.Trim() -and -not $_.TrimStart().StartsWith("#") } |
    ForEach-Object { $_.Trim() })
if (-not $blast) { Stop-Loop "loop/blast-radius.txt declares no files." }

function Test-InBlastRadius {
    <#
    .SYNOPSIS
        Is a repo-relative path inside the declared blast radius?
    #>
    param([string]$Path)
    foreach ($entry in $blast) {
        if ($entry.EndsWith("/")) {
            if ($Path.StartsWith($entry)) { return $true }
        }
        elseif ($Path -eq $entry) { return $true }
    }
    return $false
}

function Invoke-Metrics {
    <#
    .SYNOPSIS
        Run the honest ruler and return its exit code.
    #>
    param([string]$Mode)
    $metricsArgs = @("run", "python", "scripts/loop_metrics.py", "--mode", $Mode,
        "--ledger", $Ledger)
    if ($DryRunMetrics) { $metricsArgs += "--dry-run" }
    # A worktree has no .env, so a global UV_ENV_FILE fails every uv call on
    # the missing file. The ruler never needs the file: dry-run scoring needs
    # no key, and a real run reads ANTHROPIC_API_KEY from the process
    # environment (HANDOFF job 5). Caught live 2026-08-19: this removal was
    # dry-run-only, and the first real run halted at baseline scoring.
    $savedEnvFile = $env:UV_ENV_FILE
    # Removing the variable is not the same as setting it to the empty string:
    # an empty value makes uv look for a file named "" and fail.
    if (Test-Path Env:UV_ENV_FILE) { Remove-Item Env:UV_ENV_FILE }
    Push-Location $RepoRoot
    # Out-Host, not a bare call: a bare `& uv` writes its stdout to the
    # function's output stream, so the caller receives the console text AND
    # the exit code as one array, and every comparison against 0 is wrong.
    try { & uv @metricsArgs | Out-Host; return $LASTEXITCODE }
    finally {
        Pop-Location
        if ($null -ne $savedEnvFile) { $env:UV_ENV_FILE = $savedEnvFile }
    }
}

# --- baseline -------------------------------------------------------------
Write-Step "config: max=$MaxIterations iterations, budget=`$$BudgetUsd, cap=$MaxMinutes min, branch=$Branch"
Write-Step "ledger (outside the worktree): $Ledger"
Write-Step "scoring the starting prompt"
if ((Invoke-Metrics -Mode "baseline") -ne 0) { Stop-Loop "the baseline scoring run failed." }

$deadline = (Get-Date).AddMinutes($MaxMinutes)
$spent = 0.0
$signatures = @()
$accepted = 0
$stopReason = "iteration cap reached"

for ($i = 1; $i -le $MaxIterations; $i++) {
    # --- Rail 2: the caps, checked here, before spending anything ---------
    if ((Get-Date) -gt $deadline) { $stopReason = "time cap reached"; break }
    if ($spent -ge $BudgetUsd) { $stopReason = "budget cap reached"; break }

    Write-Step "iteration $i of $MaxIterations (spent so far: `$$([math]::Round($spent,4)))"

    # --- a FRESH agent, under normal permissions, on the frozen prompt ----
    $prompt = Get-Content $PromptFile -Raw
    Push-Location $RepoRoot
    try {
        $raw = $prompt | & $AgentCommand -p --model $Model --output-format json
    }
    finally { Pop-Location }

    if ($LASTEXITCODE -ne 0) { Stop-Loop "the agent invocation failed (exit $LASTEXITCODE)." }

    # `total_cost_usd` is what makes the budget cap real rather than a
    # wall-clock guess. If the field is absent the time cap still binds.
    try {
        $result = $raw | ConvertFrom-Json
        if ($result.PSObject.Properties.Name -contains "total_cost_usd") {
            $spent += [double]$result.total_cost_usd
        }
    }
    catch { Write-Step "note: could not parse the agent result as JSON; the time cap still applies." }

    # --- Rail 8: blast radius, before anything else ----------------------
    $changed = @(git -C $RepoRoot status --porcelain |
        ForEach-Object { $_.Substring(3).Trim().Trim('"') })
    $outside = @($changed | Where-Object { -not (Test-InBlastRadius $_) })
    if ($outside) {
        git -C $RepoRoot checkout -- . 2>$null
        Stop-Loop "iteration $i changed files outside the blast radius: $($outside -join ', ') (ADR-016 rail 8)."
    }
    if (-not $changed) {
        Write-Step "iteration $i changed nothing."
    }

    # --- the honest ruler -------------------------------------------------
    $code = Invoke-Metrics -Mode "check"
    $diff = (git -C $RepoRoot diff) -join "`n"
    $diffHash = if ($diff) {
        (Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($diff))) -Algorithm SHA256).Hash.Substring(0, 16)
    }
    else { "empty" }

    if ($code -eq 0) {
        if ($changed) {
            git -C $RepoRoot add -- src/classify.py
            git -C $RepoRoot commit -m "loop(iter ${i}): accepted -- hidden validation gate passed" | Out-Null
            Write-Step "iteration ${i}: ACCEPTED, committed"
            $accepted++
        }
        else {
            Write-Step "iteration ${i}: nothing to accept, no edit was made"
        }
        $signatures = @()
    }
    else {
        $gate = switch ($code) {
            3 { "b_regression" }
            4 { "region_rubric" }
            default { "metrics_error_$code" }
        }
        Write-Step "iteration ${i}: REJECTED ($gate), reverting the edit"
        # Revert the prompt but keep loop/state/, so the next iteration reads
        # why this one was rejected without inheriting the edit that failed.
        # Nothing is committed: a rejected iteration leaves no commit, and its
        # full record is in the ledger.
        git -C $RepoRoot checkout -- src/classify.py 2>$null

        # --- Rail 4: stuck detection --------------------------------------
        $signatures += "${gate}:${diffHash}"
        if ($signatures.Count -ge 3) {
            $last3 = @($signatures[-3..-1])
            # @() around the pipeline: three identical strings collapse to one
            # scalar, which has no .Count under Set-StrictMode.
            if (@($last3 | Select-Object -Unique).Count -eq 1) {
                $state = [ordered]@{
                    halted_at = (Get-Date).ToUniversalTime().ToString("o")
                    reason    = "three consecutive identical failures"
                    iteration = $i
                    branch    = $Branch
                    gate      = $gate
                    signature = $last3[0]
                    command   = "uv run python scripts/loop_metrics.py --mode check"
                    ledger    = $Ledger
                }
                $state | ConvertTo-Json | Set-Content -Path $StuckFile -Encoding utf8
                Copy-Item $Ledger (Join-Path $RepoRoot "loop/state/ledger_at_halt.jsonl")
                Stop-Loop "stuck: the same failure three times. See loop/state/stuck.json (ADR-016 rail 4)."
            }
        }
    }

    # --- the completion sigil --------------------------------------------
    if ((Test-Path $StatusFile) -and (Select-String -Path $StatusFile -SimpleMatch $SIGIL -Quiet)) {
        $stopReason = "the agent wrote $SIGIL"
        break
    }
}

# --- publish the ledger as the run's evidence -----------------------------
$evalDir = Join-Path $RepoRoot "evals/loop"
New-Item -ItemType Directory -Force -Path $evalDir | Out-Null
Copy-Item $Ledger (Join-Path $evalDir "run_$stamp.jsonl")

Write-Step "stopped: $stopReason"
Write-Step "$accepted of $MaxIterations iterations accepted"
Write-Step "run log: evals/loop/run_$stamp.jsonl"

# --- Rail 6: push to the loop branch only ---------------------------------
if ($NoPush) {
    Write-Step "-NoPush: the run stays local. Nothing was merged (ADR-016)."
}
else {
    Write-Step "pushing $Branch (the loop opens no pull request and merges nothing -- ADR-016)"
    git -C $RepoRoot push -u origin $Branch
}
