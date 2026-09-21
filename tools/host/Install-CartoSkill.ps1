#requires -Version 5.1
<#
.SYNOPSIS
    把 carto-agent skill 一键装载到宿主 Agent 的 skills 目录。

.DESCRIPTION
    装载 = 让宿主 Agent 能像发现 ppt-master 一样发现并加载 carto-agent。
    对应测试清单 doc/dev-log/0920宿主Agent形态一测试清单.md 第 2.5 节与步骤 6。

    两种模式：
      Junction（默认）：创建目录联接指向仓库内的 skills\carto-agent。
                        无需管理员权限；装载内容始终与仓库同步，不会漂移；
                        适合开发与验收阶段。
      Copy           ：复制一份独立副本（排除 __pycache__ / *.pyc / .env）。
                        适合需要冻结被测版本的场景；仓库更新后需重新装载。

    装载后会自动用「装载路径下的 carto.py」执行一次 schema check，
    证明该副本能自行解析 schemas/ 与 policies/（carto_core 以 __file__ 定位协议资产）。

    注意：本脚本只处理目录式 skills 根（如 ~/.codex/skills）。
    注册表式插件宿主（Qoder plugins / Claude plugins）需要各自的插件打包格式，
    不在本脚本范围内。

.PARAMETER HostSkillsRoot
    宿主 skills 根目录。缺省时按 Codex → Hermes → Claude → agents → Qoder 顺序
    自动探测第一个已存在的目录。

.PARAMETER Mode
    Junction（默认）或 Copy。

.PARAMETER SkillName
    装载后的目录名，默认取 SKILL.md front-matter 的 name（carto-agent）。

.PARAMETER Force
    目标已存在时先移除再装载。对 junction 使用安全移除，不会删除仓库源目录内容。

.PARAMETER Uninstall
    卸载已装载的 skill（安全移除 junction 或副本目录）。

.PARAMETER HermesProjectLocal
    注册为 **Hermes 仓库本地技能**（推荐用于形态一宿主演练）：
    在 <repo>\.hermes\skills\<name> 建 junction 指向 <repo>\skills\<name>，
    再执行 hermes skills trust <repo>。技能仅在本仓库内启动的 Hermes 会话中加载，
    且优先于同名 profile 技能；不向全局目录写入任何内容。
    搭配 -Uninstall 使用则执行注销（hermes skills untrust + 移除 junction）。

.PARAMETER HermesExe
    hermes 可执行文件绝对路径。缺省从 PATH 与 %LOCALAPPDATA%\hermes\bin 探测。

.PARAMETER HermesGlobal
    注册为 **Hermes 全局 profile 技能**（任何 cwd 的会话都加载，在 /skills 目录的指定类别下出现）：
    在 <hermes_home>\skills\<Category>\<name> 建 junction 指向 <repo>\skills\<name>，
    再执行 hermes curator adopt <name>（关键：仅放 junction 不够，必须 adopt 打 provenance 标记才会显示）。
    搭配 -Uninstall 使用则安全移除 junction并从仓库外核验已不再列出。

.PARAMETER Category
    全局注册的目标类别（如 creative / software-development）。仅在 -HermesGlobal 时必需。
    须是 Hermes 既有顶层类别；新建类别会被警告（规范不鼓励随意新增顶层类别）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Install-CartoSkill.ps1 -HermesGlobal -Category creative

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Install-CartoSkill.ps1 -HermesGlobal -Category creative -Uninstall

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Install-CartoSkill.ps1 -HermesProjectLocal

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Install-CartoSkill.ps1 -HermesProjectLocal -Uninstall

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Install-CartoSkill.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Install-CartoSkill.ps1 -Mode Copy -Force

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Install-CartoSkill.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [string]$HostSkillsRoot = '',
    [ValidateSet('Junction', 'Copy')]
    [string]$Mode = 'Junction',
    [string]$SkillName = '',
    [switch]$Force,
    [switch]$Uninstall,
    [switch]$HermesProjectLocal,
    [switch]$HermesGlobal,
    [string]$Category = '',
    [string]$HermesExe = '',
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

Write-CartoBanner -Title 'Carto skill 宿主装载' -Subtitle 'Install-CartoSkill.ps1'

$repoRoot = Get-CartoRepoRoot
$sourceRoot = Get-CartoSkillRoot -RepoRoot $repoRoot
$cli = Get-CartoCliPath -RepoRoot $repoRoot

# Hermes 注册（项目本地或全局）只有 3 步，profile 目录装载有 4 步
$stepTotal = 4
if ($HermesProjectLocal -or $HermesGlobal) { $stepTotal = 3 }

# ── 1. 源目录完整性校验 ───────────────────────
Write-CartoStep "1/$stepTotal 校验源 skill 完整性"
Assert-CartoDir -Path $sourceRoot -What 'skill 目录'

$frontMatter = Read-CartoSkillFrontMatter -SkillRoot $sourceRoot
if (-not $frontMatter['name']) { throw 'SKILL.md front-matter 缺少 name 字段' }
if (-not $frontMatter['description']) { throw 'SKILL.md front-matter 缺少 description 字段' }
if (-not $frontMatter['version']) { throw 'SKILL.md front-matter 缺少 version 字段' }

if (-not $SkillName) { $SkillName = [string]$frontMatter['name'] }
Write-CartoOk ("name={0} version={1}" -f $frontMatter['name'], $frontMatter['version'])
Write-CartoInfo ("description={0}" -f $frontMatter['description'])

$requiredSubDirs = @('workflows', 'schemas', 'policies', 'scripts')
$missing = @()
foreach ($sub in $requiredSubDirs) {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot $sub) -PathType Container)) { $missing += $sub }
}
if ($missing.Count -gt 0) { throw "skill 源目录缺少必需子目录: $($missing -join ', ')" }
Write-CartoOk "必需子目录齐备: $($requiredSubDirs -join ', ')"

# 历史占位目录不得被装载
$legacy = Join-Path $repoRoot 'skills\carto-master'
if (Test-Path -LiteralPath $legacy) {
    Write-CartoInfo '检测到历史占位目录 skills\carto-master（按 AGENTS.md 不得作为运行入口，已忽略）'
}

# ── Hermes 仓库本地注册（优先分支）───────────
if ($HermesProjectLocal) {
    if ($Uninstall) {
        Write-CartoStep '注销 Hermes 仓库本地技能'
        $undo = Unregister-CartoHermesProjectSkill -RepoRoot $repoRoot -SkillName $SkillName -HermesExe $HermesExe
        if ($undo.Removed) { Write-CartoOk "已移除 junction: $($undo.LinkPath)" }
        else { Write-CartoWarn "junction 不存在或未移除: $($undo.LinkPath)" }
        if ($undo.TrustOutput) { Write-CartoInfo $undo.TrustOutput }
        Write-CartoOk "仓库源目录完好: $(Test-Path -LiteralPath (Join-Path $sourceRoot 'SKILL.md'))"
        [void](Write-CartoEnv -RepoRoot $repoRoot -Values @{
                hermes_project_local = $false; skill_installed = $false; skill_install_path = ''
            })
        exit 0
    }

    Write-CartoStep "2/$stepTotal 注册为 Hermes 仓库本地技能"
    $registration = Register-CartoHermesProjectSkill -RepoRoot $repoRoot -SourceRoot $sourceRoot `
        -SkillName $SkillName -HermesExe $HermesExe
    Write-CartoOk "hermes: $($registration.HermesExe)"
    if ($registration.Reused) { Write-CartoInfo "junction 已存在，直接复用: $($registration.LinkPath)" }
    else { Write-CartoOk "已创建 junction: $($registration.LinkPath) -> $sourceRoot" }

    if ($registration.TrustExit -ne 0) {
        Write-CartoFail "hermes skills trust 失败（退出码 $($registration.TrustExit)）"
        Write-CartoInfo $registration.TrustOutput
        exit 1
    }
    $trustFirstLine = (($registration.TrustOutput -split "`r?`n") | Where-Object { $_ } | Select-Object -First 1)
    Write-CartoOk "trust: $trustFirstLine"

    Write-CartoStep "3/$stepTotal 注册结果核验"
    if ($registration.Registered) {
        Write-CartoOk "hermes skills list 已列出 $SkillName"
    }
    else {
        Write-CartoFail "hermes skills list 未列出 $SkillName，注册未生效"
        exit 1
    }

    [void](Write-CartoEnv -RepoRoot $repoRoot -Values @{
            skill_installed      = $true
            skill_install_mode   = 'HermesProjectLocal'
            skill_install_path   = $registration.LinkPath
            host_skills_root     = (Join-Path $repoRoot '.hermes\skills')
            hermes_project_local = $true
            hermes_exe           = $registration.HermesExe
            skill_name           = $SkillName
            skill_version        = [string]$frontMatter['version']
        })

    Write-CartoStep '结果'
    Write-CartoOk "已注册为 Hermes 仓库本地技能: $SkillName"
    Write-CartoWarn '必须在本仓库内**新开一个 Hermes 会话**才能看到该技能：技能加载器与提示词快照在会话启动时初始化，当前会话不会刷新'
    Write-CartoInfo '验证：cd 到本仓库后新开会话，执行 hermes skills list 应看到 Source=local / Status=enabled'
    Write-CartoInfo '注销：Install-CartoSkill.ps1 -HermesProjectLocal -Uninstall'
    Write-CartoInfo '.hermes/ 已加入 .gitignore，junction 不会被提交'
    exit 0
}

# ── Hermes 全局 profile 注册（任何 cwd 的会话都加载）──
if ($HermesGlobal) {
    if (-not $Category) { throw '全局注册必须指定 -Category（如 creative / software-development）' }

    if ($Uninstall) {
        Write-CartoStep '注销 Hermes 全局技能'
        $undo = Unregister-CartoHermesGlobalSkill -SkillName $SkillName -Category $Category -HermesExe $HermesExe
        if ($undo.Removed) { Write-CartoOk "已移除全局 junction: $($undo.LinkPath)" }
        else { Write-CartoWarn "全局 junction 不存在或未移除: $($undo.LinkPath)" }
        if ($undo.StillListed) { Write-CartoWarn "hermes skills list 仍列出 $SkillName（provenance 标记残留）" }
        else { Write-CartoOk "hermes skills list 已不再列出 $SkillName" }
        Write-CartoInfo $undo.Note
        Write-CartoOk "仓库源目录完好: $(Test-Path -LiteralPath (Join-Path $sourceRoot 'SKILL.md'))"
        [void](Write-CartoEnv -RepoRoot $repoRoot -Values @{
                hermes_global = $false; skill_installed = $false; skill_install_path = ''
            })
        exit 0
    }

    Write-CartoStep "2/$stepTotal 注册为 Hermes 全局技能（类别 $Category）"
    $registration = Register-CartoHermesGlobalSkill -RepoRoot $repoRoot -SourceRoot $sourceRoot `
        -SkillName $SkillName -Category $Category -HermesExe $HermesExe
    Write-CartoOk "hermes: $($registration.HermesExe)"
    Write-CartoOk "已创建 junction: $($registration.LinkPath) -> $sourceRoot"

    if (-not $registration.AdoptOk) {
        Write-CartoFail "hermes curator adopt 失败（退出码 $($registration.AdoptExit)）"
        Write-CartoInfo $registration.AdoptOutput
        exit 1
    }
    $adoptFirstLine = (($registration.AdoptOutput -split "`r?`n") | Where-Object { $_ } | Select-Object -First 1)
    Write-CartoOk "curator adopt: $adoptFirstLine"

    Write-CartoStep "3/$stepTotal 注册结果核验（从仓库外查 skills list）"
    if ($registration.Registered) {
        Write-CartoOk "hermes skills list 已列出 $SkillName（类别=$Category）"
    }
    else {
        Write-CartoFail "hermes skills list 未在 $Category 类别下列出 $SkillName"
        if ($registration.ListedRow) { Write-CartoInfo "匹配行: $($registration.ListedRow)" }
        exit 1
    }

    [void](Write-CartoEnv -RepoRoot $repoRoot -Values @{
            skill_installed    = $true
            skill_install_mode = 'HermesGlobal'
            skill_install_path = $registration.LinkPath
            host_skills_root   = (Join-Path (Get-CartoHermesHome -HermesExe $HermesExe) 'skills')
            hermes_global      = $true
            hermes_category    = $Category
            hermes_exe         = $registration.HermesExe
            skill_name         = $SkillName
            skill_version      = [string]$frontMatter['version']
        })

    Write-CartoStep '结果'
    Write-CartoOk "已注册为 Hermes 全局技能: $SkillName（$Category）"
    Write-CartoWarn '必须重启 Hermes 会话才生效：技能加载器与提示词快照在会话启动时初始化'
    Write-CartoInfo "验证：新开会话后 /skills 目录的 $Category 类别下应出现 carto-agent；或从任意目录跑 hermes skills list"
    Write-CartoInfo "注销：Install-CartoSkill.ps1 -HermesGlobal -Category $Category -Uninstall"
    Write-CartoInfo '换类别：先 -Uninstall，再用新 -Category 重跑'
    exit 0
}

# ── 2. 解析宿主 skills 根 ─────────────────────
Write-CartoStep "2/$stepTotal 解析宿主 skills 根目录"
$resolvedRoot = $HostSkillsRoot
if (-not $resolvedRoot) {
    $env = Read-CartoEnv -RepoRoot $repoRoot
    if ($null -ne $env -and $env.PSObject.Properties['host_skills_root']) {
        $recorded = [string]$env.host_skills_root
        if ($recorded -and (Test-Path -LiteralPath $recorded)) { $resolvedRoot = $recorded }
    }
}
if (-not $resolvedRoot) { $resolvedRoot = Resolve-CartoHostSkillsRoot }

if (-not $resolvedRoot) {
    Write-CartoFail '未探测到任何宿主 skills 根目录'
    Write-CartoInfo '候选位置（均不存在）：'
    foreach ($candidate in (Get-CartoHostSkillsCandidates)) { Write-CartoInfo "  - $($candidate.Host): $($candidate.Path)" }
    Write-CartoInfo '请用 -HostSkillsRoot <绝对路径> 显式指定。'
    exit 1
}
Write-CartoOk "宿主 skills 根: $resolvedRoot"

$target = Join-Path $resolvedRoot $SkillName

# ── 卸载分支 ──────────────────────────────────
if ($Uninstall) {
    Write-CartoStep '卸载'
    if (-not (Test-Path -LiteralPath $target)) {
        Write-CartoWarn "未装载，无需卸载: $target"
        exit 0
    }
    if (Test-CartoReparsePoint -Path $target) {
        Remove-CartoJunction -Path $target
        Write-CartoOk "已移除 junction: $target（仓库源目录未受影响）"
    }
    else {
        Remove-CartoJunction -Path $target
        Write-CartoOk "已移除副本目录: $target"
    }
    [void](Write-CartoEnv -RepoRoot $repoRoot -Values @{ skill_installed = $false; skill_install_path = '' })
    exit 0
}

# ── 3. 处理已存在的目标 ───────────────────────
Write-CartoStep "3/$stepTotal 装载"
if (Test-Path -LiteralPath $target) {
    $isLink = Test-CartoReparsePoint -Path $target
    if ($isLink) { Write-CartoInfo "目标已存在且为 junction: $target" }
    else { Write-CartoInfo "目标已存在且为实体目录: $target" }
    if (-not $Force) {
        Write-CartoFail '目标已存在。确认无误后加 -Force 覆盖，或先执行 -Uninstall。'
        exit 1
    }
    Remove-CartoJunction -Path $target
    Write-CartoOk '已按 -Force 移除旧目标'
}

$parent = Split-Path -Path $target -Parent
if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

if ($Mode -eq 'Junction') {
    try {
        New-Item -ItemType Junction -Path $target -Target $sourceRoot -ErrorAction Stop | Out-Null
        Write-CartoOk "已创建 junction: $target -> $sourceRoot"
        Write-CartoInfo '装载内容与仓库保持同步，仓库更新后无需重新装载'
    }
    catch {
        Write-CartoWarn "junction 创建失败（$($_.Exception.Message)），回退为 Copy 模式"
        $Mode = 'Copy'
    }
}
if ($Mode -eq 'Copy') {
    $count = Copy-CartoSkillTree -Source $sourceRoot -Destination $target
    Write-CartoOk "已复制 $count 项到 $target（排除 __pycache__ / *.pyc / .env）"
    Write-CartoWarn '副本不会随仓库更新，重新验收前请重跑本脚本'
}

# ── 4. 装载后自检 ─────────────────────────────
Write-CartoStep "4/$stepTotal 装载后自检"
$installedSkill = Get-Content -Raw -LiteralPath (Join-Path $target 'SKILL.md') -Encoding UTF8
if ($installedSkill -notmatch '(?s)name:\s*carto-agent') {
    Write-CartoFail '装载路径下的 SKILL.md 不可读或内容不符'
    exit 1
}
Write-CartoOk '装载路径下 SKILL.md 可读'

$resolvedPython = Get-CartoEnvPython -RepoRoot $repoRoot -Preferred $Python
if ($resolvedPython) {
    $installedCli = Join-Path $target 'scripts\carto.py'
    if (Test-Path -LiteralPath $installedCli) {
        $check = Invoke-CartoCli -Python $resolvedPython -Cli $installedCli -Arguments @('schema', 'check') -TimeoutSeconds 180
        if ($check.Ok) {
            Write-CartoOk ("装载副本自解析协议资产成功：schema check 通过，checked={0}" -f $check.Json.checked)
        }
        else {
            Write-CartoFail "装载副本 schema check 失败：code=$($check.Code)"
            Write-CartoInfo $check.StdErr
            exit 1
        }
    }
    else { Write-CartoWarn "装载路径下缺少 scripts\carto.py: $installedCli" }
}
else {
    Write-CartoWarn '未找到可用 Python 解释器，跳过装载副本的 schema check 自检'
    Write-CartoInfo '请先运行 Set-CartoBaseEnv.ps1'
}

$envValues = @{
    skill_installed    = $true
    skill_install_mode = $Mode
    skill_install_path = $target
    host_skills_root   = $resolvedRoot
    skill_name         = $SkillName
    skill_version      = [string]$frontMatter['version']
}
[void](Write-CartoEnv -RepoRoot $repoRoot -Values $envValues)

Write-CartoStep '结果'
Write-CartoOk "装载完成: $target"
Write-CartoInfo '宿主 Agent 侧应能看到该 skill 的 name 与 description，并据 description 决定是否加载。'
Write-CartoInfo '演练时宿主 Agent 的入口纪律：先读 SKILL.md，再读 workflows/routing.md 选定唯一路由。'
Write-CartoInfo '下一步：Invoke-CartoPreflight.ps1 跑环境就绪门，然后从测试用例开始。'

exit 0
