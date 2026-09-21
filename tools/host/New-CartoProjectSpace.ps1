#requires -Version 5.1
<#
.SYNOPSIS
    为 carto-agent 真实 CLI 运行创建项目空间脚手架。

.DESCRIPTION
    carto CLI 不像单元测试那样用系统临时目录自动清理——intake 起就要求显式指定
    --project-root / --workdir / --repository-root，所有产物落在指定位置，由
    PathGuard 限制在 --allowed-root 内。本脚本创建约定的目录结构、写一份 README
    说明各子目录用途与规范 CLI 路径，并把规范路径记入 carto-host.env.json，
    供宿主 Agent 与人工运行复用。

    默认根目录在仓库内 <repo>\projects\（你指定的路径）；如想放仓库外（git 天然
    看不到、更干净），用 -Root 指定，例如 -Root D:\IdeaProjects\github\code-reviewer\projects。

    产物归属（对应 carto 工作流）：
      template-repository\  共享不可变模板仓库 + 权威索引（create-template publish 写入；generate-map 读取）
      <project>\project\    --project-root：source-manifest.yaml + data\*.geojson
      <project>\runs\       --workdir 基：每个 run 一个子目录（状态/回执/staging/generation）
      <project>\approvals\  T1/TP/G1/G2 审批回执 YAML + nonce sqlite
      <project>\output\     最终成果 A3 SVG/PNG/PDF

.PARAMETER Root
    项目空间根。缺省 <repo>\projects。

.PARAMETER ProjectName
    单个地图项目的目录名，缺省 carto-flood-a3。

.PARAMETER Force
    目录已存在时仍补齐缺失子目录与 README（不删除已有内容）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\New-CartoProjectSpace.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\host\New-CartoProjectSpace.ps1 -Root D:\IdeaProjects\github\code-reviewer\projects
#>

[CmdletBinding()]
param(
    [string]$Root = '',
    [string]$ProjectName = 'carto-flood-a3',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

$repoRoot = Get-CartoRepoRoot
if (-not $Root) { $Root = Join-Path $repoRoot 'projects' }
$Root = [System.IO.Path]::GetFullPath($Root)

Write-CartoBanner -Title 'Carto 项目空间脚手架' -Subtitle 'New-CartoProjectSpace.ps1'
Write-CartoOk "项目空间根: $Root"
Write-CartoInfo "地图项目: $ProjectName"

# ── 1. 创建目录结构 ──────────────────────────
Write-CartoStep '1/3 创建目录结构'
$repositoryRoot = Join-Path $Root 'template-repository'
$projectDir = Join-Path $Root $ProjectName
$projectRoot = Join-Path $projectDir 'project'
$dataDir = Join-Path $projectRoot 'data'
$workdirBase = Join-Path $projectDir 'runs'
$approvalsDir = Join-Path $projectDir 'approvals'
$outputDir = Join-Path $projectDir 'output'

$layout = [ordered]@{
    template_repository = $repositoryRoot
    project_root         = $projectRoot
    data                 = $dataDir
    workdir_base         = $workdirBase
    approvals            = $approvalsDir
    output               = $outputDir
}
foreach ($path in $layout.Values) {
    if (-not (Test-Path -LiteralPath $path)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        Write-CartoOk "新建: $path"
    }
    else { Write-CartoInfo "已存在: $path" }
}

# ── 2. README（子目录用途 + 规范 CLI 路径 + PathGuard 约束）──
Write-CartoStep '2/3 写 README'
$readme = Join-Path $Root 'README.md'
$readmeContent = @"
# Carto 项目空间

由 ``tools/host/New-CartoProjectSpace.ps1`` 生成。carto CLI 真实运行（区别于单元测试）
从 ``intake`` 起即显式要求 ``--project-root`` / ``--workdir`` / ``--repository-root``，
所有产物落在下面这些目录，由 PathGuard 限制在 ``--allowed-root`` 内。

## 目录结构

| 目录 | 用途 | 对应 CLI 参数 |
|---|---|---|
| ``template-repository\`` | 共享不可变模板仓库 + 权威索引（``create-template publish`` 写入；``generate-map`` 读取） | ``--repository-root`` |
| ``$ProjectName\project\`` | 项目根：``source-manifest.yaml`` + ``data\*.geojson`` | ``--project-root`` |
| ``$ProjectName\project\data\`` | 合成/业务 GeoJSON 数据源 | 被 source-manifest 引用 |
| ``$ProjectName\runs\`` | 每个 run 一个子目录：状态、回执、staging、generation 产物 | ``--workdir`` 基 |
| ``$ProjectName\approvals\`` | T1/TP/G1/G2 审批回执 YAML + ``nonce`` sqlite 防重放库 | ``--approval`` / ``--nonce-db`` |
| ``$ProjectName\output\`` | 最终成果 A3 横版 SVG/PNG/PDF | 渲染产物输出 |

## 规范路径变量（供宿主 Agent 与人工运行复用）

```powershell
`$PS  = "$Root"                              # 项目空间根 = --allowed-root 之一
`$PR  = "$projectRoot"                       # --project-root
`$REPO= "$repositoryRoot"                    # --repository-root
`$RUN  = "$workdirBase\template-one"          # --workdir（模板侧）
`$RUN2 = "$workdirBase\map-one"               # --workdir（生成侧）
`$APP  = "$approvalsDir"                     # 审批回执与 nonce 库目录
`$OUT  = "$outputDir"                        # 成果输出
`$PY   = "$((Get-CartoEnvPython -RepoRoot $repoRoot))"   # Python 解释器
`$C    = "skills/carto-agent/scripts/carto.py"
```

## 规范 CLI 调用（占位，审批回执需另行签发）

模板侧（发布到 template-repository）：
```
`$PY `$C create-template analyze  `<request.yaml> --project-root `$PR --workdir `$RUN  --allowed-root `$PS --allowed-root `$PR
`$PY `$C create-template brief    `<request.yaml> --project-root `$PR --workdir `$RUN  --allowed-root `$PS --allowed-root `$PR
`$PY `$C create-template author   `<request.yaml> --approval `$APP\t1.yaml --key-env CARTO_APPROVAL_HMAC_KEY --nonce-db `$APP\nonces.sqlite3 --policy-id carto-security --issuer trusted-local --project-root `$PR --workdir `$RUN --allowed-root `$PS --allowed-root `$PR
`$PY `$C create-template validate `<request.yaml> --attestation-key-env CARTO_RENDER_ATTESTATION_KEY --project-root `$PR --workdir `$RUN --allowed-root `$PS --allowed-root `$PR
`$PY `$C create-template publish  `<request.yaml> --approval `$APP\tp.yaml --repository-root `$REPO --repository-scope local --idempotency-key `<key> --key-env CARTO_APPROVAL_HMAC_KEY --attestation-key-env CARTO_RENDER_ATTESTATION_KEY --nonce-db `$APP\nonces.sqlite3 --policy-id carto-security --issuer trusted-local --project-root `$PR --workdir `$RUN --allowed-root `$PS --allowed-root `$PR
```

生成侧（从 template-repository 取已发布模板）：
```
`$PY `$C generate-map intake  `<generate-request.yaml> --project-root `$PR --workdir `$RUN2 --repository-root `$REPO --repository-scope local --allowed-root `$PS --allowed-root `$PR
`$PY `$C generate-map brief    `<request> --project-root `$PR --workdir `$RUN2 --repository-root `$REPO --repository-scope local --allowed-root `$PS --allowed-root `$PR
`$PY `$C generate-map compile  `<request> --approval `$APP\g1.yaml --key-env CARTO_APPROVAL_HMAC_KEY --nonce-db `$APP\nonces.sqlite3 --policy-id carto-security --issuer trusted-local --project-root `$PR --workdir `$RUN2 --repository-root `$REPO --repository-scope local --allowed-root `$PS --allowed-root `$PR
`$PY `$C generate-map preview  `<request> --attestation-key-env CARTO_RENDER_ATTESTATION_KEY --project-root `$PR --workdir `$RUN2 --repository-root `$REPO --repository-scope local --allowed-root `$PS --allowed-root `$PR
`$PY `$C generate-map freeze   `<request> --approval `$APP\g2.yaml --key-env CARTO_APPROVAL_HMAC_KEY --attestation-key-env CARTO_RENDER_ATTESTATION_KEY --nonce-db `$APP\nonces.sqlite3 --policy-id carto-security --issuer trusted-local --project-root `$PR --workdir `$RUN2 --repository-root `$REPO --repository-scope local --allowed-root `$PS --allowed-root `$PR
```

## 约束（必读）

- **路径全绝对**：``--project-root`` / ``--repository-root`` / ``--allowed-root`` 必须绝对路径；``--workdir`` 可相对（按 project-root 解析）。
- **PathGuard**：所有文件访问必须在某个 ``--allowed-root`` 内。本空间根 ``$PS`` 覆盖 project 与 repository；数据在 ``$PR\data``；中文字体在 ``C:\Windows\Fonts``，渲染步骤需追加 ``--allowed-root C:\Windows\Fonts``。
- **审批门禁**：``author``/``publish``/``compile``/``freeze`` 需 T1/TP/G1/G2 回执，由独立审批者签发，宿主 Agent 无权自签。未到审批的步骤只能做 ``analyze``/``brief``/``intake``。
- **不可变产物**：``template-repository`` 与 ``MapSpecLock`` 是 create-once，内容不可覆盖；重跑请换新 run 子目录或新 idempotency-key。
- **不在 git 内**：本目录已加入 ``.gitignore``（``projects/``），产物与回执不入库。

## 重生成

```powershell
powershell -ExecutionPolicy Bypass -File tools\host\New-CartoProjectSpace.ps1 -Force
# 或换根（仓库外同级）：
powershell -ExecutionPolicy Bypass -File tools\host\New-CartoProjectSpace.ps1 -Root D:\IdeaProjects\github\code-reviewer\projects
```
"@
if ((-not (Test-Path -LiteralPath $readme)) -or $Force) {
    Set-Content -LiteralPath $readme -Value $readmeContent -Encoding UTF8
    Write-CartoOk "README 已写: $readme"
}
else { Write-CartoInfo "README 已存在，跳过（加 -Force 覆盖）" }

# ── 3. 记入 carto-host.env.json ──────────────
Write-CartoStep '3/3 记录规范路径到 carto-host.env.json'
[void](Write-CartoEnv -RepoRoot $repoRoot -Values @{
        project_space = [ordered]@{
            root             = $Root
            project_name     = $ProjectName
            repository_root  = $repositoryRoot
            project_root     = $projectRoot
            data             = $dataDir
            workdir_base     = $workdirBase
            approvals        = $approvalsDir
            output           = $outputDir
            allowed_root     = $Root
            inside_repo      = ($Root.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase))
        }
    })
$envPath = Get-CartoEnvPath -RepoRoot $repoRoot
Write-CartoOk "规范路径已记入: $envPath"

Write-CartoStep '结果'
Write-CartoOk "项目空间就绪: $Root"
Write-CartoInfo "下一步：把 source-manifest.yaml 与 data\*.geojson 放进 $dataDir，即可按 README 的规范 CLI 运行"
Write-CartoInfo "宿主 Agent 可读 carto-host.env.json 的 project_space 字段获取规范路径"

exit 0
