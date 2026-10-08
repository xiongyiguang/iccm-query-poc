[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [ValidateScript({ $_ -notmatch '[|\r\n]' })]
    [string]$ProjectName,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [ValidateScript({ $_ -notmatch '[|\r\n]' })]
    [string]$ProjectType,

    [ValidateNotNullOrEmpty()]
    [ValidateScript({ $_ -notmatch '[|\r\n]' })]
    [string]$ProjectShape = "待确认",

    [ValidateScript({ $_ -notmatch '[|\r\n]' })]
    [string]$ProjectDeliveryGoal = "待确认",

    [ValidateScript({ $_ -notmatch '[|\r\n]' })]
    [string]$ProjectOwner = "待填写",

    [ValidateScript({ $_ -notmatch '[\\/:*?"<>|\r\n]' })]
    [string]$ProjectSlug = "",

    [ValidateSet("待确认", "轻量", "标准", "严格")]
    [string]$ExecutionProfile = "待确认",

    [switch]$SkipGit,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDirectory ".."))
$folderName = Split-Path -Leaf $projectRoot
$manifestPath = Join-Path $projectRoot "PROJECT.yaml"
$projectInfoPath = Join-Path $projectRoot "docs\00-项目治理\项目基本信息.md"

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "未找到 PROJECT.yaml，无法确认项目根目录：$projectRoot"
}

if (-not $DryRun -and $folderName -eq "AI项目工程模板_Codex协同开发版") {
    throw "当前目录名称仍是母版名称。请先复制并重命名文件夹，再运行初始化脚本。"
}

if ([string]::IsNullOrWhiteSpace($ProjectSlug)) {
    $ProjectSlug = $ProjectName.Trim().ToLowerInvariant()
    $ProjectSlug = [regex]::Replace($ProjectSlug, '[^\p{L}\p{Nd}]+', '-')
    $ProjectSlug = $ProjectSlug.Trim('-')
}

if ([string]::IsNullOrWhiteSpace($ProjectSlug)) {
    throw "无法从项目名称生成 Slug，请显式传入 -ProjectSlug。"
}

function ConvertTo-YamlScalar {
    param([string]$Value)

    $escaped = $Value.Replace('\', '\\').Replace('"', '\"')
    return '"' + $escaped + '"'
}

function Set-YamlSectionValue {
    param(
        [string[]]$Lines,
        [string]$Section,
        [string]$Key,
        [string]$Value
    )

    $currentSection = ""
    $found = $false
    for ($index = 0; $index -lt $Lines.Count; $index++) {
        $line = $Lines[$index]
        if ($line -match '^([A-Za-z_][A-Za-z0-9_-]*):\s*$') {
            $currentSection = $Matches[1]
            continue
        }

        if ($currentSection -eq $Section -and $line -match ('^  ' + [regex]::Escape($Key) + ':\s*')) {
            $Lines[$index] = "  ${Key}: $Value"
            $found = $true
            break
        }
    }

    if (-not $found) {
        throw "PROJECT.yaml 中缺少字段：$Section.$Key"
    }

    return ,$Lines
}

$manifestLines = @(Get-Content -LiteralPath $manifestPath -Encoding UTF8)
$templateState = $null
$currentSection = ""
foreach ($line in $manifestLines) {
    if ($line -match '^([A-Za-z_][A-Za-z0-9_-]*):\s*$') {
        $currentSection = $Matches[1]
        continue
    }
    if ($currentSection -eq "template" -and $line -match '^  is_template:\s*(.+?)\s*$') {
        $templateState = $Matches[1]
        break
    }
}

if ($templateState -ne "true") {
    throw "当前 PROJECT.yaml 不是待初始化的母版状态，停止重复初始化。"
}

$manifestLines = Set-YamlSectionValue $manifestLines "execution" "profile" (ConvertTo-YamlScalar $ExecutionProfile)

$today = Get-Date -Format "yyyy-MM-dd"
$manifestLines = Set-YamlSectionValue $manifestLines "template" "is_template" "false"
$manifestLines = Set-YamlSectionValue $manifestLines "project" "name" (ConvertTo-YamlScalar $ProjectName)
$manifestLines = Set-YamlSectionValue $manifestLines "project" "slug" (ConvertTo-YamlScalar $ProjectSlug)
$manifestLines = Set-YamlSectionValue $manifestLines "project" "type" (ConvertTo-YamlScalar $ProjectType)
$manifestLines = Set-YamlSectionValue $manifestLines "project" "shape" (ConvertTo-YamlScalar $ProjectShape)
$manifestLines = Set-YamlSectionValue $manifestLines "project" "delivery_goal" (ConvertTo-YamlScalar $ProjectDeliveryGoal)
$manifestLines = Set-YamlSectionValue $manifestLines "project" "stage" (ConvertTo-YamlScalar "00-项目启动")
$manifestLines = Set-YamlSectionValue $manifestLines "project" "owner" (ConvertTo-YamlScalar $ProjectOwner)
$manifestLines = Set-YamlSectionValue $manifestLines "project" "created_at" (ConvertTo-YamlScalar $today)
$manifestLines = Set-YamlSectionValue $manifestLines "project" "updated_at" (ConvertTo-YamlScalar $today)

if ($DryRun) {
    Write-Host "[DRY-RUN] 项目根目录：$projectRoot"
    Write-Host "[DRY-RUN] 将初始化项目：$ProjectName ($ProjectSlug) / $ProjectType / $ProjectShape"
    Write-Host "[DRY-RUN] 执行档位：$ExecutionProfile；PROJECT.yaml 字段检查通过，未写入文件。"
    exit 0
}

Set-Content -LiteralPath $manifestPath -Value $manifestLines -Encoding UTF8

if (Test-Path -LiteralPath $projectInfoPath -PathType Leaf) {
    $projectInfo = Get-Content -LiteralPath $projectInfoPath -Raw -Encoding UTF8
    $projectInfo = $projectInfo.Replace('|项目名称|待填写|', "|项目名称|$ProjectName|")
    $projectInfo = $projectInfo.Replace('|项目简称/Slug|待填写|', "|项目简称/Slug|$ProjectSlug|")
    $projectInfo = $projectInfo.Replace('|项目类型|待选择|', "|项目类型|$ProjectType|")
    $projectInfo = $projectInfo.Replace('|项目形态|按实际情况开放描述，例如独立应用/服务、既有系统改造、配置型产品、数据/算法组件、技术原型或其他|', "|项目形态|$ProjectShape|")
    $projectInfo = $projectInfo.Replace('|本期交付目标|待确认；区分技术试验、配置能力、可运行闭环和可发布版本|', "|本期交付目标|$ProjectDeliveryGoal|")
    $projectInfo = $projectInfo.Replace('|项目负责人|待填写|', "|项目负责人|$ProjectOwner|")
    Set-Content -LiteralPath $projectInfoPath -Value $projectInfo -Encoding UTF8
}

if (-not $SkipGit) {
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($null -eq $gitCommand) {
        Write-Warning "未找到 Git。项目文件已初始化，但尚未创建 Git 仓库。"
    }
    elseif (Test-Path -LiteralPath (Join-Path $projectRoot ".git")) {
        Write-Warning "当前目录已经存在 .git，未重复初始化。请确认它不是从其他项目复制的历史。"
    }
    else {
        & git -C $projectRoot init -b main
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "当前 Git 不支持直接指定初始分支，改用兼容方式初始化。"
            & git -C $projectRoot init
            if ($LASTEXITCODE -ne 0) {
                throw "Git 初始化失败，退出码：$LASTEXITCODE"
            }
            & git -C $projectRoot symbolic-ref HEAD refs/heads/main
            if ($LASTEXITCODE -ne 0) {
                throw "Git 主分支设置为 main 失败，退出码：$LASTEXITCODE"
            }
        }
    }
}

Write-Host "项目初始化完成：$ProjectName"
Write-Host "项目根目录：$projectRoot"
Write-Host "下一步：登记项目输入依据，确认 PROJECT.yaml 的适用性字段，然后执行需求分析 Prompt。"

