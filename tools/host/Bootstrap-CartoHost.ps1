#requires -Version 5.1
<#
.SYNOPSIS
    Carto 宿主环境一键装载与配置入口。

.DESCRIPTION
    串起三个阶段，跑完后直接给出「从测试用例开始」的交接卡：

      阶段 1  Set-CartoBaseEnv.ps1      基础环境配置（解释器 / 依赖 / 渲染能力 / carto 命令）
      阶段 2  Install-CartoSkill.ps1    装载 skill 到宿主 skills 目录
      阶段 3  Invoke-CartoPreflight.ps1 环境就绪门（schema / 渲染 / 全量回归 / 工作区清洁度）

    任一阶段失败即中止并给出修复指引。全部通过后，执行
    tools\host\Invoke-CartoHostCases.ps1 即可开始跑测试用例。

.PARAMETER Python
    显式指定 Python 解释器绝对路径。缺省自动探测（排除微软商店占位符）。

.PARAMETER HostSkillsRoot
    宿主 skills 根目录。缺省自动探测第一个已存在的候选目录。

.PARAMETER InstallMode
    Junction（默认，与仓库同步、无需管理员权限）或 Copy（独立副本）。

.PARAMETER InstallDependencies
    依赖缺失时自动 pip install -r skills/carto-agent/requirements.txt。
    默认关闭，脚本不会未经同意修改 Python 环境。

.PARAMETER SkipInstall
    跳过阶段 2（skill 已装载或本次只想体检环境）。

.PARAMETER SkipUnitTest
    跳过阶段 3 的全量回归（约 77 秒），只做快速复检。

.PARAMETER RequireRenderer
    渲染能力不可用时判定就绪门失败。默认给出 CONDITIONAL 并继续。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Bootstrap-CartoHost.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Bootstrap-CartoHost.ps1 -SkipUnitTest -InstallDependencies

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Bootstrap-CartoHost.ps1 -InstallMode Copy -HostSkillsRoot C:\host\skills
#>

[CmdletBinding()]
param(
    [string]$Python = '',
    [string]$HostSkillsRoot = '',
    [ValidateSet('Junction', 'Copy')]
    [string]$InstallMode = 'Junction',
    [switch]$InstallDependencies,
    [switch]$SkipInstall,
    [switch]$SkipUnitTest,
    [switch]$RequireRenderer
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

$startedAt = Get-Date
Write-CartoBanner -Title 'Carto 宿主环境一键装载与配置' -Subtitle 'Bootstrap-CartoHost.ps1'

$psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $psExe)) { $psExe = 'powershell.exe' }

try { $repoRoot = Get-CartoRepoRoot }
catch { Write-CartoFail $_.Exception.Message; exit 1 }
Write-CartoOk "仓库根: $repoRoot"

function Invoke-Stage {
    param([string]$Name, [string]$Script, [string[]]$StageArgs)
    Write-CartoStep "阶段：$Name"
    $path = Join-Path $PSScriptRoot $Script
    if (-not (Test-Path -LiteralPath $path)) {
        Write-CartoFail "脚本缺失: $path"
        return -1
    }
    # 用子进程执行，保持各阶段独立作用域与真实退出码。
    # PowerShell 子进程按系统 ANSI 代码页写出，因此用 Default 而非 UTF-8 解码，
    # 否则中文全部变 '?'；这样阶段输出也能被重定向到日志文件供 CI 留存。
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $path) + $StageArgs
    $result = Invoke-CartoProcess -FileName $psExe -Arguments $arguments -WorkingDirectory $repoRoot `
        -TimeoutSeconds 2400 -OutputEncoding ([System.Text.Encoding]::Default)

    if ($result.StdOut) { Write-Host $result.StdOut.TrimEnd() }
    if ($result.StdErr) { Write-Host $result.StdErr.TrimEnd() -ForegroundColor DarkGray }
    if ($result.ExitCode -ne 0) { Write-CartoFail "$Name 失败（退出码 $($result.ExitCode)）" }
    return $result.ExitCode
}

# ── 阶段 1：基础环境配置 ──────────────────────
$stageOneArgs = @()
if ($Python) { $stageOneArgs += @('-Python', $Python) }
if ($InstallDependencies) { $stageOneArgs += '-InstallDependencies' }
$code = Invoke-Stage -Name '基础环境配置' -Script 'Set-CartoBaseEnv.ps1' -StageArgs $stageOneArgs
if ($code -ne 0) {
    Write-CartoFail '基础环境未就绪，已中止。请按上方 FAIL 项修复后重跑。'
    exit 1
}

# 后续阶段复用阶段 1 探测到的解释器
$envData = Read-CartoEnv -RepoRoot $repoRoot
$resolvedPython = $Python
if (-not $resolvedPython -and $null -ne $envData -and $envData.PSObject.Properties['python']) {
    $resolvedPython = [string]$envData.python
}

# ── 阶段 2：装载 skill ────────────────────────
if ($SkipInstall) {
    Write-CartoStep '阶段：装载 skill（已跳过）'
    Write-CartoWarn '已按 -SkipInstall 跳过；宿主 Agent 侧可能看不到本 skill'
}
else {
    $stageTwoArgs = @('-Mode', $InstallMode, '-Force')
    if ($resolvedPython) { $stageTwoArgs += @('-Python', $resolvedPython) }
    if ($HostSkillsRoot) { $stageTwoArgs += @('-HostSkillsRoot', $HostSkillsRoot) }
    $code = Invoke-Stage -Name '装载 skill 到宿主' -Script 'Install-CartoSkill.ps1' -StageArgs $stageTwoArgs
    if ($code -ne 0) {
        Write-CartoWarn '装载未完成；仍可继续执行环境就绪门与 CLI 契约用例，但宿主行为演练（步骤 6）无法进行'
    }
}

# ── 阶段 3：环境就绪门 ────────────────────────
$stageThreeArgs = @()
if ($resolvedPython) { $stageThreeArgs += @('-Python', $resolvedPython) }
if ($SkipUnitTest) { $stageThreeArgs += '-SkipUnitTest' }
if ($RequireRenderer) { $stageThreeArgs += '-RequireRenderer' }
$code = Invoke-Stage -Name '环境就绪门' -Script 'Invoke-CartoPreflight.ps1' -StageArgs $stageThreeArgs
if ($code -ne 0) {
    Write-CartoFail '就绪门未通过，禁止开始测试用例。'
    exit 1
}

# ── 交接 ──────────────────────────────────────
$elapsed = [int]((Get-Date) - $startedAt).TotalSeconds
$cli = Get-CartoCliPath -RepoRoot $repoRoot
if (-not $resolvedPython) { $resolvedPython = (Get-CartoEnvPython -RepoRoot $repoRoot) }

Write-CartoBanner -Title "装载与配置完成（耗时 ${elapsed}s）"
Write-CartoHostHandoff -RepoRoot $repoRoot -Python $resolvedPython -Cli $cli

exit 0
