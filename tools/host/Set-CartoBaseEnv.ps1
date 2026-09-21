#requires -Version 5.1
<#
.SYNOPSIS
    Carto 宿主基础环境配置脚本。

.DESCRIPTION
    完成宿主环境的基础配置与体检，并把结果写入 tools/host/carto-host.env.json
    供后续装载、就绪门与用例执行脚本复用：

      1. 定位仓库根与 skill 根
      2. 探测真实 Python 解释器（自动排除微软商店占位符），校验版本 >= 3.11
      3. 校验直接依赖 jsonschema / PyYAML（可选自动安装）
      4. 探测渲染能力（Chromium / Node / 中文字体）与环境指纹
      5. 检查 carto 控制台脚本是否已安装（对应测试用例 TC-D04）

    对应测试清单：doc/dev-log/0920宿主Agent形态一测试清单.md 第二章「前置条件」与步骤 1。

.PARAMETER Python
    显式指定 Python 解释器绝对路径。缺省时按 CARTO_PYTHON 环境变量、PATH、
    py 启动器、常见安装位置的顺序自动探测。

.PARAMETER InstallDependencies
    依赖缺失时执行 pip install -r skills/carto-agent/requirements.txt。
    默认关闭：脚本不会在未经同意的情况下修改 Python 环境。

.PARAMETER SkipRendererProbe
    跳过渲染能力探测（探测会启动浏览器握手，耗时约数秒）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Set-CartoBaseEnv.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Set-CartoBaseEnv.ps1 -Python D:\ProgramData\miniconda3\python.exe
#>

[CmdletBinding()]
param(
    [string]$Python = '',
    [switch]$InstallDependencies,
    [switch]$SkipRendererProbe
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

$exitCode = 0
$warnings = @()

Write-CartoBanner -Title 'Carto 宿主基础环境配置' -Subtitle 'Set-CartoBaseEnv.ps1'

# ── 1. 仓库与 skill ───────────────────────────
Write-CartoStep '1/5 定位仓库与 skill'
try {
    $repoRoot = Get-CartoRepoRoot
    $skillRoot = Get-CartoSkillRoot -RepoRoot $repoRoot
    $cli = Get-CartoCliPath -RepoRoot $repoRoot
    Assert-CartoDir -Path $skillRoot -What 'skill 目录'
    if (-not (Test-Path -LiteralPath $cli)) { throw "CLI 入口不存在: $cli" }
    Write-CartoOk "仓库根: $repoRoot"
    Write-CartoOk "skill 根: $skillRoot"
    Write-CartoOk "CLI 入口: $cli"
}
catch {
    Write-CartoFail $_.Exception.Message
    exit 1
}

$frontMatter = Read-CartoSkillFrontMatter -SkillRoot $skillRoot
Write-CartoInfo ("SKILL.md front-matter: name={0} version={1}" -f $frontMatter['name'], $frontMatter['version'])

# ── 2. Python 解释器 ──────────────────────────
Write-CartoStep '2/5 探测 Python 解释器（要求 >= 3.11）'
$resolvedPython = $null
try { $resolvedPython = Find-CartoPython -Preferred $Python }
catch { Write-CartoFail $_.Exception.Message; exit 1 }

if (-not $resolvedPython) {
    Write-CartoFail '未找到可用的 Python 3.11+ 解释器'
    Write-CartoInfo 'PATH 中的 python/python3 可能只是微软商店占位符（...\WindowsApps\python.exe），已被自动排除。'
    Write-CartoInfo '请安装 Python 3.11+，或用 -Python <绝对路径> 显式指定，或设置环境变量 CARTO_PYTHON。'
    exit 1
}

$pythonVersion = Get-CartoPythonVersionText -Python $resolvedPython
Write-CartoOk "解释器: $resolvedPython"
Write-CartoOk "版本: Python $pythonVersion"
if (Test-CartoPythonDependencies -Python $resolvedPython) {
    Write-CartoOk '已优选具备 jsonschema + PyYAML 的解释器'
}

# ── 3. 直接依赖 ───────────────────────────────
Write-CartoStep '3/5 校验直接依赖（jsonschema / PyYAML）'
$deps = Get-CartoDependencyStatus -Python $resolvedPython
$depsOk = ($deps.JsonSchema -ne 'MISSING' -and $deps.JsonSchema -ne 'UNKNOWN' -and
            $deps.PyYaml -ne 'MISSING' -and $deps.PyYaml -ne 'UNKNOWN')

if ($depsOk) {
    if ($deps.Versions) {
        $versionParts = $deps.Versions.Split('|')
        Write-CartoOk "jsonschema $($versionParts[0]) / PyYAML $($versionParts[1])"
        if ($versionParts[0] -notmatch '^4\.(2[3-9]|[3-9]\d)') {
            Write-CartoWarn "jsonschema 版本 $($versionParts[0]) 不在声明范围 >=4.23,<5 内"
            $warnings += 'jsonschema 版本越界'
        }
        if ($versionParts[1] -notmatch '^6\.') {
            Write-CartoWarn "PyYAML 版本 $($versionParts[1]) 不在声明范围 >=6.0.2,<7 内"
            $warnings += 'PyYAML 版本越界'
        }
    }
    else { Write-CartoOk 'jsonschema 与 PyYAML 均可导入（版本未知）' }
}
elseif ($InstallDependencies) {
    Write-CartoInfo '依赖缺失，执行 pip install -r skills/carto-agent/requirements.txt ...'
    $requirements = Join-Path $skillRoot 'requirements.txt'
    $installResult = Invoke-CartoProcess -FileName $resolvedPython -TimeoutSeconds 600 `
        -Arguments @('-m', 'pip', 'install', '-r', $requirements)
    if ($installResult.ExitCode -eq 0) {
        $deps = Get-CartoDependencyStatus -Python $resolvedPython
        $depsOk = ($deps.JsonSchema -ne 'MISSING' -and $deps.PyYaml -ne 'MISSING')
        if ($depsOk) { Write-CartoOk '依赖安装完成' }
        else { Write-CartoFail '依赖安装后仍不可导入'; $exitCode = 1 }
    }
    else {
        Write-CartoFail '依赖安装失败'
        Write-CartoInfo $installResult.StdErr
        $exitCode = 1
    }
}
else {
    Write-CartoFail "依赖缺失: jsonschema=$($deps.JsonSchema) PyYaml=$($deps.PyYaml)"
    Write-CartoInfo "修复方式一：重跑本脚本并加 -InstallDependencies"
    Write-CartoInfo "修复方式二：& `"$resolvedPython`" -m pip install -r `"$skillRoot\requirements.txt`""
    Write-CartoInfo '本机已探测到的合格解释器（可用 -Python <绝对路径> 指定）：'
    foreach ($row in @(Get-CartoPythonDiagnosis)) {
        Write-CartoInfo ("  {0,-6} jsonschema={1,-8} PyYaml={2,-8} {3}" -f $row.Version, $row.JsonSchema, $row.PyYaml, $row.Path)
    }
    $exitCode = 1
}

# ── 4. 渲染能力 ───────────────────────────────
Write-CartoStep '4/5 探测渲染能力（Chromium / Node / 中文字体）'
$renderer = $null
if ($SkipRendererProbe) {
    Write-CartoWarn '已按 -SkipRendererProbe 跳过；涉及渲染的用例不可执行'
    $warnings += '未探测渲染能力'
}
elseif (-not $depsOk) {
    Write-CartoWarn '依赖不完整，跳过渲染探测'
}
else {
    $renderer = Get-CartoRendererStatus -Python $resolvedPython -Cli $cli
    if ($renderer.Available) {
        Write-CartoOk "status: available"
        Write-CartoOk "浏览器: $($renderer.Browser)"
        Write-CartoOk "Node: $($renderer.Node)"
        Write-CartoOk "中文字体: $($renderer.Fonts)"
        Write-CartoInfo "指纹: $($renderer.Fingerprint)"
    }
    else {
        # 漂移 D4：探测不可用时 CLI 仍返回退出码 0，判据在响应体 status 字段
        Write-CartoWarn "status: $($renderer.Status)（退出码仍为 $($renderer.ExitCode)，判据在响应体而非退出码）"
        Write-CartoWarn '涉及渲染的用例（U-P2.3 / U-P2.6 / U-P3 预览冻结）在本宿主环境不可执行'
        Write-CartoInfo '按 U-P2 架构图约定：浏览器与 Node 属宿主环境能力，缺失时判定为未完成而非降级'
        $warnings += '渲染能力不可用'
    }
}

# ── 5. carto 控制台脚本 ───────────────────────
Write-CartoStep '5/5 检查 carto 控制台脚本（TC-D04）'
$cartoCommand = Get-Command carto -ErrorAction SilentlyContinue
if ($cartoCommand) {
    Write-CartoOk "已安装: $($cartoCommand.Source)"
}
else {
    Write-CartoWarn '未安装 carto 命令；TC-D04 不可执行'
    Write-CartoInfo "安装方式（会修改当前 Python 环境，请自行决定）：& `"$resolvedPython`" -m pip install -e `"$repoRoot`""
    $warnings += 'carto 控制台脚本未安装'
}

# ── 写入环境配置 ──────────────────────────────
$envValues = @{
    repo_root        = $repoRoot
    skill_root       = $skillRoot
    cli_path         = $cli
    tests_root       = (Get-CartoTestsRoot -RepoRoot $repoRoot)
    python           = $resolvedPython
    python_version   = $pythonVersion
    dependencies_ok  = $depsOk
    dependency_info  = $deps.Versions
    carto_installed  = [bool]$cartoCommand
    warnings         = $warnings
}
if ($renderer) {
    $envValues['renderer_available'] = $renderer.Available
    $envValues['renderer_status'] = $renderer.Status
    $envValues['renderer_fingerprint'] = $renderer.Fingerprint
    $envValues['renderer_browser'] = $renderer.Browser
    $envValues['renderer_node'] = $renderer.Node
    $envValues['renderer_fonts'] = $renderer.Fonts
}
$envPath = Write-CartoEnv -RepoRoot $repoRoot -Values $envValues

Write-CartoStep '结果'
Write-CartoOk "环境配置已写入: $envPath"
if ($warnings.Count -gt 0) { Write-CartoWarn ("待处理项 {0} 项: {1}" -f $warnings.Count, ($warnings -join '; ')) }
if ($exitCode -eq 0) {
    Write-CartoOk '基础环境配置完成'
    Write-CartoInfo '下一步：Install-CartoSkill.ps1 装载到宿主，或直接 Invoke-CartoPreflight.ps1 跑就绪门'
}
else { Write-CartoFail '基础环境配置未通过，请先修复上述 FAIL 项' }

exit $exitCode
