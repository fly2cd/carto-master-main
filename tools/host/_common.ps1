#requires -Version 5.1
<#
.SYNOPSIS
    Carto 宿主环境脚本共享函数库。

.DESCRIPTION
    本文件不单独执行，由 Bootstrap-CartoHost.ps1 / Set-CartoBaseEnv.ps1 /
    Install-CartoSkill.ps1 / Invoke-CartoPreflight.ps1 / Invoke-CartoHostCases.ps1
    通过 dot-source 引入。

    兼容性目标：Windows PowerShell 5.1（不使用三元运算符、?? 、ForEach -Parallel 等 PS7 语法）。

.NOTES
    所有子进程调用统一走 Invoke-CartoProcess，避免 PowerShell 把子进程 stderr
    包装成 NativeCommandError 而干扰退出码判定。
#>

$script:CartoCommonRoot = $PSScriptRoot

# 不主动修改 [Console]::OutputEncoding：本机控制台为 GBK，强制改为 UTF-8
# 会让宿主会话（以及捕获子进程输出的父终端）出现中文乱码。
# CLI 输出统一由 Invoke-CartoProcess 以 UTF-8 显式捕获，与控制台编码无关。

# ─────────────────────────────────────────────
# 输出
# ─────────────────────────────────────────────

function Write-CartoStep { param([string]$Message) Write-Host ''; Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-CartoOk   { param([string]$Message) Write-Host "  [OK]   $Message" -ForegroundColor Green }
function Write-CartoInfo { param([string]$Message) Write-Host "  [INFO] $Message" }
function Write-CartoWarn { param([string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-CartoFail { param([string]$Message) Write-Host "  [FAIL] $Message" -ForegroundColor Red }

function Write-CartoBanner {
    param([string]$Title, [string]$Subtitle = '')
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor DarkCyan
    Write-Host " $Title" -ForegroundColor Cyan
    if ($Subtitle) { Write-Host " $Subtitle" -ForegroundColor DarkGray }
    Write-Host ('=' * 72) -ForegroundColor DarkCyan
}

# ─────────────────────────────────────────────
# 路径
# ─────────────────────────────────────────────

function Get-CartoRepoRoot {
    param([string]$StartDir = $script:CartoCommonRoot)

    $dir = Get-Item -LiteralPath $StartDir
    while ($null -ne $dir) {
        $hasProject = Test-Path -LiteralPath (Join-Path $dir.FullName 'pyproject.toml')
        $hasSkill = Test-Path -LiteralPath (Join-Path $dir.FullName 'skills\carto-agent\SKILL.md')
        if ($hasProject -and $hasSkill) { return $dir.FullName }
        $dir = $dir.Parent
    }
    throw '无法定位仓库根目录：需同时包含 pyproject.toml 与 skills\carto-agent\SKILL.md'
}

function Get-CartoSkillRoot { param([string]$RepoRoot) Join-Path $RepoRoot 'skills\carto-agent' }
function Get-CartoCliPath   { param([string]$RepoRoot) Join-Path $RepoRoot 'skills\carto-agent\scripts\carto.py' }
function Get-CartoTestsRoot { param([string]$RepoRoot) Join-Path $RepoRoot 'skills\carto-agent\scripts\tests' }
function Get-CartoEnvPath   { param([string]$RepoRoot) Join-Path $RepoRoot 'tools\host\carto-host.env.json' }
function Get-CartoReportDir { param([string]$RepoRoot) Join-Path $RepoRoot 'tools\host\reports' }

function Assert-CartoDir {
    param([string]$Path, [string]$What = '目录')
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$What 不存在: $Path" }
}

# ─────────────────────────────────────────────
# 子进程调用（统一入口）
# ─────────────────────────────────────────────

function ConvertTo-CartoArgumentString {
    param([string[]]$Arguments)
    $parts = @()
    foreach ($item in $Arguments) {
        if ($null -eq $item) { continue }
        $text = [string]$item
        if ($text -match '[\s"]') { $parts += ('"' + ($text -replace '"', '\"') + '"') }
        else { $parts += $text }
    }
    return ($parts -join ' ')
}

function Invoke-CartoProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FileName,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 900,
        [string]$WorkingDirectory = '',
        [System.Text.Encoding]$OutputEncoding = $null
    )

    if ($null -eq $OutputEncoding) { $OutputEncoding = [System.Text.Encoding]::UTF8 }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FileName
    $psi.Arguments = (ConvertTo-CartoArgumentString $Arguments)
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    # 重定向以便解析输出与保留退出码；解码编码必须与子进程实际写出的编码一致：
    #   Python 子进程 -> UTF-8（carto CLI 输出为 JSON，非 ASCII 字符极少）
    #   PowerShell 子进程 -> 系统 ANSI 代码页（本机为 GBK），否则中文会变 '?'
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = $OutputEncoding
    $psi.StandardErrorEncoding = $OutputEncoding
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi

    try { [void]$process.Start() }
    catch {
        return [pscustomobject]@{
            ExitCode = -1; StdOut = ''; TimedOut = $false
            StdErr   = "无法启动进程 '$FileName': $($_.Exception.Message)"
        }
    }

    # 先发起异步读取再等待退出，避免 stderr 缓冲区写满导致死锁
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()

    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $process.Kill() } catch { }
        return [pscustomobject]@{
            ExitCode = -1; StdOut = $stdoutTask.GetAwaiter().GetResult()
            StdErr   = "TIMEOUT after $TimeoutSeconds s"; TimedOut = $true
        }
    }

    return [pscustomobject]@{
        ExitCode = $process.ExitCode
        StdOut   = $stdoutTask.GetAwaiter().GetResult()
        StdErr   = $stderrTask.GetAwaiter().GetResult()
        TimedOut = $false
    }
}

function Invoke-CartoCli {
    <#
        调用 carto.py 并解析 CLI 输出契约：
          成功 -> 退出码 0，stdout 为 {"ok":true,...}
          失败 -> 退出码 2，stderr 为 {"ok":false,"code":...,"message":...}
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Cli,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 900,
        [string]$WorkingDirectory = ''
    )

    $all = @($Cli) + $Arguments
    $raw = Invoke-CartoProcess -FileName $Python -Arguments $all -TimeoutSeconds $TimeoutSeconds -WorkingDirectory $WorkingDirectory

    $json = $null
    $text = $raw.StdOut
    if ([string]::IsNullOrWhiteSpace($text)) { $text = $raw.StdErr }
    if (-not [string]::IsNullOrWhiteSpace($text)) {
        $trimmed = $text.Trim()
        if ($trimmed.StartsWith('{')) {
            try { $json = $trimmed | ConvertFrom-Json } catch { $json = $null }
        }
    }

    $code = $null
    if ($null -ne $json -and $json.PSObject.Properties['code']) { $code = [string]$json.code }

    return [pscustomobject]@{
        ExitCode = $raw.ExitCode
        StdOut   = $raw.StdOut
        StdErr   = $raw.StdErr
        TimedOut = $raw.TimedOut
        Json     = $json
        Code     = $code
        Ok       = ($raw.ExitCode -eq 0 -and $null -ne $json -and $json.ok -eq $true)
    }
}

# ─────────────────────────────────────────────
# Python 解释器探测
# ─────────────────────────────────────────────

function Get-CartoPythonVersionText {
    param([Parameter(Mandatory = $true)][string]$Python)
    $result = Invoke-CartoProcess -FileName $Python -TimeoutSeconds 30 `
        -Arguments @('-c', 'import sys;print(''%d.%d'' % sys.version_info[:2])')
    if ($result.ExitCode -ne 0) { return $null }
    $text = ($result.StdOut).Trim()
    if ($text -match '^\d+\.\d+$') { return $text }
    return $null
}

function Test-CartoPythonCandidate {
    <# 返回 $true 表示可执行且版本 >= 3.11，且不是微软商店占位符 #>
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    if ($Path -match 'WindowsApps') { return $false }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $version = Get-CartoPythonVersionText -Python $Path
    if ($null -eq $version) { return $false }
    $parts = $version.Split('.')
    $major = [int]$parts[0]; $minor = [int]$parts[1]
    if ($major -lt 3) { return $false }
    if ($major -eq 3 -and $minor -lt 11) { return $false }
    return $true
}

function Get-CartoPythonCandidates {
    $list = New-Object System.Collections.ArrayList

    if ($env:CARTO_PYTHON) { [void]$list.Add($env:CARTO_PYTHON) }

    foreach ($name in @('python', 'python3', 'python.exe')) {
        foreach ($cmd in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($cmd.Source) { [void]$list.Add($cmd.Source) }
        }
    }

    # py 启动器登记的解释器
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $listed = Invoke-CartoProcess -FileName $launcher.Source -Arguments @('-0p') -TimeoutSeconds 30
        if ($listed.ExitCode -eq 0) {
            foreach ($line in ($listed.StdOut -split "`r?`n")) {
                if ($line -match '([A-Za-z]:\\.*python\.exe)') { [void]$list.Add($Matches[1].Trim()) }
            }
        }
    }

    # 由 conda 可执行文件反推 base 环境（conda 可能装在非系统盘）
    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($conda -and $conda.Source) {
        try {
            $condaRoot = Split-Path -Path (Split-Path -Path $conda.Source -Parent) -Parent
            [void]$list.Add((Join-Path $condaRoot 'python.exe'))
        }
        catch { }
    }

    # 常见安装位置：遍历所有就绪的固定驱动器，避免 conda 装在 D: 而 $env:ProgramData 指向 C: 时漏掉
    $driveLetters = @()
    try {
        foreach ($drive in [System.IO.DriveInfo]::GetDrives()) {
            if ($drive.IsReady -and $drive.DriveType -eq [System.IO.DriveType]::Fixed) {
                $driveLetters += $drive.Name.TrimEnd('\')
            }
        }
    }
    catch { $driveLetters += $env:SystemDrive.TrimEnd('\') }
    if ($driveLetters.Count -eq 0) { $driveLetters += $env:SystemDrive.TrimEnd('\') }

    foreach ($letter in $driveLetters) {
        foreach ($relative in @(
                'ProgramData\miniconda3\python.exe',
                'ProgramData\anaconda3\python.exe',
                'miniconda3\python.exe',
                'anaconda3\python.exe',
                'Python313\python.exe', 'Python312\python.exe', 'Python311\python.exe'
            )) {
            [void]$list.Add((Join-Path $letter $relative))
        }
    }

    foreach ($root in @(
            (Join-Path $env:USERPROFILE 'miniconda3\python.exe'),
            (Join-Path $env:USERPROFILE 'anaconda3\python.exe')
        )) { [void]$list.Add($root) }

    foreach ($pattern in @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'),
            (Join-Path $env:USERPROFILE '.conda\envs\*\python.exe'),
            (Join-Path $env:ProgramData 'miniconda3\envs\*\python.exe')
        )) {
        foreach ($hit in @(Resolve-Path -Path $pattern -ErrorAction SilentlyContinue)) { [void]$list.Add($hit.Path) }
    }
    foreach ($letter in $driveLetters) {
        $pattern = Join-Path $letter 'ProgramData\miniconda3\envs\*\python.exe'
        foreach ($hit in @(Resolve-Path -Path $pattern -ErrorAction SilentlyContinue)) { [void]$list.Add($hit.Path) }
    }

    $seen = @{}
    $unique = @()
    foreach ($item in $list) {
        if ([string]::IsNullOrWhiteSpace($item)) { continue }
        try { $full = [System.IO.Path]::GetFullPath($item) } catch { continue }
        $key = $full.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $unique += $full
    }
    return $unique
}

function Test-CartoPythonDependencies {
    <# 该解释器是否已具备项目声明的两个直接依赖 #>
    param([Parameter(Mandatory = $true)][string]$Python)
    $deps = Get-CartoDependencyStatus -Python $Python
    $jsonOk = ($deps.JsonSchema -ne 'MISSING' -and $deps.JsonSchema -ne 'UNKNOWN')
    $yamlOk = ($deps.PyYaml -ne 'MISSING' -and $deps.PyYaml -ne 'UNKNOWN')
    return ($jsonOk -and $yamlOk)
}

function Find-CartoPython {
    <#
        开发机常同时存在多个 conda 环境，因此不能只按“版本合格”取第一个：
        先在全部合格候选中优选已具备 jsonschema + PyYAML 的解释器，
        都不具备时才退回第一个合格候选（由调用方提示安装依赖）。
    #>
    param([string]$Preferred = '')

    if ($Preferred) {
        if (Test-CartoPythonCandidate -Path $Preferred) { return $Preferred }
        throw "指定的 Python 解释器不可用或版本低于 3.11: $Preferred"
    }

    $valid = @()
    foreach ($candidate in (Get-CartoPythonCandidates)) {
        if (Test-CartoPythonCandidate -Path $candidate) { $valid += $candidate }
    }
    if ($valid.Count -eq 0) { return $null }

    foreach ($candidate in $valid) {
        if (Test-CartoPythonDependencies -Python $candidate) { return $candidate }
    }
    return $valid[0]
}

function Get-CartoPythonDiagnosis {
    <# 列出全部合格候选及其依赖状况，用于失败时的修复提示 #>
    $rows = @()
    foreach ($candidate in (Get-CartoPythonCandidates)) {
        if (-not (Test-CartoPythonCandidate -Path $candidate)) { continue }
        $deps = Get-CartoDependencyStatus -Python $candidate
        $rows += [pscustomobject]@{
            Path       = $candidate
            Version    = (Get-CartoPythonVersionText -Python $candidate)
            JsonSchema = $deps.JsonSchema
            PyYaml     = $deps.PyYaml
        }
    }
    return $rows
}

# ─────────────────────────────────────────────
# 依赖与渲染能力
# ─────────────────────────────────────────────

function Get-CartoDependencyStatus {
    param([Parameter(Mandatory = $true)][string]$Python)

    $probe = 'import importlib.util as u;print((''jsonschema'' if u.find_spec(''jsonschema'') else ''MISSING'')+''|''+(''yaml'' if u.find_spec(''yaml'') else ''MISSING''))'
    $result = Invoke-CartoProcess -FileName $Python -Arguments @('-c', $probe) -TimeoutSeconds 60
    if ($result.ExitCode -ne 0) {
        return [pscustomobject]@{ JsonSchema = 'UNKNOWN'; PyYaml = 'UNKNOWN'; Versions = '' }
    }
    $parts = ($result.StdOut).Trim().Split('|')
    $jsonSchema = $parts[0]; $pyYaml = $parts[1]
    $versions = ''
    if ($jsonSchema -ne 'MISSING' -and $pyYaml -ne 'MISSING') {
        $versionProbe = 'import importlib.metadata as m;print(m.version(''jsonschema'')+''|''+m.version(''PyYAML''))'
        $versionResult = Invoke-CartoProcess -FileName $Python -Arguments @('-c', $versionProbe) -TimeoutSeconds 60
        if ($versionResult.ExitCode -eq 0) { $versions = ($versionResult.StdOut).Trim() }
    }
    return [pscustomobject]@{ JsonSchema = $jsonSchema; PyYaml = $pyYaml; Versions = $versions }
}

function Get-CartoRendererStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Cli
    )
    $result = Invoke-CartoCli -Python $Python -Cli $Cli -Arguments @('environment', 'probe-renderer') -TimeoutSeconds 300
    $info = [pscustomobject]@{
        Available = $false; Status = 'unknown'; Fingerprint = ''; Browser = ''; Node = ''
        Fonts = ''; ExitCode = $result.ExitCode; Code = $result.Code; Raw = $result
    }
    if ($null -eq $result.Json) { return $info }
    $env = $result.Json.environment
    if ($null -eq $env) { return $info }
    $info.Status = [string]$env.status
    $info.Fingerprint = [string]$env.fingerprint
    $info.Available = ($env.status -eq 'available')
    if ($env.renderer_profile) { $info.Browser = [string]$env.renderer_profile.browser_engine }
    if ($env.tools -and $env.tools.node) { $info.Node = [string]$env.tools.node.version }
    if ($env.chinese_fonts) { $info.Fonts = ($env.chinese_fonts -join ', ') }
    return $info
}

# ─────────────────────────────────────────────
# 环境配置文件（机器相关，已 gitignore）
# ─────────────────────────────────────────────

function Read-CartoEnv {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $path = Get-CartoEnvPath -RepoRoot $RepoRoot
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try { return (Get-Content -Raw -LiteralPath $path -Encoding UTF8 | ConvertFrom-Json) }
    catch { return $null }
}

function Write-CartoEnv {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][hashtable]$Values
    )
    $path = Get-CartoEnvPath -RepoRoot $RepoRoot
    $dir = Split-Path -Path $path -Parent
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    $current = Read-CartoEnv -RepoRoot $RepoRoot
    $merged = @{}
    if ($null -ne $current) {
        foreach ($property in $current.PSObject.Properties) { $merged[$property.Name] = $property.Value }
    }
    foreach ($key in $Values.Keys) { $merged[$key] = $Values[$key] }
    $merged['updated_at'] = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')

    # ConvertTo-Json 后统一写为 UTF8（PS5.1 会带 BOM，ConvertFrom-Json 可正常解析）
    ($merged | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $path -Encoding UTF8
    return $path
}

function Get-CartoEnvPython {
    <# 从环境文件取解释器；取不到则现场探测。返回 $null 表示未找到。 #>
    param([Parameter(Mandatory = $true)][string]$RepoRoot, [string]$Preferred = '')
    if ($Preferred) { return (Find-CartoPython -Preferred $Preferred) }
    $env = Read-CartoEnv -RepoRoot $RepoRoot
    if ($null -ne $env -and $env.PSObject.Properties['python']) {
        $recorded = [string]$env.python
        if ($recorded -and (Test-CartoPythonCandidate -Path $recorded)) { return $recorded }
    }
    return (Find-CartoPython)
}

# ─────────────────────────────────────────────
# 宿主 skills 目录
# ─────────────────────────────────────────────

function Get-CartoHostSkillsCandidates {
    $profileRoot = $env:USERPROFILE
    return @(
        # Windows 上 Hermes 的实际 profile 根是 %LOCALAPPDATA%\hermes，而非文档里写的 ~/.hermes
        [pscustomobject]@{ Host = 'Hermes Agent (Windows)'; Path = (Join-Path $env:LOCALAPPDATA 'hermes\skills') },
        [pscustomobject]@{ Host = 'Codex'; Path = (Join-Path $profileRoot '.codex\skills') },
        [pscustomobject]@{ Host = 'Hermes Agent'; Path = (Join-Path $profileRoot '.hermes\skills') },
        [pscustomobject]@{ Host = 'Claude Code'; Path = (Join-Path $profileRoot '.claude\skills') },
        [pscustomobject]@{ Host = 'Generic agents'; Path = (Join-Path $profileRoot '.agents\skills') },
        [pscustomobject]@{ Host = 'Qoder'; Path = (Join-Path $profileRoot '.qoder\skills') }
    )
}

function Resolve-CartoHostSkillsRoot {
    param([string]$Explicit = '')

    if ($Explicit) {
        $full = [System.IO.Path]::GetFullPath($Explicit)
        if (-not (Test-Path -LiteralPath $full)) { New-Item -ItemType Directory -Path $full -Force | Out-Null }
        return $full
    }

    foreach ($candidate in (Get-CartoHostSkillsCandidates)) {
        if (Test-Path -LiteralPath $candidate.Path -PathType Container) { return $candidate.Path }
    }
    return $null
}

# ─────────────────────────────────────────────
# SKILL.md 与 junction
# ─────────────────────────────────────────────

function Read-CartoSkillFrontMatter {
    param([Parameter(Mandatory = $true)][string]$SkillRoot)
    $path = Join-Path $SkillRoot 'SKILL.md'
    if (-not (Test-Path -LiteralPath $path)) { throw "SKILL.md 不存在: $path" }
    $lines = @(Get-Content -LiteralPath $path -Encoding UTF8)
    if ($lines.Count -lt 2 -or $lines[0].Trim() -ne '---') { throw 'SKILL.md 缺少 YAML front-matter 起始分隔符' }
    $end = -1
    for ($i = 1; $i -lt $lines.Count; $i++) { if ($lines[$i].Trim() -eq '---') { $end = $i; break } }
    if ($end -lt 0) { throw 'SKILL.md front-matter 未闭合' }

    $frontMatter = @{}
    for ($i = 1; $i -lt $end; $i++) {
        $index = $lines[$i].IndexOf(':')
        if ($index -gt 0) {
            $key = $lines[$i].Substring(0, $index).Trim()
            $frontMatter[$key] = $lines[$i].Substring($index + 1).Trim()
        }
    }
    return $frontMatter
}

function Test-CartoReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $item = Get-Item -LiteralPath $Path -Force
    return (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
}

function Remove-CartoJunction {
    <#
        安全移除 junction：只删链接本身，绝不递归删除目标内容。
        警告：Windows PowerShell 5.1 下对 junction 使用 Remove-Item -Recurse
        可能删除目标目录内容，因此这里固定使用 Directory.Delete(path, false)。
    #>
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-CartoReparsePoint -Path $Path) { [System.IO.Directory]::Delete($Path, $false) }
    elseif (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force }
}

function Copy-CartoSkillTree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (Test-Path -LiteralPath $Destination) { Remove-CartoJunction -Path $Destination }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null

    $sourceFull = (Get-Item -LiteralPath $Source).FullName.TrimEnd('\')
    $items = @(Get-ChildItem -LiteralPath $sourceFull -Recurse -Force | Where-Object {
            $_.FullName -notmatch '\\__pycache__(\\|$)' -and
            $_.Extension -ne '.pyc' -and
            $_.Name -ne '.env'
        })

    foreach ($item in $items) {
        $relative = $item.FullName.Substring($sourceFull.Length).TrimStart('\')
        $target = Join-Path $Destination $relative
        if ($item.PSIsContainer) {
            if (-not (Test-Path -LiteralPath $target)) { New-Item -ItemType Directory -Path $target -Force | Out-Null }
        }
        else {
            $targetDir = Split-Path -Path $target -Parent
            if (-not (Test-Path -LiteralPath $targetDir)) { New-Item -ItemType Directory -Path $targetDir -Force | Out-Null }
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
    return $items.Count
}

# ─────────────────────────────────────────────
# 报告
# ─────────────────────────────────────────────

function Write-CartoReport {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Prefix,
        [Parameter(Mandatory = $true)]$Payload
    )
    $dir = Get-CartoReportDir -RepoRoot $RepoRoot
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
    $path = Join-Path $dir "$Prefix-$stamp.json"
    ($Payload | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $path -Encoding UTF8
    return $path
}

function Write-CartoHostHandoff {
    <#
        打印「从这里开始执行测试用例」的交接卡：
        变量前置块可直接复制到宿主会话，之后即可逐组跑用例。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Cli
    )

    $docPath = Join-Path $RepoRoot 'doc\dev-log\0920宿主Agent形态一测试清单.md'
    $casesScript = Join-Path $RepoRoot 'tools\host\Invoke-CartoHostCases.ps1'
    $cliRelative = $Cli.Substring($RepoRoot.Length).TrimStart('\') -replace '\\', '/'
    $policyRelative = 'skills\carto-agent\policies\scope-baseline.yaml'

    Write-Host ''
    Write-Host ('-' * 72) -ForegroundColor DarkCyan
    Write-Host ' 从这里开始：测试用例执行入口' -ForegroundColor Cyan
    Write-Host ('-' * 72) -ForegroundColor DarkCyan
    Write-Host ''
    Write-Host '【方式一】一键跑完 A/B/C/D 四组共 26 条用例（推荐）' -ForegroundColor White
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$casesScript`"" -ForegroundColor Gray
    Write-Host ''
    Write-Host '【方式二】手工逐条执行，先粘贴以下变量前置块（清单步骤 0）' -ForegroundColor White
    Write-Host "  cd $RepoRoot" -ForegroundColor Gray
    Write-Host "  `$py = `"$Python`"" -ForegroundColor Gray
    Write-Host "  `$c  = `"$cliRelative`"" -ForegroundColor Gray
    Write-Host '  $r  = (Get-Location).Path' -ForegroundColor Gray
    Write-Host "  `$y  = `"`$r\$policyRelative`"" -ForegroundColor Gray
    Write-Host ''
    Write-Host '  然后按清单第四章逐组执行：' -ForegroundColor White
    Write-Host '    A 组 CLI 契约与只读能力（7 条）  → 4.1 节' -ForegroundColor Gray
    Write-Host '    B 组 安全边界与拒绝路径（8 条）  → 4.2 节' -ForegroundColor Gray
    Write-Host '    C 组 宿主会话行为（6 条）        → 4.3 节' -ForegroundColor Gray
    Write-Host '    D 组 文档与实现一致性（5 条）    → 4.4 节' -ForegroundColor Gray
    Write-Host ''
    Write-Host '【必读约束】' -ForegroundColor Yellow
    Write-Host '  · allowed-root / project-root / repository-root 必须绝对路径；workdir 可相对（按 project-root 解析）' -ForegroundColor Gray
    Write-Host '  · 判定看退出码 + JSON code 字段；PowerShell 的红色 NativeCommandError 是显示噪声' -ForegroundColor Gray
    Write-Host '  · probe-renderer 与 intent resolve 在能力不可用时仍返回退出码 0，判据在响应体字段' -ForegroundColor Gray
    Write-Host '  · 只读 status 也会创建 run 目录与 .workflow.lock，试探后必须清理（D5）' -ForegroundColor Gray
    Write-Host '  · 不得在 preview / freeze 执行期间轮询 status（单写锁 10 秒超时）' -ForegroundColor Gray
    Write-Host '  · 宿主 Agent 无权签发审批回执，遇 author/compile/publish/freeze 必须停下索取' -ForegroundColor Gray
    Write-Host ''
    if (Test-Path -LiteralPath $docPath) {
        Write-Host "清单文档: $docPath" -ForegroundColor DarkGray
    }
    Write-Host ''
}

# ────────────────────────────────
# Hermes 仓库本地技能注册
# ────────────────────────────────

function Get-CartoHermesExe {
    param([string]$Explicit = '')
    if ($Explicit) {
        if (Test-Path -LiteralPath $Explicit) { return $Explicit }
        throw "指定的 hermes 可执行文件不存在: $Explicit"
    }
    $cmd = Get-Command hermes -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    foreach ($candidate in @(
            (Join-Path $env:LOCALAPPDATA 'hermes\bin\hermes.exe'),
            (Join-Path $env:USERPROFILE '.hermes\bin\hermes.exe')
        )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Get-CartoHermesProjectSkillPath {
    param([Parameter(Mandatory = $true)][string]$RepoRoot, [Parameter(Mandatory = $true)][string]$SkillName)
    return (Join-Path $RepoRoot ".hermes\skills\$SkillName")
}

function Register-CartoHermesProjectSkill {
    <#
        仓库本地注册（Hermes 官方推荐路径，对应 hermes skills trust）：
          1. 在 <repo>\.hermes\skills\<name> 建 junction 指向 <repo>\skills\<name>
          2. 执行 hermes skills trust <repo> 授权本项目
        技能仅在本仓库内启动的会话中加载，且优先于同名 profile 技能。
        不复制内容，仓库仍是唯一实现根（符合 AGENTS.md 约束）。

        注意：hermes 输出为 UTF-8（包括表格框线字符），因此按 Invoke-CartoProcess
        默认的 UTF-8 解码，不能用系统 ANSI。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$SkillName,
        [string]$HermesExe = ''
    )

    $hermes = Get-CartoHermesExe -Explicit $HermesExe
    if (-not $hermes) { throw '未找到 hermes 可执行文件；请确认已安装 Hermes，或用 -HermesExe 指定绝对路径' }

    $linkPath = Get-CartoHermesProjectSkillPath -RepoRoot $RepoRoot -SkillName $SkillName
    $linkParent = Split-Path -Path $linkPath -Parent
    if (-not (Test-Path -LiteralPath $linkParent)) { New-Item -ItemType Directory -Path $linkParent -Force | Out-Null }

    $reused = $false
    if (Test-Path -LiteralPath $linkPath) {
        $reused = $true
    }
    else {
        New-Item -ItemType Junction -Path $linkPath -Target $SourceRoot -ErrorAction Stop | Out-Null
    }

    $trust = Invoke-CartoProcess -FileName $hermes -WorkingDirectory $RepoRoot -TimeoutSeconds 300 `
        -Arguments @('skills', 'trust', $RepoRoot)
    $listing = Invoke-CartoProcess -FileName $hermes -WorkingDirectory $RepoRoot -TimeoutSeconds 300 `
        -Arguments @('skills', 'list')
    $registered = ($listing.ExitCode -eq 0) -and ($listing.StdOut -match [regex]::Escape($SkillName))

    return [pscustomobject]@{
        HermesExe   = $hermes
        LinkPath    = $linkPath
        Reused      = $reused
        TrustExit   = $trust.ExitCode
        TrustOutput = ($trust.StdOut + $trust.StdErr).Trim()
        Registered  = $registered
    }
}

function Unregister-CartoHermesProjectSkill {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$SkillName,
        [string]$HermesExe = ''
    )

    $linkPath = Get-CartoHermesProjectSkillPath -RepoRoot $RepoRoot -SkillName $SkillName
    if (Test-Path -LiteralPath $linkPath) { Remove-CartoJunction -Path $linkPath }

    # 逐级清理空目录，不清除其他内容
    foreach ($dir in @((Split-Path -Path $linkPath -Parent), (Join-Path $RepoRoot '.hermes'))) {
        if ((Test-Path -LiteralPath $dir) -and (@(Get-ChildItem -LiteralPath $dir -Force).Count -eq 0)) {
            Remove-Item -LiteralPath $dir -Force
        }
    }

    $hermes = Get-CartoHermesExe -Explicit $HermesExe
    $trustOutput = ''
    if ($hermes) {
        $untrust = Invoke-CartoProcess -FileName $hermes -WorkingDirectory $RepoRoot -TimeoutSeconds 300 `
            -Arguments @('skills', 'untrust', $RepoRoot)
        $trustOutput = ($untrust.StdOut + $untrust.StdErr).Trim()
    }
    return [pscustomobject]@{ LinkPath = $linkPath; Removed = (-not (Test-Path -LiteralPath $linkPath)); TrustOutput = $trustOutput }
}

# ────────────────────────────────
# Hermes 全局 profile 技能注册
# 实测发现：仅在 <hermes_home>\skills\<category>\<name> 放 junction 不够，
# hermes skills list 不显示；必须 hermes curator adopt <name> 打 provenance 标记。
# ────────────────────────────────

function Get-CartoHermesHome {
    <# 由 hermes.exe 位置反推 Hermes 安装根：<home>\bin\hermes.exe -> <home> #>
    param([string]$HermesExe = '')
    $hermes = Get-CartoHermesExe -Explicit $HermesExe
    if (-not $hermes) { return $null }
    return (Split-Path -Path (Split-Path -Path $hermes -Parent) -Parent)
}

function Register-CartoHermesGlobalSkill {
    <#
        全局 profile 注册（任何 cwd 的会话都加载，在 /skills 目录的指定类别下出现）：
          1. 在 <hermes_home>\skills\<category>\<name> 建 junction 指向 <repo>\skills\<name>
          2. hermes curator adopt <name> --yes  打 provenance 标记（关键步骤，否则 skills list 不显示）
          3. 从仓库外核验 hermes skills list（避免项目本地同名优先导致去重）
        hermes.exe 输出为 UTF-8，沿用 Invoke-CartoProcess 默认 UTF-8 解码。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$SkillName,
        [Parameter(Mandatory = $true)][string]$Category,
        [string]$HermesExe = ''
    )

    $hermes = Get-CartoHermesExe -Explicit $HermesExe
    if (-not $hermes) { throw '未找到 hermes 可执行文件；请确认已安装 Hermes，或用 -HermesExe 指定绝对路径' }

    $home2 = Get-CartoHermesHome -HermesExe $HermesExe
    $skillsRoot = Join-Path $home2 'skills'
    $categoryDir = Join-Path $skillsRoot $Category
    if (-not (Test-Path -LiteralPath $categoryDir)) {
        New-Item -ItemType Directory -Path $categoryDir -Force | Out-Null
        Write-CartoWarn "类别目录新建：$categoryDir（Hermes 规范建议不轻易新增顶层类别）"
    }
    $linkPath = Join-Path $categoryDir $SkillName

    if (Test-Path -LiteralPath $linkPath) {
        if (Test-CartoReparsePoint -Path $linkPath) { Remove-CartoJunction -Path $linkPath }
        else { throw "目标已存在且为实体目录（非 junction）：$linkPath；请先手工移除或换类别/名称" }
    }
    New-Item -ItemType Junction -Path $linkPath -Target $SourceRoot -ErrorAction Stop | Out-Null

    # 关键步骤：curator adopt 打 provenance 标记。幂等：已管理时输出含 already/managed
    $adopt = Invoke-CartoProcess -FileName $hermes -TimeoutSeconds 300 `
        -Arguments @('curator', 'adopt', $SkillName, '--yes')
    $adoptOk = ($adopt.ExitCode -eq 0) -or ($adopt.StdOut -match 'already|managed') -or ($adopt.StdErr -match 'already|managed')

    # 从仓库外核验，避免项目本地同名优先导致去重看不到全局条目
    $listing = Invoke-CartoProcess -FileName $hermes -WorkingDirectory $env:USERPROFILE -TimeoutSeconds 300 `
        -Arguments @('skills', 'list')
    $row = ($listing.StdOut -split "`r?`n" | Where-Object { $_ -match [regex]::Escape($SkillName) } | Select-Object -First 1)
    $registered = ($null -ne $row) -and ($row -match [regex]::Escape($Category))

    return [pscustomobject]@{
        HermesExe   = $hermes
        LinkPath    = $linkPath
        Category    = $Category
        AdoptOk     = $adoptOk
        AdoptExit   = $adopt.ExitCode
        AdoptOutput = ($adopt.StdOut + $adopt.StdErr).Trim()
        Registered  = $registered
        ListedRow   = $row
    }
}

function Unregister-CartoHermesGlobalSkill {
    <#
        全局注销：安全移除 <hermes_home>\skills\<category>\<name> junction，
        并从仓库外核验 hermes skills list 不再列出。
        curator provenance 标记可能残留为孤儿（无害），如需彻底清理可手工 hermes curator archive/prune。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$SkillName,
        [Parameter(Mandatory = $true)][string]$Category,
        [string]$HermesExe = ''
    )

    $hermes = Get-CartoHermesExe -Explicit $HermesExe
    if ($hermes) { $home2 = Get-CartoHermesHome -HermesExe $HermesExe }
    else { $home2 = Join-Path $env:LOCALAPPDATA 'hermes' }

    $linkPath = Join-Path $home2 "skills\$Category\$SkillName"
    if (Test-Path -LiteralPath $linkPath) {
        if (Test-CartoReparsePoint -Path $linkPath) { Remove-CartoJunction -Path $linkPath }
        else { Remove-Item -LiteralPath $linkPath -Recurse -Force }
    }
    $removed = -not (Test-Path -LiteralPath $linkPath)

    $stillListed = $false
    if ($hermes) {
        $listing = Invoke-CartoProcess -FileName $hermes -WorkingDirectory $env:USERPROFILE -TimeoutSeconds 300 `
            -Arguments @('skills', 'list')
        $stillListed = ($listing.StdOut -match [regex]::Escape($SkillName))
    }

    return [pscustomobject]@{
        LinkPath = $linkPath; Removed = $removed; StillListed = $stillListed
        Note     = 'curator provenance 标记可能残留为孤儿（无害）；如需清理可手工 hermes curator archive/prune'
    }
}
