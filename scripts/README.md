# 脚本与工作入口

## 本项目当前入口（2026-10-08）

`macos-demo.py`读取本项目 `.local/deepseek-macos.key` 安全注入普通服务，优先使用Codex配套Python，复用已有8765服务，日志和PID保存在.local。它不自动加载.env。根目录 `打开演示.command` 调用此脚本并打开浏览器。

`agent_demo/启动智能体.command`运行独立8771服务，要求Python 3.11+和已登录本机Codex。跨平台直接运行backend/app.py或agent_demo/server.py；具体参数、文件关系和测试见[运行手册](../docs/07-部署与运维/监控与运行手册.md)。

以下PowerShell初始化及模板门禁为保留工程工具，本轮只翻译说明性注释，未在Mac执行PowerShell完整门禁。新环境不要对已经初始化的仓库重复运行Initialize-Project.ps1。

## 历史记录

以下记录保留各自日期的实现、环境、验证及限制；其中“当前”不表示2026-10-08交接状态。当前状态以文首及当前唯一源为准。

当前本机为 macOS：日常启动使用项目根目录 `打开演示.command`（调用 `macos-demo.py`），独立智能体使用 `agent_demo/启动智能体.command`。下面 PowerShell 工程母版脚本为保留的历史工具，不是 Mac 日常启动依赖；本轮未迁移或运行其完整门禁检查器。

本目录面向软件研发母版和业务项目，入口规则唯一源为 docs/00-项目治理/分级执行与裁剪规则.md。

|身份/入口|使用方式|检查范围|
|-|-|-|
|母版 Audit|只读检查；可选运行 Test-ProjectReadiness.ps1 -Level Audit|无初始化、业务门禁或生成记录|
|母版 TemplateMaintenance|修改母版，保留快照与版本；可选 -Level TemplateMaintenance 检查身份|不进入业务门禁；修改后运行模板回归|
|母版 TemplateRegression|Test-TemplateRegression.ps1；仅完整性可加 -StructureOnly|完整母版及可选模板；默认再执行合成回归|
|业务 Startup|Test-ProjectReadiness.ps1 -Level Startup|首次研发基线与首个闭环|
|业务 Iteration|Test-ProjectReadiness.ps1 -Level Iteration|既有基线、本轮 affected_modules/impacted_gates 及相关证据|
|业务 Release|Test-ProjectReadiness.ps1 -Level Release|当前适用设计、验收、授权、运行恢复与干净 Git 状态|
|兼容 Development|Test-ProjectReadiness.ps1 -Level Development|完整设计评审；不是默认开发入口|
|Structure|Test-ProjectReadiness.ps1 -Level Structure|基础登记结构；不能证明母版完整或业务验收|

## 初始化

复制并重命名后运行 Initialize-Project.ps1，登记项目名、类型、形态、交付目标等；默认建立独立 Git，不自动暂存、提交或配置远程。-DryRun 只验证；-SkipGit 可暂缓初始化，但业务实现门禁前需有有效 Git 工作区。母版自身不初始化。

```powershell
.\scripts\Initialize-Project.ps1 -ProjectName "库存同步服务" -ProjectType "企业集成" -ProjectShape "数据与集成服务" -ProjectDeliveryGoal "端到端同步闭环"
.\scripts\Test-ProjectReadiness.ps1 -Level Startup
.\scripts\Test-ProjectReadiness.ps1 -Level Iteration
.\scripts\Test-ProjectReadiness.ps1 -Level Release
```

## 职责与证据

TemplateRegression 保存完整可选文件清单；-StructureOnly 只读验证母版结构，可通过 -TemplateRoot 指定待检查副本。默认运行会在 docs/.staging/v2.8.0-validation/run-* 生成合成项目、逐例日志和结果；保留历史，不自动清理。合成确认明确标注测试专用，不代表真实批准或发布。

ProjectReadiness 不因可选模板存在而要求启用；Iteration 复用已有状态，仅检查本轮能力及设计门禁依赖。运维文档只在 Release 或 affected_modules 包含 deployment 时核对。子级 AGENTS.md 要声明 scope（项目相对目录/）与 authority: supplemental；检查器不判断全部自然语言冲突。

普通搜索和规则加载排除 docs/.staging；回归或历史对比读取时仍将其作为数据。返回 0 表示当前检查符合登记契约，1 表示存在错误；警告需评估。脚本不验证授权真实性，不替代实际测试、界面操作或现场验收。
