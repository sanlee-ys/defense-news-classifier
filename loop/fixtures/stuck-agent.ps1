<#
.SYNOPSIS
    A deterministic stub agent that fails the same way every iteration.

.DESCRIPTION
    Substituted for `claude` via `loop.ps1 -AgentCommand` so that ADR-016's
    stuck-detection rail can be exercised without spending any budget and
    without depending on what a real agent happens to do.

    It makes one fixed edit: it renames the frozen `Region rules:` header in
    `src/classify.py`. The ruler rejects that edit every time (exit 4), the
    loop reverts it every time, and the diff is therefore byte-identical on
    every iteration. Three of those in a row is what rail 4 halts on.

    It accepts and ignores `claude`'s flags, reads the prompt from stdin and
    discards it, and prints a result object of the same shape the loop parses.

.EXAMPLE
    pwsh loop/loop.ps1 -MaxIterations 4 -DryRunMetrics -NoPush `
        -AgentCommand loop/fixtures/stuck-agent.ps1
#>
param(
    # `claude` is called with double-dash flags, which PowerShell does not
    # bind by name. Swallow them all rather than declaring each one.
    [Parameter(ValueFromRemainingArguments = $true)]
    $Rest
)

$ErrorActionPreference = "Stop"

# Drain stdin so the caller's pipe closes cleanly.
$null = $input | Out-String

$target = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "src/classify.py"
$text = Get-Content $target -Raw
Set-Content -Path $target -Value ($text -replace "Region rules:", "Region guidance:") -NoNewline

@{ total_cost_usd = 0.0; is_error = $false; result = "stub: renamed the frozen region header" } |
    ConvertTo-Json -Compress
