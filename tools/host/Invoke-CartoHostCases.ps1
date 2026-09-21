#requires -Version 5.1
<#
.SYNOPSIS
    Carto 宿主形态一测试用例执行器（A/B/C/D 四组）。

.DESCRIPTION
    按 doc/dev-log/0920宿主Agent形态一测试清单.md 第四章逐条执行用例，
    输出结果表并写入 tools/host/reports/host-cases-<时间戳>.json。

    结果分四类：
      PASS   契约与文档一致
      FAIL   契约不符且未登记为已知漂移 —— 视为回归，退出码 1
      DRIFT  已知契约漂移（清单第五章 D1/D2），预期不符但不计为回归
      SKIP   环境不具备或需人工并发观测

    所有会产生副作用的用例都在 tools/host/.scratch 下执行，结束后自动清理
    （对应清单 8.2「演练产生的空 run 目录与 .workflow.lock 已清理」）。

.PARAMETER Group
    只跑指定组，可多值：A B C D。缺省全跑。

.PARAMETER IncludeUnitTest
    TC-D05 实际执行全量回归（约 77 秒）。缺省只做结构性检查，全量回归由
    Invoke-CartoPreflight.ps1 负责，避免重复耗时。

.PARAMETER Strict
    把 DRIFT 也计为失败。用于漂移处置完成后确认已修复。

.PARAMETER KeepArtifacts
    保留 .scratch 目录以便取证。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Invoke-CartoHostCases.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\Invoke-CartoHostCases.ps1 -Group A,B -Strict
#>

[CmdletBinding()]
param(
    [ValidateSet('A', 'B', 'C', 'D')]
    [string[]]$Group = @('A', 'B', 'C', 'D'),
    [switch]$IncludeUnitTest,
    [switch]$Strict,
    [switch]$KeepArtifacts,
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

Write-CartoBanner -Title 'Carto 宿主形态一测试用例' -Subtitle 'Invoke-CartoHostCases.ps1'

$repoRoot = Get-CartoRepoRoot
$skillRoot = Get-CartoSkillRoot -RepoRoot $repoRoot
$cli = Get-CartoCliPath -RepoRoot $repoRoot
$testsRoot = Get-CartoTestsRoot -RepoRoot $repoRoot

$resolvedPython = Get-CartoEnvPython -RepoRoot $repoRoot -Preferred $Python
if (-not $resolvedPython) {
    Write-CartoFail '未找到可用 Python 解释器，请先运行 Set-CartoBaseEnv.ps1'
    exit 1
}
Write-CartoOk "解释器: $resolvedPython"

# 专用沙箱根：所有副作用都落在这里，跑完清理
$scratch = Join-Path $repoRoot ("tools\host\.scratch\" + (Get-Date).ToString('yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
$projectRoot = Join-Path $scratch 'project'
New-Item -ItemType Directory -Path $projectRoot -Force | Out-Null
$policy = Join-Path $skillRoot 'policies\scope-baseline.yaml'
$intentProfiles = Join-Path $skillRoot 'policies\intent-profiles.yaml'
$pyproject = Join-Path $repoRoot 'pyproject.toml'
$outsideFile = Join-Path $env:SystemRoot 'win.ini'

$script:Results = New-Object System.Collections.ArrayList

function Add-CaseResult {
    param(
        [string]$Id, [string]$CaseGroup, [string]$Purpose,
        [ValidateSet('PASS', 'FAIL', 'DRIFT', 'SKIP')][string]$Status,
        [string]$Expected = '', [string]$Actual = '', [string]$Note = ''
    )
    [void]$script:Results.Add([pscustomobject]@{
            Id = $Id; Group = $CaseGroup; Purpose = $Purpose; Status = $Status
            Expected = $Expected; Actual = $Actual; Note = $Note
        })
    $color = 'Gray'
    if ($Status -eq 'PASS') { $color = 'Green' }
    elseif ($Status -eq 'FAIL') { $color = 'Red' }
    elseif ($Status -eq 'DRIFT') { $color = 'Yellow' }
    $suffix = ''
    if ($Note) { $suffix = "  # $Note" }
    Write-Host ("  [{0,-4}] {1,-8} {2}{3}" -f $Status, $Id, $Purpose, $suffix) -ForegroundColor $color
    if ($Status -eq 'FAIL') {
        Write-Host ("         预期: {0}" -f $Expected) -ForegroundColor DarkGray
        Write-Host ("         实际: {0}" -f $Actual) -ForegroundColor DarkGray
    }
}

function Invoke-Case {
    <# 包裹单条用例，异常不中断整体执行 #>
    param([string]$Id, [string]$CaseGroup, [string]$Purpose, [scriptblock]$Body)
    try { & $Body }
    catch { Add-CaseResult -Id $Id -Group $CaseGroup -Purpose $Purpose -Status 'FAIL' -Expected '用例正常执行' -Actual $_.Exception.Message }
}

function Assert-CliContract {
    <#
        校验 CLI 输出契约并登记结果：
          成功 -> 退出码 0 且 stdout 为 {"ok":true}
          失败 -> 退出码 2 且 stderr 为 {"ok":false,"code":...}
    #>
    param(
        [string]$Id, [string]$CaseGroup, [string]$Purpose,
        $Result, [int]$ExpectExit, [string]$ExpectCode = '', [string]$Note = ''
    )
    $actual = "exit=$($Result.ExitCode)"
    if ($Result.Code) { $actual += " code=$($Result.Code)" }

    $passed = ($Result.ExitCode -eq $ExpectExit)
    if ($passed -and $ExpectExit -eq 0) {
        $passed = ($null -ne $Result.Json -and $Result.Json.ok -eq $true)
        if (-not $passed) { $actual += ' stdout非{"ok":true}' }
    }
    if ($passed -and $ExpectCode) {
        $passed = ($Result.Code -eq $ExpectCode)
    }
    if ($passed -and $ExpectExit -ne 0) {
        # 失败路径必须仍是结构化 JSON，否则宿主 Agent 无法归因
        if ($null -eq $Result.Json) { $passed = $false; $actual += ' stderr非结构化JSON' }
    }

    if ($passed) { Add-CaseResult -Id $Id -Group $CaseGroup -Purpose $Purpose -Status 'PASS' -Note $Note }
    else {
        Add-CaseResult -Id $Id -Group $CaseGroup -Purpose $Purpose -Status 'FAIL' `
            -Expected "exit=$ExpectExit$(if ($ExpectCode) { " code=$ExpectCode" })" -Actual $actual -Note $Note
    }
    return $passed
}

# ═════════════════════════════════════════════
# A 组：CLI 契约与只读能力
# ═════════════════════════════════════════════
if ($Group -contains 'A') {
    Write-CartoStep 'A 组：CLI 契约与只读能力（7 条）'

    Invoke-Case 'TC-A01' 'A' 'Schema 注册表自检' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -Arguments @('schema', 'check') -TimeoutSeconds 180
        $note = ''
        if ($r.Ok) { $note = "checked=$($r.Json.checked)" }
        [void](Assert-CliContract -Id 'TC-A01' -CaseGroup 'A' -Purpose 'Schema 注册表自检' -Result $r -ExpectExit 0 -Note $note)
    }

    Invoke-Case 'TC-A02' 'A' '渲染能力探测契约' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -Arguments @('environment', 'probe-renderer') -TimeoutSeconds 300
        $status = ''
        if ($null -ne $r.Json -and $r.Json.environment) { $status = [string]$r.Json.environment.status }
        # 契约：无论可用与否都返回退出码 0；不可用时响应体必须带 CAPABILITY_NOT_AVAILABLE（漂移 D4）
        $ok = ($r.ExitCode -eq 0) -and ($status -eq 'available' -or $status -eq 'unavailable')
        if ($ok -and $status -eq 'unavailable') {
            $ok = ($null -ne $r.Json.environment.error -and [string]$r.Json.environment.error.code -eq 'CAPABILITY_NOT_AVAILABLE')
        }
        if ($ok) {
            Add-CaseResult -Id 'TC-A02' -Group 'A' -Purpose '渲染能力探测契约' -Status 'PASS' -Note "status=$status（判据在响应体而非退出码）"
        }
        else {
            Add-CaseResult -Id 'TC-A02' -Group 'A' -Purpose '渲染能力探测契约' -Status 'FAIL' -Expected 'exit=0 且 status∈{available,unavailable}' -Actual "exit=$($r.ExitCode) status=$status"
        }
    }

    Invoke-Case 'TC-A03' 'A' '版本化策略自校验' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 180 `
            -Arguments @('schema', 'validate', 'intent-profiles', $intentProfiles, '--allowed-root', $repoRoot)
        [void](Assert-CliContract -Id 'TC-A03' -CaseGroup 'A' -Purpose '版本化策略自校验' -Result $r -ExpectExit 0)
    }

    Invoke-Case 'TC-A04' 'A' '子命令帮助可用' {
        $r = Invoke-CartoProcess -FileName $resolvedPython -Arguments @($cli, 'create-template', '--help') -TimeoutSeconds 60
        if ($r.ExitCode -eq 0 -and $r.StdOut -match 'analyze') {
            Add-CaseResult -Id 'TC-A04' -Group 'A' -Purpose '子命令帮助可用' -Status 'PASS'
        }
        else {
            Add-CaseResult -Id 'TC-A04' -Group 'A' -Purpose '子命令帮助可用' -Status 'FAIL' -Expected 'exit=0 且列出 analyze' -Actual "exit=$($r.ExitCode)"
        }
    }

    Invoke-Case 'TC-A05' 'A' '顶层子命令集合固定' {
        $r = Invoke-CartoProcess -FileName $resolvedPython -Arguments @($cli, '--help') -TimeoutSeconds 60
        $expected = @('schema', 'security', 'approval', 'intent', 'environment', 'data', 'create-template', 'generate-map')
        $missing = @($expected | Where-Object { $r.StdOut -notmatch [regex]::Escape($_) })
        if ($r.ExitCode -eq 0 -and $missing.Count -eq 0) {
            Add-CaseResult -Id 'TC-A05' -Group 'A' -Purpose '顶层子命令集合固定' -Status 'PASS' -Note "$($expected.Count) 个子命令"
        }
        else {
            Add-CaseResult -Id 'TC-A05' -Group 'A' -Purpose '顶层子命令集合固定' -Status 'FAIL' -Expected ($expected -join ',') -Actual "缺失: $($missing -join ',')"
        }
    }

    Invoke-Case 'TC-A06' 'A' '未知 schema 名被拒' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('schema', 'validate', 'not-a-schema', $policy, '--allowed-root', $repoRoot)
        [void](Assert-CliContract -Id 'TC-A06' -CaseGroup 'A' -Purpose '未知 schema 名被拒' -Result $r -ExpectExit 2 -ExpectCode 'SCHEMA_NOT_FOUND')
    }

    Invoke-Case 'TC-A07' 'A' '不支持的文档类型被拒' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('schema', 'validate', 'not-a-schema', $pyproject, '--allowed-root', $repoRoot)
        [void](Assert-CliContract -Id 'TC-A07' -CaseGroup 'A' -Purpose '不支持的文档类型被拒' -Result $r -ExpectExit 2 -ExpectCode 'DOCUMENT_TYPE_UNSUPPORTED' -Note '文档解析先于 schema 查表')
    }
}

# ═════════════════════════════════════════════
# B 组：安全边界与拒绝路径
# ═════════════════════════════════════════════
if ($Group -contains 'B') {
    Write-CartoStep 'B 组：安全边界与拒绝路径（8 条）'

    Invoke-Case 'TC-B01' 'B' '越允许根被拒' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('security', 'check-path', $outsideFile, '--allowed-root', $skillRoot)
        [void](Assert-CliContract -Id 'TC-B01' -CaseGroup 'B' -Purpose '越允许根被拒' -Result $r -ExpectExit 2 -ExpectCode 'PATH_OUTSIDE_ALLOWED_ROOT')
    }

    Invoke-Case 'TC-B02' 'B' '相对 allowed-root 被拒' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 -WorkingDirectory $repoRoot `
            -Arguments @('security', 'check-path', 'x.txt', '--allowed-root', 'skills')
        [void](Assert-CliContract -Id 'TC-B02' -CaseGroup 'B' -Purpose '相对 allowed-root 被拒' -Result $r -ExpectExit 2 -ExpectCode 'ALLOWED_ROOT_NOT_ABSOLUTE')
    }

    Invoke-Case 'TC-B03' 'B' '相对 repository-root 被拒' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 -WorkingDirectory $repoRoot `
            -Arguments @('generate-map', 'intake', (Join-Path $scratch 'nope.yaml'),
                '--project-root', $projectRoot, '--workdir', (Join-Path $scratch 'b03-run'),
                '--repository-root', 'rep', '--repository-scope', 'local',
                '--allowed-root', $scratch)
        [void](Assert-CliContract -Id 'TC-B03' -CaseGroup 'B' -Purpose '相对 repository-root 被拒' -Result $r -ExpectExit 2 -ExpectCode 'RELATIVE_PATH_WITHOUT_ROOT')
    }

    Invoke-Case 'TC-B04' 'B' '未知字段默认拒绝' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('schema', 'validate', 'scenario', $policy, '--allowed-root', $repoRoot)
        $passed = Assert-CliContract -Id 'TC-B04' -CaseGroup 'B' -Purpose '未知字段默认拒绝' -Result $r -ExpectExit 2 -ExpectCode 'SCHEMA_VALIDATION_FAILED'
        if ($passed -and $r.StdErr -notmatch 'Additional properties are not allowed') {
            Add-CaseResult -Id 'TC-B04b' -Group 'B' -Purpose '错误信息指明未知字段' -Status 'FAIL' -Expected 'message 含 Additional properties are not allowed' -Actual $r.StdErr
        }
    }

    Invoke-Case 'TC-B05' 'B' '回执文件缺失被拒' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('approval', 'verify', (Join-Path $scratch 'nope.yaml'), '--allowed-root', $scratch,
                '--action', 'approve-map-brief', '--object-digest', 'sha256:aa', '--scope', 'project:p',
                '--policy-id', 'carto-security', '--tenant-id', 't', '--issuer', 'i',
                '--subject-id', 's', '--object-type', 'map-brief', '--environment', 'local',
                '--nonce-db', (Join-Path $scratch 'n.sqlite3'))
        [void](Assert-CliContract -Id 'TC-B05' -CaseGroup 'B' -Purpose '回执文件缺失被拒' -Result $r -ExpectExit 2 -ExpectCode 'PATH_NOT_FOUND')
    }

    Invoke-Case 'TC-B06' 'B' '独立渲染入口不存在且不建目录' {
        $workdir = Join-Path $scratch 'render-probe\job'
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('create-template', 'render', '--project-root', $projectRoot,
                '--workdir', $workdir, '--allowed-root', $scratch)
        $passed = Assert-CliContract -Id 'TC-B06' -CaseGroup 'B' -Purpose '独立渲染入口不存在' -Result $r -ExpectExit 2 -ExpectCode 'CAPABILITY_NOT_AVAILABLE'
        if ($passed) {
            if (Test-Path -LiteralPath $workdir) {
                Add-CaseResult -Id 'TC-B06b' -Group 'B' -Purpose '拒绝后不创建 workdir' -Status 'FAIL' -Expected '不创建' -Actual $workdir
            }
            else { Add-CaseResult -Id 'TC-B06b' -Group 'B' -Purpose '拒绝后不创建 workdir' -Status 'PASS' }
        }
    }

    Invoke-Case 'TC-B07' 'B' '仓库根校验早于请求校验' {
        $workdir = Join-Path $scratch 'b07-run'
        $missingRepo = Join-Path $scratch 'missing-repo'
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('generate-map', 'intake', (Join-Path $scratch 'nope.yaml'),
                '--project-root', $projectRoot, '--workdir', $workdir,
                '--repository-root', $missingRepo, '--repository-scope', 'local',
                '--allowed-root', $scratch)
        $passed = Assert-CliContract -Id 'TC-B07' -CaseGroup 'B' -Purpose '仓库根校验早于请求校验' -Result $r -ExpectExit 2 -ExpectCode 'PATH_NOT_FOUND'
        if ($passed) {
            if ($r.StdErr -match [regex]::Escape('missing-repo')) {
                Add-CaseResult -Id 'TC-B07b' -Group 'B' -Purpose '错误指向缺失的仓库根' -Status 'PASS'
            }
            else {
                Add-CaseResult -Id 'TC-B07b' -Group 'B' -Purpose '错误指向缺失的仓库根' -Status 'FAIL' -Expected 'message 含 missing-repo' -Actual $r.StdErr
            }
            # 漂移 D5 证据：构造函数 mkdir 早于 repository_root 校验，命令失败但目录已落地
            if (Test-Path -LiteralPath $workdir) {
                Add-CaseResult -Id 'TC-B07c' -Group 'B' -Purpose 'D5 副作用：失败命令仍创建 workdir' -Status 'DRIFT' -Note '构造函数 mkdir 早于 repository_root 校验'
            }
            else {
                Add-CaseResult -Id 'TC-B07c' -Group 'B' -Purpose 'D5 副作用：失败命令仍创建 workdir' -Status 'PASS' -Note '副作用已消除，可关闭 D5'
            }
        }
    }

    Invoke-Case 'TC-B08' 'B' '相对 workdir 按 project-root 解析' {
        # workdir 以 base_root=project_root 解析，因此相对值是合法的；
        # 此处用不存在的请求文件作为中性失败点，隔离出 workdir 的解析语义。
        $relativeWorkdir = 'b08-run'
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('generate-map', 'intake', (Join-Path $scratch 'nope.yaml'),
                '--project-root', $projectRoot, '--workdir', $relativeWorkdir,
                '--repository-root', $projectRoot, '--repository-scope', 'local',
                '--allowed-root', $scratch)
        $passed = Assert-CliContract -Id 'TC-B08' -CaseGroup 'B' -Purpose '相对 workdir 按 project-root 解析' -Result $r -ExpectExit 2 -ExpectCode 'PATH_NOT_FOUND'
        if ($passed) {
            $expectedWorkdir = Join-Path $projectRoot $relativeWorkdir
            if (Test-Path -LiteralPath $expectedWorkdir) {
                Add-CaseResult -Id 'TC-B08b' -Group 'B' -Purpose 'workdir 落在 project-root 下' -Status 'PASS' -Note "相对值合法：$relativeWorkdir -> $expectedWorkdir"
            }
            else {
                Add-CaseResult -Id 'TC-B08b' -Group 'B' -Purpose 'workdir 落在 project-root 下' -Status 'FAIL' -Expected $expectedWorkdir -Actual '未创建'
            }
        }
    }
}

# ═════════════════════════════════════════════
# C 组：宿主会话行为
# ═════════════════════════════════════════════
if ($Group -contains 'C') {
    Write-CartoStep 'C 组：宿主会话行为（6 条）'

    $stateRoot = Join-Path $scratch 'no-state-run'

    Invoke-Case 'TC-C01' 'C' '模板路由无状态时先探测' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('create-template', 'status', '--project-root', $projectRoot,
                '--workdir', $stateRoot, '--allowed-root', $scratch)
        [void](Assert-CliContract -Id 'TC-C01' -CaseGroup 'C' -Purpose '模板路由无状态时先探测' -Result $r -ExpectExit 2 -ExpectCode 'JOB_STATE_NOT_FOUND')
    }

    Invoke-Case 'TC-C02' 'C' '生成路由无状态时先探测' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('generate-map', 'status', '--project-root', $projectRoot,
                '--workdir', (Join-Path $scratch 'no-state-run-map'),
                '--repository-root', $projectRoot, '--repository-scope', 'local',
                '--allowed-root', $scratch)
        [void](Assert-CliContract -Id 'TC-C02' -CaseGroup 'C' -Purpose '生成路由无状态时先探测' -Result $r -ExpectExit 2 -ExpectCode 'JOB_STATE_NOT_FOUND')
    }

    Invoke-Case 'TC-C03' 'C' '无参数调用给出用法而非崩溃' {
        $r = Invoke-CartoProcess -FileName $resolvedPython -Arguments @($cli) -TimeoutSeconds 60
        if ($r.ExitCode -eq 2 -and ($r.StdErr -match 'required')) {
            Add-CaseResult -Id 'TC-C03' -Group 'C' -Purpose '无参数调用给出用法而非崩溃' -Status 'PASS' -Note 'argparse usage，非结构化 JSON'
        }
        else {
            Add-CaseResult -Id 'TC-C03' -Group 'C' -Purpose '无参数调用给出用法而非崩溃' -Status 'FAIL' -Expected 'exit=2 且 stderr 含 required' -Actual "exit=$($r.ExitCode)"
        }
    }

    Invoke-Case 'TC-C04' 'C' '意图解析不谎报成功' {
        $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 120 `
            -Arguments @('intent', 'resolve', $policy, '--allowed-root', $repoRoot)
        if ($r.ExitCode -ne 0 -or $null -eq $r.Json) {
            Add-CaseResult -Id 'TC-C04' -Group 'C' -Purpose '意图解析不谎报成功' -Status 'FAIL' -Expected 'exit=0 且返回结构化 intent' -Actual "exit=$($r.ExitCode)"
        }
        else {
            $intent = $r.Json.intent
            $intentStatus = [string]$intent.intent_status
            $readiness = [string]$intent.readiness_status
            if ($intentStatus -eq 'unsupported' -and $readiness -eq 'missing_information' -and @($intent.missing_items).Count -gt 0) {
                Add-CaseResult -Id 'TC-C04' -Group 'C' -Purpose '意图解析不谎报成功' -Status 'PASS' `
                    -Note "exit=0 但 intent_status=$intentStatus / readiness=$readiness，判据在响应体（漂移 D3）"
            }
            else {
                Add-CaseResult -Id 'TC-C04' -Group 'C' -Purpose '意图解析不谎报成功' -Status 'FAIL' `
                    -Expected 'intent_status=unsupported 且 readiness_status=missing_information' `
                    -Actual "intent_status=$intentStatus readiness=$readiness"
            }
        }
    }

    Invoke-Case 'TC-C05' 'C' '只读命令副作用可观测' {
        if ((Test-Path -LiteralPath $stateRoot) -and (Test-Path -LiteralPath (Join-Path $stateRoot '.workflow.lock'))) {
            Add-CaseResult -Id 'TC-C05' -Group 'C' -Purpose '只读命令副作用可观测' -Status 'DRIFT' `
                -Note 'status 创建了 run 目录与 .workflow.lock（漂移 D5，清单要求演练后清理）'
        }
        elseif (Test-Path -LiteralPath $stateRoot) {
            Add-CaseResult -Id 'TC-C05' -Group 'C' -Purpose '只读命令副作用可观测' -Status 'DRIFT' -Note 'status 创建了 run 目录'
        }
        else {
            Add-CaseResult -Id 'TC-C05' -Group 'C' -Purpose '只读命令副作用可观测' -Status 'PASS' -Note '只读命令已无磁盘副作用，可关闭 D5'
        }
    }

    Add-CaseResult -Id 'TC-C06' -Group 'C' -Purpose 'mutating 持锁期间 status 行为' -Status 'SKIP' `
        -Note '需并发对象：在 preview/freeze 执行中另开会话调 status，预期 10 秒锁超时；建议在步骤 6 演练中人工观测'
}

# ═════════════════════════════════════════════
# D 组：文档 ↔ 实现一致性
# ═════════════════════════════════════════════
if ($Group -contains 'D') {
    Write-CartoStep 'D 组：文档与实现一致性（5 条）'

    foreach ($item in @(
            @{ Id = 'TC-D01'; Route = 'edit-native-map' },
            @{ Id = 'TC-D02'; Route = 'curate-catalog' }
        )) {
        Invoke-Case $item.Id 'D' "未开放路由 $($item.Route)" {
            $route = $item.Route
            $id = $item.Id
            $r = Invoke-CartoCli -Python $resolvedPython -Cli $cli -TimeoutSeconds 60 -Arguments @($route)
            if ($r.ExitCode -eq 2 -and $r.Code -eq 'CAPABILITY_NOT_AVAILABLE') {
                Add-CaseResult -Id $id -Group 'D' -Purpose "未开放路由 $route 返回结构化错误" -Status 'PASS' -Note '漂移 D1 已修复'
            }
            elseif ($r.ExitCode -eq 2 -and $null -eq $r.Json) {
                Add-CaseResult -Id $id -Group 'D' -Purpose "未开放路由 $route 返回结构化错误" -Status 'DRIFT' `
                    -Expected 'stderr {"ok":false,"code":"CAPABILITY_NOT_AVAILABLE"}' -Actual 'argparse usage 文本' `
                    -Note '漂移 D1：routing.md 承诺与实现不符'
            }
            else {
                Add-CaseResult -Id $id -Group 'D' -Purpose "未开放路由 $route 返回结构化错误" -Status 'FAIL' `
                    -Expected 'exit=2' -Actual "exit=$($r.ExitCode) code=$($r.Code)"
            }
        }
    }

    Invoke-Case 'TC-D03' 'D' '路由注册表是否真实接入' {
        $scriptsDir = Join-Path $skillRoot 'scripts'
        $hits = @(Get-ChildItem -LiteralPath $scriptsDir -Recurse -Filter '*.py' -ErrorAction SilentlyContinue |
                Select-String -Pattern 'RouteRegistry' -SimpleMatch -ErrorAction SilentlyContinue)
        $outsideDefinition = @($hits | Where-Object { $_.Path -notmatch 'router\.py$' })
        if ($hits.Count -gt 0 -and $outsideDefinition.Count -eq 0) {
            Add-CaseResult -Id 'TC-D03' -Group 'D' -Purpose '路由注册表是否真实接入' -Status 'DRIFT' `
                -Note '漂移 D2：RouteRegistry 仅在 router.py 内定义，全仓库零引用'
        }
        elseif ($outsideDefinition.Count -gt 0) {
            Add-CaseResult -Id 'TC-D03' -Group 'D' -Purpose '路由注册表是否真实接入' -Status 'PASS' -Note "已被 $($outsideDefinition.Count) 处引用，D2 可关闭"
        }
        else {
            Add-CaseResult -Id 'TC-D03' -Group 'D' -Purpose '路由注册表是否真实接入' -Status 'PASS' -Note '定义已移除，文档与实现一致'
        }
    }

    Invoke-Case 'TC-D04' 'D' 'carto 控制台脚本可用性' {
        $cartoCommand = Get-Command carto -ErrorAction SilentlyContinue
        if (-not $cartoCommand) {
            Add-CaseResult -Id 'TC-D04' -Group 'D' -Purpose 'carto 控制台脚本可用性' -Status 'SKIP' `
                -Note "未安装；如需覆盖请执行 & `"$resolvedPython`" -m pip install -e `"$repoRoot`""
        }
        else {
            # carto 是控制台脚本，直接作为可执行文件调用并校验它确实是 carto_core 的入口。
            # PATH 上的 carto 可能是同名 npm 包等不同工具，必须用它能否产出本项目 JSON 来区分。
            $direct = Invoke-CartoProcess -FileName $cartoCommand.Source -Arguments @('schema', 'check') -TimeoutSeconds 180
            if ($direct.ExitCode -eq 0 -and $direct.StdOut -match '"ok": true') {
                Add-CaseResult -Id 'TC-D04' -Group 'D' -Purpose 'carto 控制台脚本可用性' -Status 'PASS' -Note $cartoCommand.Source
            }
            else {
                Add-CaseResult -Id 'TC-D04' -Group 'D' -Purpose 'carto 控制台脚本可用性' -Status 'SKIP' `
                    -Note "PATH 上的 carto（$($cartoCommand.Source)）非本项目控制台脚本（carto schema check 未返回本项目 JSON，可能为同名 npm 包）；未安装 carto_core 入口"
            }
        }
    }

    Invoke-Case 'TC-D05' 'D' 'SKILL.md 声明的测试入口' {
        $skillMd = Join-Path $skillRoot 'SKILL.md'
        $declared = @(Get-Content -LiteralPath $skillMd -Encoding UTF8 | Select-String -Pattern 'unittest discover -s (\S+)' -AllMatches)
        if ($declared.Count -eq 0) {
            Add-CaseResult -Id 'TC-D05' -Group 'D' -Purpose 'SKILL.md 声明的测试入口' -Status 'FAIL' -Expected 'SKILL.md 含 unittest discover 入口' -Actual '未找到'
        }
        elseif (-not (Test-Path -LiteralPath $testsRoot)) {
            Add-CaseResult -Id 'TC-D05' -Group 'D' -Purpose 'SKILL.md 声明的测试入口' -Status 'FAIL' -Expected "测试目录存在: $testsRoot" -Actual '不存在'
        }
        elseif (-not $IncludeUnitTest) {
            Add-CaseResult -Id 'TC-D05' -Group 'D' -Purpose 'SKILL.md 声明的测试入口' -Status 'PASS' `
                -Note '结构性检查通过；全量回归由 Invoke-CartoPreflight.ps1 执行，加 -IncludeUnitTest 可在此重跑'
        }
        else {
            $t = Invoke-CartoProcess -FileName $resolvedPython -WorkingDirectory $repoRoot -TimeoutSeconds 1800 `
                -Arguments @('-m', 'unittest', 'discover', '-s', $testsRoot)
            if ($t.ExitCode -eq 0 -and ($t.StdErr + $t.StdOut) -match '(?m)^OK') {
                Add-CaseResult -Id 'TC-D05' -Group 'D' -Purpose 'SKILL.md 声明的测试入口' -Status 'PASS' -Note '全量回归 OK'
            }
            else {
                Add-CaseResult -Id 'TC-D05' -Group 'D' -Purpose 'SKILL.md 声明的测试入口' -Status 'FAIL' -Expected 'unittest OK' -Actual "exit=$($t.ExitCode)"
            }
        }
    }
}

# ═════════════════════════════════════════════
# 汇总
# ═════════════════════════════════════════════
$passCount = @($script:Results | Where-Object { $_.Status -eq 'PASS' }).Count
$failCount = @($script:Results | Where-Object { $_.Status -eq 'FAIL' }).Count
$driftCount = @($script:Results | Where-Object { $_.Status -eq 'DRIFT' }).Count
$skipCount = @($script:Results | Where-Object { $_.Status -eq 'SKIP' }).Count

$payload = [pscustomobject]@{
    executed_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    python      = $resolvedPython
    groups      = $Group
    strict      = [bool]$Strict
    summary     = [pscustomobject]@{ pass = $passCount; fail = $failCount; drift = $driftCount; skip = $skipCount }
    results     = $script:Results
}
$reportPath = Write-CartoReport -RepoRoot $repoRoot -Prefix 'host-cases' -Payload $payload

Write-CartoStep '汇总'
Write-Host ("  PASS={0}  FAIL={1}  DRIFT={2}  SKIP={3}" -f $passCount, $failCount, $driftCount, $skipCount)
Write-CartoInfo "报告: $reportPath"

# 清理副作用目录
if ($KeepArtifacts) {
    Write-CartoWarn "已按 -KeepArtifacts 保留沙箱: $scratch"
}
else {
    try {
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction Stop
        Write-CartoOk "沙箱已清理: $scratch"
    }
    catch { Write-CartoWarn "沙箱清理失败，请手工删除: $scratch" }
}

$effectiveFail = $failCount
if ($Strict) { $effectiveFail += $driftCount }

if ($effectiveFail -gt 0) {
    Write-CartoFail "存在 $effectiveFail 条未通过用例"
    if ($Strict -and $driftCount -gt 0) { Write-CartoInfo 'Strict 模式下已登记漂移也计为失败' }
    exit 1
}

if ($driftCount -gt 0) {
    Write-CartoWarn "全部通过（另有 $driftCount 条已登记漂移，见清单第五章 D1/D2/D5）"
}
else { Write-CartoOk '全部用例通过，且无已登记漂移' }

exit 0

