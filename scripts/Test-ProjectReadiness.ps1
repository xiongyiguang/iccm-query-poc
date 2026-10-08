[CmdletBinding()]
param(
    [ValidateSet("Structure", "Audit", "TemplateMaintenance", "TemplateRegression", "Startup", "Iteration", "Development", "Release")]
    [string]$Level = "Structure"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDirectory ".."))
$findings = @()

function Add-Finding {
    param(
        [ValidateSet("PASS", "WARN", "ERROR")]
        [string]$Severity,
        [string]$Check,
        [string]$Message
    )

    $script:findings += [PSCustomObject]@{
        Severity = $Severity
        Check = $Check
        Message = $Message
    }
}

function Get-YamlSectionValue {
    param(
        [string[]]$Lines,
        [string]$Section,
        [string]$Key
    )

    $currentSection = ""
    foreach ($line in $Lines) {
        if ($line -match '^([A-Za-z_][A-Za-z0-9_-]*):\s*$') {
            $currentSection = $Matches[1]
            continue
        }

        if ($currentSection -eq $Section -and $line -match ('^  ' + [regex]::Escape($Key) + ':\s*(.*?)\s*$')) {
            return $Matches[1].Trim('"')
        }
    }

    return $null
}

# 完整可选模板清单由 Test-TemplateRegression.ps1 检查。
$requiredFiles = @("AGENTS.md", "PROJECT.yaml", "docs/README.md", ".gitignore", "docs/00-项目治理/分级执行与裁剪规则.md")
$requiredDirectories = @("docs")

foreach ($relativePath in $requiredFiles) {
    $fullPath = Join-Path $projectRoot $relativePath
    if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
        Add-Finding "PASS" "File" $relativePath
    }
    else {
        Add-Finding "ERROR" "File" "缺少 $relativePath"
    }
}

foreach ($relativePath in $requiredDirectories) {
    $fullPath = Join-Path $projectRoot $relativePath
    if (Test-Path -LiteralPath $fullPath -PathType Container) {
        Add-Finding "PASS" "Directory" $relativePath
    }
    else {
        Add-Finding "ERROR" "Directory" "缺少 $relativePath"
    }
}

$manifestPath = Join-Path $projectRoot "PROJECT.yaml"
$manifestLines = @()
$isTemplate = $null
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    $manifestLines = @(Get-Content -LiteralPath $manifestPath -Encoding UTF8)
    $isTemplate = Get-YamlSectionValue $manifestLines "template" "is_template"
    $templateVersion = Get-YamlSectionValue $manifestLines "template" "version"
    $projectName = Get-YamlSectionValue $manifestLines "project" "name"
    $projectStage = Get-YamlSectionValue $manifestLines "project" "stage"
    $projectShape = Get-YamlSectionValue $manifestLines "project" "shape"
    $projectDeliveryGoal = Get-YamlSectionValue $manifestLines "project" "delivery_goal"

    if ($isTemplate -in @("true", "false")) {
        Add-Finding "PASS" "Manifest" "template.is_template=$isTemplate"
    }
    else {
        Add-Finding "ERROR" "Manifest" "template.is_template 缺失或无效"
    }

    if ([string]::IsNullOrWhiteSpace($templateVersion)) {
        Add-Finding "ERROR" "Manifest" "缺少 template.version"
    }
    else {
        Add-Finding "PASS" "Manifest" "template.version=$templateVersion"
    }

    if ($isTemplate -eq "true") {
        if ($projectName -eq "待初始化" -and $projectStage -eq "00-未初始化" -and $projectShape -eq "待确认") {
            Add-Finding "PASS" "TemplateState" "母版身份未被项目内容污染"
        }
        else {
            Add-Finding "ERROR" "TemplateState" "母版状态与项目名称/阶段不一致"
        }
        if (Test-Path -LiteralPath (Join-Path $projectRoot ".git")) {
            Add-Finding "ERROR" "TemplateGit" "母版目录不应包含 .git，以免复制仓库历史"
        }
        else {
            Add-Finding "PASS" "TemplateGit" "母版未初始化 Git"
        }
    }
    elseif ($isTemplate -eq "false") {
        if ([string]::IsNullOrWhiteSpace($projectName) -or $projectName -eq "待初始化") {
            Add-Finding "ERROR" "ProjectState" "项目名称尚未初始化"
        }
        else {
            Add-Finding "PASS" "ProjectState" "project.name=$projectName"
        }
        if ($projectStage -eq "00-未初始化") {
            Add-Finding "ERROR" "ProjectState" "项目阶段仍为未初始化"
        }
    }
}

$indexPath = Join-Path $projectRoot "docs\README.md"
$indexContent = ""
if (Test-Path -LiteralPath $indexPath -PathType Leaf) {
    $indexContent = Get-Content -LiteralPath $indexPath -Raw -Encoding UTF8
}

# 只遍历当前来源，不解析归档规则或依赖元数据。
function Get-CurrentRuleFiles {
    param([string]$Directory)
    foreach ($entry in Get-ChildItem -LiteralPath $Directory -Force) {
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
        if ($entry.PSIsContainer) {
            if ($entry.Name -notin @(".staging", ".git", "node_modules", ".venv", "dist", "build")) { Get-CurrentRuleFiles $entry.FullName }
        } elseif ($entry.Name -like "AGENTS*.md") { $entry }
    }
}
$rootSpec = Join-Path $projectRoot "AGENTS.md"
$rootText = if (Test-Path -LiteralPath $rootSpec) { (Get-Content -LiteralPath $rootSpec -Raw -Encoding UTF8).Trim() } else { "" }
foreach ($rule in @(Get-CurrentRuleFiles $projectRoot | Where-Object FullName -ne $rootSpec)) {
    $relativeScope = $rule.DirectoryName.Substring($projectRoot.Length).TrimStart('\').Replace('\','/') + "/"
    $ruleText = Get-Content -LiteralPath $rule.FullName -Raw -Encoding UTF8
    $scopeMatches = [regex]::Matches($ruleText, '(?m)^scope:\s*([^\r\n]+)\s*$')
    $authorityMatches = [regex]::Matches($ruleText, '(?m)^authority:\s*supplemental\s*$')
    $declaredScope = if ($scopeMatches.Count -eq 1) { $scopeMatches[0].Groups[1].Value.Trim() } else { "" }
    if ($rule.Name -ne "AGENTS.md" -or $relativeScope -eq "/" -or $declaredScope -ne $relativeScope -or $authorityMatches.Count -ne 1) {
        Add-Finding "ERROR" "ScopedAuthority" "局部 AGENTS 必须声明实际目录 scope 与 authority: supplemental：$($rule.FullName)"
    } elseif ($rootText.Length -gt 0 -and $ruleText.Replace("`r", "").Contains($rootText.Replace("`r", ""))) {
        Add-Finding "ERROR" "ScopedAuthority" "局部规范不得复制完整根规范：$($rule.FullName)"
    } else { Add-Finding "PASS" "ScopedAuthority" "$relativeScope 局部补充；语义冲突仍须人工/AI审查" }
}

foreach ($obsoletePath in @("docs\05-智能审核专项", "docs\07-项目沉淀")) {
    if (Test-Path -LiteralPath (Join-Path $projectRoot $obsoletePath)) {
        Add-Finding "ERROR" "ObsoletePath" "仍存在旧目录 $obsoletePath"
    }
}

$gitignorePath = Join-Path $projectRoot ".gitignore"
if (Test-Path -LiteralPath $gitignorePath -PathType Leaf) {
    $gitignoreContent = Get-Content -LiteralPath $gitignorePath -Raw -Encoding UTF8
    foreach ($pattern in @(".env", "*.key", "node_modules/", ".venv/", "inputs/*", "docs/.staging/*")) {
        if (-not $gitignoreContent.Contains($pattern)) {
            Add-Finding "ERROR" "GitIgnore" "缺少规则 $pattern"
        }
    }
}

# 登记结构检查不能证明语义正确或授权真实。
function Test-EvidencePath {
    param([string]$RelativePath, [switch]$AllowRecorded)
    if ([string]::IsNullOrWhiteSpace($RelativePath) -or [IO.Path]::IsPathRooted($RelativePath)) { return $false }
    try {
        $full = [IO.Path]::GetFullPath((Join-Path $projectRoot $RelativePath))
        $docsRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "docs")) + [IO.Path]::DirectorySeparatorChar
        $stageRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "docs/.staging")) + [IO.Path]::DirectorySeparatorChar
        if (-not $full.StartsWith($docsRoot, [StringComparison]::OrdinalIgnoreCase) -or $full.StartsWith($stageRoot, [StringComparison]::OrdinalIgnoreCase)) { return $false }
        # 同时拒绝联接点或符号链接越界，以及文本路径穿越。
        $itemPath = $full
        while ($itemPath -ne $projectRoot) {
            $item = Get-Item -LiteralPath $itemPath -ErrorAction Stop
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $false }
            $itemPath = Split-Path -Parent $itemPath
        }
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { return $false }
        if ([string]::IsNullOrWhiteSpace((Get-Content -LiteralPath $full -Raw -Encoding UTF8))) { return $false }
        $canonical = $full.Substring($projectRoot.Length + 1).Replace('\', '/')
        $sourceRows = @($indexContent -split "`r?`n" | Where-Object { $_.Contains(('`' + $canonical + '`')) })
        if ($sourceRows.Count -ne 1) { return $false }
        $sourceCells = @($sourceRows[0].Split('|'))
        $allowedStates = @("已确认", "已交付")
        if ($AllowRecorded) { $allowedStates += "已记录" }
        return ($sourceCells.Count -gt 6 -and $sourceCells[6].Trim() -in $allowedStates)
    }
    catch { return $false }
}

$evidenceRecords = @()
function Test-GateEvidence {
    param([string]$Gate)
    $matchesForGate = @($evidenceRecords | Where-Object { $_.gate -eq $Gate })
    if ($matchesForGate.Count -ne 1) {
        Add-Finding "ERROR" "GateEvidence" "$Gate 必须有且只有一条证据记录"
        return
    }
    $record = $matchesForGate[0]
    foreach ($key in @("status", "confirmed_by", "confirmed_at", "confirmation_ref", "evidence_path")) {
        if ($record.PSObject.Properties.Name -notcontains $key -or $record.$key -isnot [string] -or [string]::IsNullOrWhiteSpace($record.$key) -or $record.$key -in @("待确认", "待填写")) {
            Add-Finding "ERROR" "GateEvidence" "$Gate 缺少有效的 $key"
            return
        }
    }
    $parsedDate = [datetime]::MinValue
    if ($record.status -ne "已确认" -or -not [datetime]::TryParseExact($record.confirmed_at, "yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$parsedDate)) {
        Add-Finding "ERROR" "GateEvidence" "$Gate 状态或确认日期无效"
    }
    if (-not (Test-EvidencePath $record.evidence_path)) {
        Add-Finding "ERROR" "GateEvidence" "$Gate 证据必须指向项目内 docs 下已索引的非空唯一源，禁止暂存路径、链接和越界"
    }
}

if ($Level -in @("Audit", "TemplateMaintenance", "TemplateRegression")) {
    if ($isTemplate -ne "true") { Add-Finding "ERROR" "TemplateEntry" "此入口仅用于母版自身；业务项目使用对应业务入口" }
    else { Add-Finding "PASS" "TemplateEntry" "母版身份有效，无业务初始化或门禁登记要求；实际回归由 Test-TemplateRegression.ps1 执行" }
}

$profile = Get-YamlSectionValue $manifestLines "execution" "profile"
$schemaLine = @($manifestLines | Where-Object { $_ -match '^schema_version:\s*3\s*$' })
if ($schemaLine.Count -ne 1) { Add-Finding "ERROR" "Schema" "需要 schema_version: 3；旧项目请按升级说明迁移" }
if ($profile -notin @("待确认", "轻量", "标准", "严格")) { Add-Finding "ERROR" "Profile" "执行档位缺失或无效" }

$iterationGates = @()
$iterationHighRisk = $false
$iterationModules = @()
function Read-IterationRecord {
    try {
        $path = "docs/00-项目治理/本轮变更.json"
        if (-not (Test-EvidencePath $path -AllowRecorded)) { throw "本轮变更必须已索引且已记录，禁止空白、暂存或越界" }
        $change = Get-Content -LiteralPath (Join-Path $projectRoot $path) -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($change.schema_version -ne 1) { throw "本轮变更需要结构版本1" }
        foreach ($key in @("change_id", "request_ref", "baseline_path", "baseline_version", "scope", "impact_reason", "validation_plan")) {
            if ($change.PSObject.Properties.Name -notcontains $key -or $change.$key -isnot [string] -or [string]::IsNullOrWhiteSpace($change.$key) -or $change.$key -in @("待填写", "待确认")) { throw "本轮变更缺少 $key" }
        }
        if (-not (Test-EvidencePath $change.baseline_path) -or $change.baseline_path -eq $path) { throw "必须引用已确认的业务基线，不能自引用本轮变更" }
        if ($change.high_risk -isnot [bool] -or $change.business_change -isnot [bool] -or $change.impacted_gates -isnot [array]) { throw "风险/业务变化必须为布尔值，impacted_gates必须为数组" }
        if ($change.business_change -and ($change.PSObject.Properties.Name -notcontains "confirmation_ref" -or $change.confirmation_ref -isnot [string] -or [string]::IsNullOrWhiteSpace($change.confirmation_ref) -or $change.confirmation_ref -in @("待填写", "待确认"))) { throw "业务变化缺少本次确认来源" }
        $allowed = @("product_strategy_confirmed", "requirements_confirmed", "business_design_confirmed", "reuse_assessment_confirmed", "architecture_confirmed", "data_design_confirmed", "acceptance_criteria_confirmed", "acceptance_scenarios_confirmed", "regression_boundary_confirmed", "vertical_slice_defined", "test_plan_confirmed", "ai_boundary_confirmed", "semantic_extraction_design_confirmed", "interaction_baseline_confirmed")
        foreach ($gate in $change.impacted_gates) {
            if ($gate -isnot [string] -or $gate -notin $allowed) { throw "非法受影响门禁：$gate" }
        }
        if (@($change.impacted_gates | Select-Object -Unique).Count -ne $change.impacted_gates.Count) { throw "受影响门禁不得重复" }
        if ($change.PSObject.Properties.Name -contains "affected_modules") {
            if ($change.affected_modules -isnot [array]) { throw "affected_modules 必须为数组" }
            foreach ($module in $change.affected_modules) {
                if ($module -isnot [string] -or $module -notin @("frontend","backend","ai","semantic_extraction","rag","agent","intelligent_audit","deployment")) { throw "未知受影响模块：$module" }
            }
            if (@($change.affected_modules | Select-Object -Unique).Count -ne $change.affected_modules.Count) { throw "受影响模块不得重复" }
            $script:iterationModules = @($change.affected_modules)
        }
        $script:iterationGates = @($change.impacted_gates)
        $script:iterationHighRisk = $change.high_risk
        if ($change.high_risk -and $profile -ne "严格") { throw "本轮高风险变更必须使用严格档" }
        Add-Finding "PASS" "Iteration" "已登记本轮范围、基线与验证计划；不代表已验证或授权真实性"
    }
    catch { Add-Finding "ERROR" "Iteration" $_.Exception.Message }
}

if ($Level -in @("Startup", "Iteration", "Development", "Release")) {
    if ($isTemplate -ne "false") {
        Add-Finding "ERROR" "DevelopmentGate" "母版不能进入开发或发布阶段"
    }
    else {
        $risk = Get-YamlSectionValue $manifestLines "execution" "high_risk"
        $rationale = Get-YamlSectionValue $manifestLines "execution" "rationale"
        if ($profile -notin @("轻量", "标准", "严格") -or $risk -notin @("是", "否") -or [string]::IsNullOrWhiteSpace($rationale) -or $rationale -eq "待确认") {
            Add-Finding "ERROR" "Profile" "执行档位、风险及依据尚未明确"
        }
        if ($risk -eq "是" -and $profile -ne "严格") { Add-Finding "ERROR" "Profile" "高风险事项必须采用严格档" }
        $registryPath = Get-YamlSectionValue $manifestLines "execution" "evidence_registry"
        if ($registryPath -ne "docs/00-项目治理/门禁证据.json") {
            Add-Finding "ERROR" "GateEvidence" "证据登记必须使用约定的唯一源路径"
        }
        else {
            try {
                $registry = Get-Content -LiteralPath (Join-Path $projectRoot $registryPath) -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($registry.schema_version -ne 1 -or $registry.records -isnot [array]) { throw "登记结构必须为版本1及 records 数组" }
                foreach ($entry in $registry.records) {
                    if ($null -eq $entry -or $entry.PSObject.Properties.Name -notcontains "gate" -or $entry.gate -isnot [string] -or [string]::IsNullOrWhiteSpace($entry.gate)) { throw "存在无效 gate" }
                    if ($null -eq (Get-YamlSectionValue $manifestLines "governance" $entry.gate)) { throw "未知 gate：$($entry.gate)" }
                }
                $evidenceRecords = @($registry.records)
                if (@($evidenceRecords | Group-Object gate | Where-Object Count -gt 1).Count -gt 0) { throw "gate 不得重复" }
            }
            catch { Add-Finding "ERROR" "GateEvidence" "证据登记无效：$($_.Exception.Message)" }
        }
        if ([string]::IsNullOrWhiteSpace($projectShape) -or $projectShape -eq "待确认") {
            Add-Finding "ERROR" "DevelopmentGate" "project.shape 尚未按实际项目确认"
        }
        else {
            Add-Finding "PASS" "DevelopmentGate" "project.shape=$projectShape"
        }

        if ([string]::IsNullOrWhiteSpace($projectDeliveryGoal) -or $projectDeliveryGoal -eq "待确认") {
            Add-Finding "ERROR" "DevelopmentGate" "project.delivery_goal 尚未确认"
        }
        else {
            Add-Finding "PASS" "DevelopmentGate" "project.delivery_goal 已确认"
        }

        if ($Level -eq "Iteration") { Read-IterationRecord }
        $allModules = @("frontend", "backend", "ai", "semantic_extraction", "rag", "agent", "intelligent_audit")
        $applicabilityValues = @{}
        foreach ($module in $allModules) { $applicabilityValues[$module] = Get-YamlSectionValue $manifestLines "applicability" $module }
        $modulesToCheck = @($allModules)
        if ($Level -eq "Iteration") {
            $modulesToCheck = @($iterationModules | Where-Object { $_ -ne "deployment" })
            if ($iterationGates -contains "interaction_baseline_confirmed") { $modulesToCheck += "frontend" }
            if ($iterationGates -contains "ai_boundary_confirmed") { $modulesToCheck += "ai"; $modulesToCheck += @("rag","agent","intelligent_audit" | Where-Object { $applicabilityValues[$_] -eq "适用" }) }
            if ($iterationGates -contains "semantic_extraction_design_confirmed") { $modulesToCheck += "semantic_extraction" }
        }
        if (@($modulesToCheck | Where-Object { $_ -in @("semantic_extraction","rag","agent","intelligent_audit") -and $applicabilityValues[$_] -eq "适用" }).Count -gt 0) { $modulesToCheck += "ai" }
        $modulesToCheck = @($modulesToCheck | Select-Object -Unique)
        foreach ($module in $modulesToCheck) {
            $value = $applicabilityValues[$module]
            if ($value -notin @("适用", "不适用")) { Add-Finding "ERROR" "Applicability" "本轮涉及的 applicability.$module 尚未明确" }
            else { Add-Finding "PASS" "Applicability" "复用 applicability.$module=$value" }
        }
        foreach ($module in @("semantic_extraction","rag","agent","intelligent_audit")) {
            if ($module -in $modulesToCheck -and $applicabilityValues[$module] -eq "适用" -and $applicabilityValues["ai"] -ne "适用") { Add-Finding "ERROR" "Applicability" "$module 启用须有 AI 能力边界" }
        }
        # 关闭 AI 时也必须处理此前已启用的依赖能力。
        if ("ai" -in $modulesToCheck -and $applicabilityValues["ai"] -eq "不适用" -and @("semantic_extraction","rag","agent","intelligent_audit" | Where-Object { $applicabilityValues[$_] -eq "适用" }).Count -gt 0) { Add-Finding "ERROR" "Applicability" "停用 AI 前必须处理仍启用的依赖能力" }
        if ("frontend" -in $modulesToCheck -and $applicabilityValues["frontend"] -eq "适用") {
            $uiProfile = Get-YamlSectionValue $manifestLines "ui" "profile"
            if ($null -eq $uiProfile) { Add-Finding "WARN" "UIProfile" "旧项目缺少 ui.profile，按通用基线继续；不降低冻结验收，后续登记" }
            elseif ($uiProfile -notin @("general-ui","enterprise-web")) { Add-Finding "ERROR" "UIProfile" "前端适用时须选择 general-ui 或 enterprise-web" }
        }

        $requiredGates = @("execution_profile_confirmed", "product_strategy_confirmed", "requirements_confirmed", "business_design_confirmed", "reuse_assessment_confirmed", "architecture_confirmed", "data_design_confirmed", "acceptance_criteria_confirmed", "acceptance_scenarios_confirmed", "regression_boundary_confirmed", "vertical_slice_defined", "test_plan_confirmed")
        if ($applicabilityValues["ai"] -eq "适用") {
            $requiredGates += "ai_boundary_confirmed"
        }
        if ($applicabilityValues["semantic_extraction"] -eq "适用") {
            $requiredGates += "semantic_extraction_design_confirmed"
        }
        if ($applicabilityValues["frontend"] -eq "适用") {
            $requiredGates += "interaction_baseline_confirmed"
        }

        if ($Level -eq "Startup") { $requiredGates = @("startup_scope_confirmed") }
        if ($Level -eq "Iteration") {
            $requiredGates = @($iterationGates)
        }
        if ($profile -eq "严格" -and ($Level -ne "Iteration" -or $iterationHighRisk)) { $requiredGates += "risk_review_confirmed" }
        foreach ($gate in $requiredGates) {
            Test-GateEvidence $gate
            $value = Get-YamlSectionValue $manifestLines "governance" $gate
            if ($value -eq "true") {
                Add-Finding "PASS" "DevelopmentGate" "$gate=true"
            }
            else {
                Add-Finding "ERROR" "DevelopmentGate" "$gate 尚未确认"
            }
        }

        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".git"))) {
            Add-Finding "ERROR" "DevelopmentGate" "项目尚未初始化 Git 仓库"
        }
        else {
            $gitProbe = @(& git -C $projectRoot rev-parse --is-inside-work-tree 2>$null)
            if ($LASTEXITCODE -ne 0 -or $gitProbe -notcontains "true") { Add-Finding "ERROR" "DevelopmentGate" "Git 元数据无效" }
            else { Add-Finding "PASS" "DevelopmentGate" "Git 工作区有效" }
        }

        $coreDocumentPaths = @(
            "docs/00-项目治理/阶段门禁与完成定义.md",
            "docs/00-项目治理/系统性问题解决方法论.md",
            "docs/01-需求分析/产品形态与研发策略.md",
            "docs/01-需求分析/需求清单与验收草案.md",
            "docs/02-业务设计/业务流程设计.md",
            "docs/02-业务设计/业务规则设计.md",
            "docs/03-架构设计/开源与现成方案调研.md",
            "docs/03-架构设计/技术选型记录.md",
            "docs/03-架构设计/系统架构设计.md",
            "docs/03-架构设计/数据模型设计.md",
            "docs/06-测试与验收/测试方案.md",
            "docs/06-测试与验收/验收场景设计.md"
        )
        if ($profile -eq "轻量") { $coreDocumentPaths = @("docs/00-项目治理/轻量项目执行简表.md") }
        $coreDocumentPaths += "docs/00-项目治理/分级执行与裁剪规则.md"
        if ($applicabilityValues["frontend"] -eq "适用") {
            $coreDocumentPaths += "docs/03-架构设计/前端交互与组件基线.md"
        }
        if ($applicabilityValues["ai"] -eq "适用") {
            $coreDocumentPaths += "docs/04-AI设计/AI能力边界.md"
        }
        if ($applicabilityValues["semantic_extraction"] -eq "适用") {
            $coreDocumentPaths += "docs/04-AI设计/非结构化材料语义抽取与模型输出治理.md"
        }
        $moduleDocuments = @{
            rag = @("docs/04-AI设计/RAG知识库设计.md")
            agent = @("docs/04-AI设计/Agent工作流设计.md")
            intelligent_audit = @("docs/05-专项设计/智能审核/审核链路设计.md", "docs/05-专项设计/智能审核/字段追踪设计.md", "docs/05-专项设计/智能审核/审核问题定位模型.md")
        }
        foreach ($module in $moduleDocuments.Keys) { if ($applicabilityValues[$module] -eq "适用") { $coreDocumentPaths += $moduleDocuments[$module] } }
        if ($Level -eq "Startup") { $coreDocumentPaths = @("docs/00-项目治理/轻量项目执行简表.md") }
        if ($Level -eq "Iteration") {
            $coreDocumentPaths = @()
            if ($iterationGates -contains "interaction_baseline_confirmed" -and $applicabilityValues["frontend"] -eq "适用") { $coreDocumentPaths += "docs/03-架构设计/前端交互与组件基线.md" }
            if ($iterationGates -contains "ai_boundary_confirmed" -and $applicabilityValues["ai"] -eq "适用") { $coreDocumentPaths += "docs/04-AI设计/AI能力边界.md" }
            if ($iterationGates -contains "semantic_extraction_design_confirmed" -and $applicabilityValues["semantic_extraction"] -eq "适用") { $coreDocumentPaths += "docs/04-AI设计/非结构化材料语义抽取与模型输出治理.md" }
            foreach ($module in $moduleDocuments.Keys) { if ($module -in $modulesToCheck -and $applicabilityValues[$module] -eq "适用") { $coreDocumentPaths += $moduleDocuments[$module] } }
            if ($iterationModules -contains "deployment") { $coreDocumentPaths += @("docs/07-部署与运维/部署与回滚方案.md", "docs/07-部署与运维/监控与运行手册.md") }
        }
        foreach ($documentPath in $coreDocumentPaths) {
            if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $documentPath) -PathType Leaf)) { Add-Finding "ERROR" "DevelopmentEvidence" "本轮适用文档缺失：$documentPath"; continue }
            $escapedPath = [regex]::Escape(('`' + $documentPath + '`'))
            $indexLine = @($indexContent -split "`r?`n" | Where-Object { $_ -match $escapedPath })
            if ($indexLine.Count -ne 1) {
                Add-Finding "ERROR" "DevelopmentEvidence" "文档索引中无法唯一定位 $documentPath"
                continue
            }
            $cells = @($indexLine[0].Split('|'))
            $status = if ($cells.Count -gt 6) { $cells[6].Trim() } else { "" }
            if ($status -in @("已确认", "已交付")) {
                Add-Finding "PASS" "DevelopmentEvidence" "$documentPath 状态=$status"
            }
            else {
                Add-Finding "ERROR" "DevelopmentEvidence" "$documentPath 仍为模板或状态无效"
            }
        }
    }
}

if ($Level -eq "Release") {
    $releaseGates = @("release_authorized")
    if ($profile -eq "严格") { $releaseGates += @("independent_review_confirmed", "rollback_validated") }
    foreach ($gate in $releaseGates) {
        if ((Get-YamlSectionValue $manifestLines "governance" $gate) -ne "true") { Add-Finding "ERROR" "ReleaseGate" "$gate 尚未确认" }
        Test-GateEvidence $gate
    }
    $releaseAuthorized = Get-YamlSectionValue $manifestLines "governance" "release_authorized"
    if ($releaseAuthorized -eq "true") {
        Add-Finding "PASS" "ReleaseGate" "release_authorized=true"
    }
    else {
        Add-Finding "ERROR" "ReleaseGate" "尚未获得发布授权"
    }

    foreach ($documentPath in @("docs/07-部署与运维/部署与回滚方案.md", "docs/07-部署与运维/监控与运行手册.md", "docs/07-部署与运维/发布检查表.md")) {
        $escapedPath = [regex]::Escape(('`' + $documentPath + '`'))
        $indexLine = @($indexContent -split "`r?`n" | Where-Object { $_ -match $escapedPath })
        $cells = if ($indexLine.Count -eq 1) { @($indexLine[0].Split('|')) } else { @() }
        $status = if ($cells.Count -gt 6) { $cells[6].Trim() } else { "" }
        if ($status -in @("已确认", "已交付") -and (Test-EvidencePath $documentPath)) {
            Add-Finding "PASS" "ReleaseEvidence" "$documentPath 状态=$status"
        }
        else {
            Add-Finding "ERROR" "ReleaseEvidence" "$documentPath 未达到发布检查状态"
        }
    }

    if (Test-Path -LiteralPath (Join-Path $projectRoot ".git")) {
        $gitStatus = @(& git -C $projectRoot status --porcelain 2>$null)
        if ($LASTEXITCODE -ne 0) {
            Add-Finding "ERROR" "ReleaseGate" "无法读取 Git 工作区状态"
        }
        elseif ($gitStatus.Count -gt 0) {
            Add-Finding "ERROR" "ReleaseGate" "Git 工作区存在未提交变更，不能建立可追溯发布基线"
        }
        else {
            Add-Finding "PASS" "ReleaseGate" "Git 工作区干净"
        }
    }
}

$summary = $findings | Group-Object Severity | ForEach-Object { "{0}={1}" -f $_.Name, $_.Count }
$errors = @($findings | Where-Object Severity -eq "ERROR")
$warnings = @($findings | Where-Object Severity -eq "WARN")

$findings | Where-Object Severity -ne "PASS" | Format-Table Severity, Check, Message -AutoSize
Write-Host "检查级别：$Level"
Write-Host "项目根目录：$projectRoot"
Write-Host ("结果汇总：" + ($summary -join ", "))

if ($errors.Count -gt 0) {
    exit 1
}

if ($warnings.Count -gt 0) {
    Write-Host "结构检查通过，但存在需要评估的警告。"
}
else {
    Write-Host "登记检查通过；不代表业务正确、授权真实或运行验收完成。"
}

exit 0

