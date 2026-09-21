#requires -Version 5.1
<#
.SYNOPSIS
    Carto 宿主环境就绪门（Preflight）。

.DESCRIPTION
    对应测试清单 doc/dev-log/0920宿主Agent形态一测试清单.md 的「步骤 1：环境就绪门」。
    必须先通过本脚本，才允许开始执行第 2~6 步的测试用例。

    检查项：
      1. schema check               —— 43 个 Schema 结构自检
      2. environment probe-renderer —— 渲染能力与环境指纹
      3. unittest 全量回归           —— 允许 skipped=1（Windows 符号链接用例）
      4. 工作区清洁度               —— 探测残留目录（漂移 D5 的副作用）

    结果写入 tools/host/reports/preflight-<时间戳>.json。

.PARAMETER SkipUnitTest
    跳过全量回归（约 77 秒）。仅用于快速复检 schema 与渲染能力。

.PARAMETER RequireRenderer
    渲染能力不可用时直接判定就绪门失败。默认关闭：A/B/C/D 组用例不依赖浏览器，
    渲染不可用只影响 U-P2.3 / U-P2.6 / U-P3 相关用例，因此默认给出 CONDITIONAL。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Invoke-CartoPreflight.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Invoke-CartoPreflight.ps1 -SkipUnitTest -RequireRenderer
#>

[CmdletBinding()]
param(
    [switch]$SkipUnitTest,
    [switch]$RequireRenderer,
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

Write-CartoBanner -Title 'Carto 宿主环境就绪门' -Subtitle 'Invoke-CartoPreflight.ps1'

$repoRoot = Get-CartoRepoRoot
$cli = Get-CartoCliPath -RepoRoot $repoRoot
$testsRoot = Get-CartoTestsRoot -RepoRoot $repoRoot

$resolvedPython = Get-CartoEnvPython -RepoRoot $repoRoot -Preferred $Python
if (-not $resolvedPython) {
    Write-CartoFail '未找到可用 Python 解释器，请先运行 Set-CartoBaseEnv.ps1'
    exit 1
}
Write-CartoOk "解释器: $resolvedPython ($((Get-CartoPythonVersionText -Python $resolvedPython)))"

$checks = @()
$gateFailed = $false
$conditional = $false

# ── 1. schema check ───────────────────────────
Write-CartoStep '1/4 Schema 注册表自检'
$schemaCheck = Invoke-CartoCli -Python $resolvedPython -Cli $cli -Arguments @('schema', 'check') -TimeoutSeconds 180
$schemaCount = 0
if ($schemaCheck.Ok) {
    $schemaCount = [int]$schemaCheck.Json.checked
    Write-CartoOk "schema check 通过，checked=$schemaCount"
    $checks += [pscustomobject]@{ Name = 'schema-check'; Passed = $true; Detail = "checked=$schemaCount" }
}
else {
    Write-CartoFail "schema check 失败：exit=$($schemaCheck.ExitCode) code=$($schemaCheck.Code)"
    Write-CartoInfo $schemaCheck.StdErr
    $checks += [pscustomobject]@{ Name = 'schema-check'; Passed = $false; Detail = $schemaCheck.Code }
    $gateFailed = $true
}

# ── 2. 渲染能力探测 ───────────────────────────
Write-CartoStep '2/4 渲染能力探测'
$renderer = Get-CartoRendererStatus -Python $resolvedPython -Cli $cli
$rendererAvailable = $renderer.Available
if ($rendererAvailable) {
    Write-CartoOk "status: available"
    Write-CartoOk "浏览器: $($renderer.Browser) / Node: $($renderer.Node)"
    Write-CartoOk "中文字体: $($renderer.Fonts)"
    Write-CartoInfo "指纹: $($renderer.Fingerprint)"
    $checks += [pscustomobject]@{ Name = 'renderer-probe'; Passed = $true; Detail = $renderer.Browser }
}
else {
    # 漂移 D4：能力不可用时退出码仍为 0，判据必须取响应体 status
    $detail = "status=$($renderer.Status) exit=$($renderer.ExitCode)"
    if ($RequireRenderer) {
        Write-CartoFail "渲染能力不可用（$detail），已按 -RequireRenderer 判定失败"
        $checks += [pscustomobject]@{ Name = 'renderer-probe'; Passed = $false; Detail = $detail }
        $gateFailed = $true
    }
    else {
        Write-CartoWarn "渲染能力不可用（$detail）"
        Write-CartoWarn '涉及渲染的用例不可执行；A/B/C/D 组仍可继续'
        $checks += [pscustomobject]@{ Name = 'renderer-probe'; Passed = $true; Detail = "$detail (non-blocking)" }
        $conditional = $true
    }
}

# ── 3. 全量回归 ───────────────────────────────
$unitTestSummary = ''
if ($SkipUnitTest) {
    Write-CartoStep '3/4 全量回归（已跳过）'
    Write-CartoWarn '已按 -SkipUnitTest 跳过；本次结果不能作为阶段验收证据'
    $checks += [pscustomobject]@{ Name = 'unit-tests'; Passed = $true; Detail = 'skipped by flag' }
    $conditional = $true
}
else {
    Write-CartoStep '3/4 全量回归（约 77 秒）'
    $testResult = Invoke-CartoProcess -FileName $resolvedPython -WorkingDirectory $repoRoot -TimeoutSeconds 1800 `
        -Arguments @('-m', 'unittest', 'discover', '-s', $testsRoot)
    $output = ($testResult.StdErr + "`n" + $testResult.StdOut)

    $ran = 0; $skipped = 0; $failed = 0; $errors = 0
    if ($output -match 'Ran (\d+) tests?') { $ran = [int]$Matches[1] }
    if ($output -match 'skipped=(\d+)') { $skipped = [int]$Matches[1] }
    if ($output -match 'failures=(\d+)') { $failed = [int]$Matches[1] }
    if ($output -match 'errors=(\d+)') { $errors = [int]$Matches[1] }

    $isOk = ($testResult.ExitCode -eq 0) -and ($output -match '(?m)^OK')
    $unitTestSummary = "ran=$ran skipped=$skipped failures=$failed errors=$errors"
    if ($isOk) {
        Write-CartoOk "unittest 通过：$unitTestSummary"
        if ($skipped -eq 1) {
            Write-CartoInfo '唯一 skip 为 Windows 符号链接用例（需开发者模式或管理员权限才可覆盖）'
        }
        elseif ($skipped -gt 1) {
            # 渲染用例在浏览器缺失时会静默 skip，必须提示而不是当作通过
            Write-CartoWarn "skipped=$skipped 大于预期的 1，可能有渲染用例被静默跳过"
            $conditional = $true
        }
        $checks += [pscustomobject]@{ Name = 'unit-tests'; Passed = $true; Detail = $unitTestSummary }
    }
    else {
        Write-CartoFail "unittest 未通过：$unitTestSummary exit=$($testResult.ExitCode)"
        $tail = ($output -split "`r?`n" | Select-Object -Last 40) -join "`n"
        Write-CartoInfo $tail
        $checks += [pscustomobject]@{ Name = 'unit-tests'; Passed = $false; Detail = $unitTestSummary }
        $gateFailed = $true
    }
}

# ── 4. 工作区清洁度 ───────────────────────────
Write-CartoStep '4/4 工作区清洁度（漂移 D5 副作用检查）'
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    $status = Invoke-CartoProcess -FileName $git.Source -WorkingDirectory $repoRoot -TimeoutSeconds 60 `
        -Arguments @('status', '--porcelain')
    $unexpected = @($status.StdOut -split "`r?`n" | Where-Object { $_ -match '^\?\?\s+(skills/|w/|tools/host/carto-host\.env\.json|tools/host/reports/)' })
    if ($unexpected.Count -eq 0) {
        Write-CartoOk '仓库内无探测残留（skills/ 下无未跟踪产物）'
        $checks += [pscustomobject]@{ Name = 'workspace-clean'; Passed = $true; Detail = 'clean' }
    }
    else {
        Write-CartoWarn '检测到疑似探测残留，执行用例前建议清理：'
        foreach ($line in $unexpected) { Write-CartoWarn "  $line" }
        Write-CartoInfo '成因：workflow 构造函数会 mkdir work_root，即使命令随后失败（见清单 D5）'
        $checks += [pscustomobject]@{ Name = 'workspace-clean'; Passed = $true; Detail = ($unexpected -join ' | ') }
        $conditional = $true
    }
}
else {
    Write-CartoWarn '未找到 git，跳过工作区清洁度检查'
    $checks += [pscustomobject]@{ Name = 'workspace-clean'; Passed = $true; Detail = 'git unavailable' }
}

# ── 判定与报告 ────────────────────────────────
$verdict = 'PASS'
if ($gateFailed) { $verdict = 'FAIL' }
elseif ($conditional) { $verdict = 'CONDITIONAL' }

$payload = [pscustomobject]@{
    probed_at         = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    verdict           = $verdict
    python            = $resolvedPython
    python_version    = (Get-CartoPythonVersionText -Python $resolvedPython)
    schema_count      = $schemaCount
    renderer_status   = $renderer.Status
    renderer_browser  = $renderer.Browser
    renderer_node     = $renderer.Node
    renderer_fonts    = $renderer.Fonts
    fingerprint       = $renderer.Fingerprint
    unit_tests        = $unitTestSummary
    checks            = $checks
}
$reportPath = Write-CartoReport -RepoRoot $repoRoot -Prefix 'preflight' -Payload $payload

Write-CartoStep "就绪门判定：$verdict"
Write-CartoInfo "报告: $reportPath"
Write-CartoInfo ("环境指纹: {0}" -f $renderer.Fingerprint)

if ($verdict -eq 'FAIL') {
    Write-CartoFail '就绪门未通过，禁止开始测试用例'
    exit 1
}

if ($verdict -eq 'CONDITIONAL') {
    Write-CartoWarn '就绪门有条件通过：可执行 A/B/C/D 组用例，但涉及渲染的用例结论不成立'
}
else {
    Write-CartoOk '就绪门通过，可以从测试用例开始'
}

Write-CartoHostHandoff -RepoRoot $repoRoot -Python $resolvedPython -Cli $cli

exit 0
