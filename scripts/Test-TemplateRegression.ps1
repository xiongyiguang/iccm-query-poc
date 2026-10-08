[CmdletBinding()]
param([switch]$StructureOnly, [string]$TemplateRoot = "")
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($TemplateRoot)) { $TemplateRoot = Join-Path $PSScriptRoot ".." }
$root = [IO.Path]::GetFullPath($TemplateRoot)
$requiredFiles = @(
    "docs\00-项目治理\本轮变更.json",
    "docs\00-项目治理\分级执行与裁剪规则.md",
    "docs\00-项目治理\轻量项目执行简表.md",
    "docs\00-项目治理\门禁证据.json",
    "scripts\Test-TemplateRegression.ps1",
    "AGENTS.md",
    "README.md",
    "PROJECT.yaml",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".env.example",
    "docs\README.md",
    "docs\00-项目治理\项目基本信息.md",
    "docs\00-项目治理\输入材料清单.md",
    "docs\00-项目治理\待确认问题.md",
    "docs\00-项目治理\决策记录.md",
    "docs\00-项目治理\风险与依赖.md",
    "docs\00-项目治理\项目变更记录.md",
    "docs\00-项目治理\阶段门禁与完成定义.md",
    "docs\00-项目治理\系统性问题解决方法论.md",
    "docs\01-需求分析\产品形态与研发策略.md",
    "docs\01-需求分析\项目背景与目标.md",
    "docs\01-需求分析\用户角色与场景.md",
    "docs\01-需求分析\需求清单与验收草案.md",
    "docs\02-业务设计\业务对象模型.md",
    "docs\02-业务设计\业务流程设计.md",
    "docs\02-业务设计\业务规则设计.md",
    "docs\03-架构设计\系统架构设计.md",
    "docs\03-架构设计\数据模型设计.md",
    "docs\03-架构设计\接口设计.md",
    "docs\03-架构设计\安全与权限设计.md",
    "docs\03-架构设计\前端交互与组件基线.md",
    "docs\03-架构设计\开源与现成方案调研.md",
    "docs\03-架构设计\技术选型记录.md",
    "docs\04-AI设计\AI能力边界.md",
    "docs\04-AI设计\非结构化材料语义抽取与模型输出治理.md",
    "docs\04-AI设计\Prompt资产管理.md",
    "docs\04-AI设计\RAG知识库设计.md",
    "docs\04-AI设计\Agent工作流设计.md",
    "docs\04-AI设计\模型与评测设计.md",
    "docs\05-专项设计\README.md",
    "docs\05-专项设计\智能审核\审核链路设计.md",
    "docs\05-专项设计\智能审核\审核问题定位模型.md",
    "docs\05-专项设计\智能审核\字段追踪设计.md",
    "docs\06-测试与验收\测试方案.md",
    "docs\06-测试与验收\验收场景设计.md",
    "docs\06-测试与验收\测试案例.md",
    "docs\06-测试与验收\AI评测方案.md",
    "docs\06-测试与验收\验收追踪矩阵.md",
    "docs\06-测试与验收\验收记录.md",
    "docs\07-部署与运维\部署与回滚方案.md",
    "docs\07-部署与运维\监控与运行手册.md",
    "docs\07-部署与运维\发布检查表.md",
    "docs\08-项目沉淀\项目复盘.md",
    "docs\08-项目沉淀\失败案例库.md",
    "docs\08-项目沉淀\平台型AI项目研发方法.md",
    "prompts\README.md",
    "prompts\01_需求分析启动Prompt.md",
    "prompts\02_业务设计Prompt.md",
    "prompts\03_架构设计Prompt.md",
    "prompts\04_AI能力设计Prompt.md",
    "prompts\05_开发Prompt.md",
    "prompts\06_测试验收Prompt.md",
    "prompts\07_部署交付Prompt.md",
    "prompts\08_复盘沉淀Prompt.md",
    "scripts\Initialize-Project.ps1",
    "scripts\Test-ProjectReadiness.ps1"
)

$requiredDirectories = @(
    "docs\deliverables",
    "docs\.staging",
    "prompts\system",
    "prompts\task",
    "prompts\evaluation",
    "prompts\history",
    "tests",
    "inputs",
    "deployment",
    "frontend",
    "backend"
)


# 此清单只属于软件开发母版检查，不属于业务项目就绪检查。
$requiredFiles += @("scripts/README.md", "docs/08-项目沉淀/母版2.8.0升级说明.md")
$structureErrors = @()
foreach ($path in $requiredFiles) { if (-not (Test-Path -LiteralPath (Join-Path $root $path) -PathType Leaf)) { $structureErrors += "Missing template file: $path" } }
foreach ($path in $requiredDirectories) { if (-not (Test-Path -LiteralPath (Join-Path $root $path) -PathType Container)) { $structureErrors += "Missing template directory: $path" } }
$templateText = Get-Content -LiteralPath (Join-Path $root "PROJECT.yaml") -Raw -Encoding UTF8
if ($templateText -notmatch '(?m)^  is_template: true\s*$') { $structureErrors += "TemplateRegression requires is_template: true" }
$templateIndex = Get-Content -LiteralPath (Join-Path $root "docs/README.md") -Raw -Encoding UTF8
foreach ($path in $requiredFiles | Where-Object { $_ -match '^docs[\\/].+\.(md|json)$' -and $_ -ne 'docs\README.md' }) {
    $canonical = $path.Replace('\','/')
    $sourceRows = @($templateIndex -split "`r?`n" | Where-Object { $_.Contains(('`' + $canonical + '`')) })
    if ($sourceRows.Count -ne 1) { $structureErrors += "Template document must have one index source row: $canonical" }
}
if ($structureErrors.Count -gt 0) { $structureErrors | Write-Output; exit 1 }
Write-Host "Template inventory complete: $($requiredFiles.Count) files, $($requiredDirectories.Count) directories"
if ($StructureOnly) { exit 0 }

$runRoot = Join-Path $root ("docs/.staging/v2.8.0-validation/run-" + [guid]::NewGuid().ToString("N"))
$fixture = Join-Path $runRoot "synthetic-project"
New-Item -ItemType Directory -Path $fixture | Out-Null
function Get-TemplateSourceFiles {
    param([string]$Directory)
    foreach ($entry in Get-ChildItem -LiteralPath $Directory -Force) {
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
        if ($entry.PSIsContainer) {
            if ($entry.Name -notin @(".staging", ".git", "node_modules", ".venv", "dist", "build")) { Get-TemplateSourceFiles $entry.FullName }
        } else { $entry }
    }
}
foreach ($file in @(Get-TemplateSourceFiles $root)) {
    $relative = $file.FullName.Substring($root.Length + 1)
    if ($relative.StartsWith(".git\")) { continue }
    $target = Join-Path $fixture $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target
}
foreach ($directory in @("docs/.staging", "docs/deliverables", "frontend", "backend", "inputs", "deployment", "tests", "prompts/system", "prompts/task", "prompts/evaluation", "prompts/history")) {
    New-Item -ItemType Directory -Path (Join-Path $fixture $directory) -Force | Out-Null
}
$hostExe = if ($PSVersionTable.PSEdition -eq "Core") { Join-Path $PSHOME "pwsh.exe" } else { Join-Path $PSHOME "powershell.exe" }
$checker = Join-Path $fixture "scripts/Test-ProjectReadiness.ps1"
$manifest = Join-Path $fixture "PROJECT.yaml"
$index = Join-Path $fixture "docs/README.md"
$evidence = Join-Path $fixture "docs/00-项目治理/门禁证据.json"
$results = @()
function Check-Case {
    param([string]$Name, [string]$Level, [int]$Expected)
    $inputRoot = Join-Path $runRoot ("case-inputs/" + $Name)
    foreach ($relative in @("PROJECT.yaml", "docs/README.md", "docs/00-项目治理/门禁证据.json", "docs/00-项目治理/本轮变更.json", "backend/AGENTS.md", ".gitignore")) {
        $sourceRoot = Split-Path -Parent (Split-Path -Parent $checker)
        $source = Join-Path $sourceRoot $relative
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            $target = Join-Path $inputRoot $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            Copy-Item -LiteralPath $source -Destination $target
        }
    }
    $output = @(& $hostExe -NoProfile -ExecutionPolicy Bypass -File $checker -Level $Level 2>&1)
    $actual = $LASTEXITCODE
    $output | Set-Content -LiteralPath (Join-Path $runRoot ($Name + ".log")) -Encoding UTF8
    $requiredDiagnostic = @{
        "light-frontend-gate-retained" = "interaction_baseline_confirmed"
        "light-semantic-gate-retained" = "semantic_extraction_design_confirmed"
        "release-unauthorized" = "release_authorized|发布授权"
        "strict-risk-review-missing" = "risk_review_confirmed"
        "strict-review-missing" = "independent_review_confirmed"
        "strict-rollback-missing" = "rollback_validated"
    }
    $diagnosticMatched = -not $requiredDiagnostic.ContainsKey($Name) -or (($output -join "`n") -match $requiredDiagnostic[$Name])
    $script:results += [PSCustomObject]@{ Case=$Name; Level=$Level; Expected=$Expected; Actual=$actual; Passed=($actual -eq $Expected -and $diagnosticMatched) }
    $script:results | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runRoot "results.json") -Encoding UTF8
}
Check-Case "template-structure" "Structure" 0
Check-Case "template-audit-no-registration" "Audit" 0
Check-Case "template-maintenance-no-business-gates" "TemplateMaintenance" 0
Check-Case "template-regression-route" "TemplateRegression" 0
Check-Case "template-development-blocked" "Development" 1
$initOutput = @(& $hostExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $fixture "scripts/Initialize-Project.ps1") -ProjectName "Synthetic test only" -ProjectType "测试" -ProjectShape "独立应用或服务" -ProjectDeliveryGoal "仅门禁回归" -ExecutionProfile "轻量" -SkipGit 2>&1)
if ($LASTEXITCODE -ne 0) { throw ($initOutput -join "`n") }
& git -C $fixture init --quiet
if ($LASTEXITCODE -ne 0) { throw "fixture git init failed" }
# 忽略合成项目中的未跟踪文件，以验证只检查登记状态的 Release 逻辑。
# 不创建真实项目提交、部署或操作授权。
Add-Content -LiteralPath (Join-Path $fixture ".gitignore") -Value "`n# Synthetic registration-only fixture`n*" -Encoding UTF8
$initialManifest = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8
$initialIndex = Get-Content -LiteralPath $index -Raw -Encoding UTF8
$governanceSection = [regex]::Match($initialManifest, '(?ms)^governance:\s*\r?\n(.*?)(?=^[A-Za-z_]+:|\z)').Groups[1].Value
$gates = @([regex]::Matches($governanceSection, '(?m)^  ([a-z_]+): false\s*$') | ForEach-Object { $_.Groups[1].Value })
if ($gates.Count -eq 0) { throw "No governance gates found in synthetic manifest" }
$records = @($gates | ForEach-Object {
    [PSCustomObject]@{ gate=$_; status="已确认"; confirmed_by="SYNTHETIC TEST ONLY"; confirmed_at="2026-09-07"; confirmation_ref="Synthetic fixture; not real authorization"; evidence_path="docs/00-项目治理/轻量项目执行简表.md" }
})
$baseEvidence = @{schema_version=1; records=$records} | ConvertTo-Json -Depth 6
function Reset-Fixture {
    param([string]$Profile="标准")
    $text = $initialManifest.Replace('profile: "轻量"', ('profile: "' + $Profile + '"')).Replace('rationale: "待确认"', 'rationale: "合成测试数据；无真实业务"').Replace('high_risk: "待确认"', 'high_risk: "否"')
    $text = $text.Replace(': false', ': true')
    $text = $text.Replace('is_template: true', 'is_template: false')
    $text = $text.Replace(': "待确认"', ': "不适用"')
    # 2.8 新字段使用合法中性界面配置，避免掩盖历史前端门禁失败。
    $text = [regex]::Replace($text, '(?ms)(^ui:\s*\r?\n.*?^  profile: )[^\r\n]+', '$1"general-ui"')
    Set-Content -LiteralPath $manifest -Value $text -Encoding UTF8
    Set-Content -LiteralPath $index -Value ($initialIndex.Replace('|模板|','|已确认|').Replace('|草稿|','|已确认|')) -Encoding UTF8
    Set-Content -LiteralPath $evidence -Value $baseEvidence -Encoding UTF8
}
function Change-Manifest { param([string]$Old,[string]$New)
    $text=Get-Content -LiteralPath $manifest -Raw -Encoding UTF8
    if (-not $text.Contains($Old)) { throw "Missing fixture target: $Old" }
    Set-Content -LiteralPath $manifest -Value $text.Replace($Old,$New) -Encoding UTF8
}
foreach ($profile in @("轻量", "标准", "严格")) {
    Reset-Fixture $profile
    Check-Case ($profile + "-development") "Development" 0
    Check-Case ($profile + "-release") "Release" 0
}
Reset-Fixture "严格"
Change-Manifest 'high_risk: "否"' 'high_risk: "是"'
Check-Case "strict-high-risk" "Development" 0
Reset-Fixture "轻量"
$consolidatedLines = @(Get-Content -LiteralPath $index -Encoding UTF8 | ForEach-Object {
    if ($_ -match '系统性问题解决方法论\.md|分级执行与裁剪规则\.md|轻量项目执行简表\.md') { $_ } else { $_.Replace('|已确认|','|合并维护|') }
})
Set-Content -LiteralPath $index -Value $consolidatedLines -Encoding UTF8
Check-Case "light-consolidated-documents" "Development" 0
Reset-Fixture
Set-Content -LiteralPath $evidence -Value '{"schema_version":1,"records":[]}' -Encoding UTF8
Check-Case "missing-evidence" "Development" 1
Reset-Fixture
Change-Manifest 'profile: "标准"' 'profile: "未知档位"'
Check-Case "invalid-profile" "Development" 1
Reset-Fixture "轻量"
Change-Manifest 'high_risk: "否"' 'high_risk: "是"'
Check-Case "high-risk-light-blocked" "Development" 1
Reset-Fixture
Set-Content -LiteralPath $index -Value ((Get-Content -LiteralPath $index -Raw -Encoding UTF8).Replace('|已确认|','|草稿|')) -Encoding UTF8
Check-Case "draft-documents-blocked" "Development" 1
Reset-Fixture
Set-Content -LiteralPath $evidence -Value '{bad json' -Encoding UTF8
Check-Case "malformed-registry" "Development" 1
Reset-Fixture
$duplicate = @{schema_version=1;records=@($records)+@($records[0])} | ConvertTo-Json -Depth 6
Set-Content -LiteralPath $evidence -Value $duplicate -Encoding UTF8
Check-Case "duplicate-gate" "Development" 1
Reset-Fixture
Set-Content -LiteralPath $evidence -Value $baseEvidence.Replace('docs/00-项目治理/轻量项目执行简表.md','../outside.md') -Encoding UTF8
Check-Case "evidence-path-escape" "Development" 1
Reset-Fixture
Set-Content -LiteralPath $evidence -Value $baseEvidence.Replace('docs/00-项目治理/轻量项目执行简表.md','docs/.staging/fake.md') -Encoding UTF8
Check-Case "staging-evidence-blocked" "Development" 1
Reset-Fixture
Set-Content -LiteralPath $evidence -Value $baseEvidence.Replace('2026-09-07','2026-99-99') -Encoding UTF8
Check-Case "invalid-confirmation-date" "Development" 1
Reset-Fixture
Change-Manifest 'release_authorized: true' 'release_authorized: false'
Check-Case "release-unauthorized" "Release" 1
Reset-Fixture "严格"
Change-Manifest 'risk_review_confirmed: true' 'risk_review_confirmed: false'
Check-Case "strict-risk-review-missing" "Development" 1
Reset-Fixture "严格"
Change-Manifest 'independent_review_confirmed: true' 'independent_review_confirmed: false'
Check-Case "strict-review-missing" "Release" 1
Reset-Fixture "严格"
Change-Manifest 'rollback_validated: true' 'rollback_validated: false'
Check-Case "strict-rollback-missing" "Release" 1
Reset-Fixture "轻量"
Change-Manifest 'frontend: "不适用"' 'frontend: "适用"'
Change-Manifest 'interaction_baseline_confirmed: true' 'interaction_baseline_confirmed: false'
Check-Case "light-frontend-gate-retained" "Development" 1
Reset-Fixture "轻量"
Change-Manifest 'ai: "不适用"' 'ai: "适用"'
Change-Manifest 'semantic_extraction: "不适用"' 'semantic_extraction: "适用"'
Change-Manifest 'semantic_extraction_design_confirmed: true' 'semantic_extraction_design_confirmed: false'
Check-Case "light-semantic-gate-retained" "Development" 1
Reset-Fixture
Change-Manifest 'schema_version: 3' 'schema_version: 2'
Check-Case "legacy-schema-blocked" "Development" 1
Reset-Fixture
Set-Content -LiteralPath $evidence -Value $baseEvidence.Replace('execution_profile_confirmed','unknown_gate') -Encoding UTF8
Check-Case "unknown-gate-blocked" "Development" 1
Reset-Fixture
Set-Content -LiteralPath $index -Value ((Get-Content -LiteralPath $index -Raw -Encoding UTF8).Replace('|按需|已确认|','|按需|待确认|')) -Encoding UTF8
Check-Case "release-pending-document" "Release" 1
# 以下为 2.7 契约案例，保留上方所有 2.6 预期不变。
$changePath = Join-Path $fixture "docs/00-项目治理/本轮变更.json"
function Set-MinimalStartup {
    param([string]$Profile="轻量")
    Reset-Fixture $Profile
    $text = (Get-Content -LiteralPath $manifest -Raw -Encoding UTF8).Replace(': true', ': false').Replace('startup_scope_confirmed: false','startup_scope_confirmed: true')
    if ($Profile -eq "严格") { $text = $text.Replace('risk_review_confirmed: false','risk_review_confirmed: true') }
    Set-Content -LiteralPath $manifest -Value $text -Encoding UTF8
    $minimalRecords = @($records | Where-Object { $_.gate -eq "startup_scope_confirmed" -or ($Profile -eq "严格" -and $_.gate -eq "risk_review_confirmed") })
    Set-Content -LiteralPath $evidence -Value (@{schema_version=1;records=$minimalRecords} | ConvertTo-Json -Depth 6) -Encoding UTF8
    Set-Content -LiteralPath $index -Value $initialIndex.Replace('|启动及轻量适用|模板|','|启动及轻量适用|已确认|') -Encoding UTF8
}
function Set-MinimalIteration {
    param([string]$Profile="标准")
    Set-MinimalStartup $Profile
    Change-Manifest 'startup_scope_confirmed: true' 'startup_scope_confirmed: false'
    Set-Content -LiteralPath $evidence -Value '{"schema_version":1,"records":[]}' -Encoding UTF8
    $text=(Get-Content -LiteralPath $index -Raw -Encoding UTF8).Replace('|迭代适用|模板|','|迭代适用|已记录|')
    Set-Content -LiteralPath $index -Value $text -Encoding UTF8
    $change = @{schema_version=1;change_id="synthetic-change";request_ref="synthetic user request";baseline_path="docs/00-项目治理/轻量项目执行简表.md";baseline_version="synthetic-v1";scope="局部文案";impact_reason="测试隔离修改，无共享数据与契约变化";impacted_gates=@();high_risk=$false;business_change=$false;confirmation_ref="";validation_plan="验证受影响页面及原正常场景"}
    Set-Content -LiteralPath $changePath -Value ($change | ConvertTo-Json -Depth 6) -Encoding UTF8
}
function Change-Iteration {
    param([string]$Key, $Value)
    $change=Get-Content -LiteralPath $changePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $change | Add-Member -NotePropertyName $Key -NotePropertyValue $Value -Force
    Set-Content -LiteralPath $changePath -Value ($change | ConvertTo-Json -Depth 6) -Encoding UTF8
}
foreach ($profile in @("轻量","标准","严格")) {
    Set-MinimalStartup $profile
    Check-Case ($profile + "-minimal-startup") "Startup" 0
    Check-Case ($profile + "-startup-not-release") "Release" 1
    Set-MinimalIteration $profile
    Check-Case ($profile + "-minimal-iteration") "Iteration" 0
}
Set-MinimalStartup
Change-Manifest 'startup_scope_confirmed: true' 'startup_scope_confirmed: false'
Check-Case "startup-without-confirmation" "Startup" 1
Set-MinimalStartup
Set-Content -LiteralPath $evidence -Value '{"schema_version":1,"records":[]}' -Encoding UTF8
Check-Case "startup-without-evidence" "Startup" 1
Set-MinimalStartup "严格"
Change-Manifest 'risk_review_confirmed: true' 'risk_review_confirmed: false'
Check-Case "strict-startup-without-review" "Startup" 1
Set-MinimalIteration
Change-Iteration "baseline_path" "docs/missing.md"
Check-Case "iteration-missing-baseline" "Iteration" 1
Set-MinimalIteration
Change-Iteration "baseline_path" "../outside.md"
Check-Case "iteration-outside-baseline" "Iteration" 1
Set-MinimalIteration
Change-Iteration "baseline_path" "docs/00-项目治理/本轮变更.json"
Check-Case "iteration-self-baseline" "Iteration" 1
Set-MinimalIteration
Change-Iteration "business_change" $true
Check-Case "iteration-business-without-confirmation" "Iteration" 1
Change-Iteration "confirmation_ref" "synthetic new business approval"
Check-Case "iteration-business-confirmed" "Iteration" 0
Set-MinimalIteration
Change-Iteration "high_risk" $true
Check-Case "iteration-risk-requires-strict" "Iteration" 1
Set-MinimalIteration "严格"
Change-Iteration "high_risk" $true
Check-Case "iteration-risk-missing-evidence" "Iteration" 1
Set-MinimalIteration
Change-Iteration "impacted_gates" @("data_design_confirmed")
Check-Case "iteration-affected-gate-unconfirmed" "Iteration" 1
Change-Manifest 'data_design_confirmed: false' 'data_design_confirmed: true'
Set-Content -LiteralPath $evidence -Value (@{schema_version=1;records=@($records | Where-Object gate -eq "data_design_confirmed")} | ConvertTo-Json -Depth 6) -Encoding UTF8
Check-Case "iteration-only-affected-gate" "Iteration" 0
Set-MinimalIteration
Change-Iteration "impacted_gates" @("release_authorized")
Check-Case "iteration-invalid-gate" "Iteration" 1
Set-MinimalIteration
Change-Iteration "impacted_gates" @("data_design_confirmed","data_design_confirmed")
Check-Case "iteration-duplicate-gate" "Iteration" 1
Set-MinimalIteration
Change-Iteration "high_risk" "false"
Check-Case "iteration-string-boolean" "Iteration" 1
Set-MinimalIteration
Change-Iteration "validation_plan" "待填写"
Check-Case "iteration-missing-validation-plan" "Iteration" 1
Set-MinimalIteration
Copy-Item -LiteralPath (Join-Path $root "docs/00-项目治理/本轮变更.json") -Destination $changePath
Check-Case "iteration-placeholder-record" "Iteration" 1

# 以下为 2.8 行为案例，保留前后历史 55 项预期不变。
function Set-UiProfile {
    param([string]$Value)
    $text = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8
    $text = [regex]::Replace($text, '(?ms)(^ui:\s*\r?\n.*?^  profile: )[^\r\n]+', ('$1"' + $Value + '"'))
    Set-Content -LiteralPath $manifest -Value $text -Encoding UTF8
}
Reset-Fixture
Check-Case "non-ai-ordinary-development" "Development" 0
Check-Case "business-cannot-use-template-maintenance" "TemplateMaintenance" 1
Reset-Fixture
Change-Manifest 'frontend: "不适用"' 'frontend: "适用"'
Change-Manifest 'backend: "不适用"' 'backend: "适用"'
Set-UiProfile "general-ui"
Check-Case "frontend-backend-general-development" "Development" 0
Check-Case "frontend-backend-general-release" "Release" 0
Set-UiProfile "enterprise-web"
Check-Case "enterprise-web-startup" "Startup" 0
Set-UiProfile "invalid-profile"
Check-Case "invalid-ui-profile-blocked" "Development" 1
Reset-Fixture
Change-Manifest 'ai: "不适用"' 'ai: "适用"'
Change-Manifest 'rag: "不适用"' 'rag: "适用"'
Check-Case "ai-rag-development" "Development" 0
Check-Case "ai-rag-release" "Release" 0
Change-Manifest 'ai: "适用"' 'ai: "不适用"'
Check-Case "rag-without-ai-blocked" "Development" 1
Set-MinimalIteration
Change-Manifest 'rag: "不适用"' 'rag: "待确认"'
Change-Manifest 'frontend: "不适用"' 'frontend: "待确认"'
Check-Case "iteration-unaffected-modules-not-rejudged" "Iteration" 0
Change-Iteration "affected_modules" @("rag")
Check-Case "iteration-affected-unknown-module-blocked" "Iteration" 1
Set-MinimalIteration
Change-Iteration "affected_modules" @("not-a-module")
Check-Case "iteration-invalid-module-blocked" "Iteration" 1
Change-Iteration "affected_modules" @("ai","ai")
Check-Case "iteration-duplicate-module-blocked" "Iteration" 1
Change-Iteration "affected_modules" "ai"
Check-Case "iteration-string-modules-blocked" "Iteration" 1
Set-MinimalIteration
Change-Iteration "affected_modules" @("deployment")
Check-Case "iteration-deployment-draft-evidence-blocked" "Iteration" 1
$operationIndex = @(Get-Content -LiteralPath $index -Encoding UTF8 | ForEach-Object {
    if ($_ -match 'docs/07-部署与运维/(部署与回滚方案|监控与运行手册)\.md') { $_.Replace('|模板|','|已确认|') } else { $_ }
})
Set-Content -LiteralPath $index -Value $operationIndex -Encoding UTF8
Check-Case "iteration-deployment-relevant-evidence" "Iteration" 0

# 检查子目录规则契约和归档规则隔离；每个负例输入均保留日志。
Reset-Fixture
$childRulePath = Join-Path $fixture "backend/AGENTS.md"
$validChild = "scope: backend/`nauthority: supplemental`n`n# 后端局部约束`n遵循根入口，仅约定本目录的接口错误格式。"
Set-Content -LiteralPath $childRulePath -Value $validChild -Encoding UTF8
Check-Case "scoped-child-agents-allowed" "Development" 0
Set-Content -LiteralPath $childRulePath -Value $validChild.Replace('scope: backend/','scope: frontend/') -Encoding UTF8
Check-Case "scoped-child-wrong-directory-blocked" "Development" 1
Set-Content -LiteralPath $childRulePath -Value $validChild.Replace('authority: supplemental','authority: global') -Encoding UTF8
Check-Case "scoped-child-global-authority-blocked" "Development" 1
Set-Content -LiteralPath $childRulePath -Value ($validChild + "`n" + (Get-Content -LiteralPath (Join-Path $fixture "AGENTS.md") -Raw -Encoding UTF8)) -Encoding UTF8
Check-Case "scoped-child-root-copy-blocked" "Development" 1
Set-Content -LiteralPath $childRulePath -Value $validChild -Encoding UTF8
$archiveRule = Join-Path $fixture "docs/.staging/AGENTS.md"
Set-Content -LiteralPath $archiveRule -Value "authority: global`nscope: /`nTHIS IS INVALID HISTORICAL TEST DATA" -Encoding UTF8
Check-Case "archived-invalid-rules-excluded" "Development" 0

# 选择性复制文件创建新的稀疏业务项目，不删除可选模板。
Reset-Fixture
$fullChecker = $checker
$sparse = Join-Path $runRoot "sparse-project"
New-Item -ItemType Directory -Path $sparse | Out-Null
foreach ($file in Get-ChildItem -LiteralPath $fixture -Recurse -File) {
    $rel = $file.FullName.Substring($fixture.Length + 1).Replace('\','/')
    if ($rel -match '^(\.git/|docs/\.staging/|docs/04-AI设计/|docs/05-专项设计/|prompts/|frontend/|backend/|deployment/)' -or $rel -eq 'docs/03-架构设计/前端交互与组件基线.md' -or $rel -eq 'docs/06-测试与验收/AI评测方案.md') { continue }
    $destination = Join-Path $sparse $rel
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $destination
}
& git -C $sparse init --quiet
if ($LASTEXITCODE -ne 0) { throw "Sparse fixture Git init failed" }
$checker = Join-Path $sparse "scripts/Test-ProjectReadiness.ps1"
Check-Case "sparse-non-ai-no-optional-templates-startup" "Startup" 0
Check-Case "sparse-non-ai-no-optional-templates-development" "Development" 0
Check-Case "sparse-non-ai-no-optional-templates-release" "Release" 0
$sparseManifest = Join-Path $sparse "PROJECT.yaml"
$sparseText = Get-Content -LiteralPath $sparseManifest -Raw -Encoding UTF8
Set-Content -LiteralPath $sparseManifest -Value $sparseText.Replace('ai: "不适用"','ai: "适用"') -Encoding UTF8
Check-Case "sparse-enabled-ai-missing-design-blocked" "Release" 1
foreach ($rel in @("docs/04-AI设计/AI能力边界.md","docs/04-AI设计/RAG知识库设计.md")) {
    $destination = Join-Path $sparse $rel
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $fixture $rel) -Destination $destination
}
Set-Content -LiteralPath $sparseManifest -Value $sparseText.Replace('ai: "不适用"','ai: "适用"').Replace('rag: "不适用"','rag: "适用"') -Encoding UTF8
Check-Case "sparse-ai-rag-no-semantic-template" "Release" 0
$checker = $fullChecker

# 通过新的复制范围构造缺少可选模板的项目，母版清单检查必须失败。
$templateProbe = Join-Path $runRoot "incomplete-template"
New-Item -ItemType Directory -Path $templateProbe | Out-Null
foreach ($rel in $requiredFiles) {
    if ($rel.Replace('\','/') -eq "docs/04-AI设计/RAG知识库设计.md") { continue }
    $destination = Join-Path $templateProbe $rel
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root $rel) -Destination $destination
}
foreach ($rel in $requiredDirectories) { New-Item -ItemType Directory -Path (Join-Path $templateProbe $rel) -Force | Out-Null }
$probeOutput = @(& $hostExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts/Test-TemplateRegression.ps1") -TemplateRoot $templateProbe -StructureOnly 2>&1)
$probeExit = $LASTEXITCODE
$probeOutput | Set-Content -LiteralPath (Join-Path $runRoot "template-missing-optional-module.log") -Encoding UTF8
$results += [PSCustomObject]@{ Case="template-missing-optional-module"; Level="TemplateRegression"; Expected=1; Actual=$probeExit; Passed=($probeExit -eq 1) }

Reset-Fixture
Add-Content -LiteralPath (Join-Path $fixture ".gitignore") -Value "`n!PROJECT.yaml" -Encoding UTF8
Check-Case "release-dirty-worktree" "Release" 1
$results | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runRoot "results.json") -Encoding UTF8
$results | Format-Table -AutoSize
Write-Host "Synthetic evidence retained at: $runRoot"
if (@($results | Where-Object { -not $_.Passed }).Count -gt 0) { exit 1 }
exit 0
