# Prompt 目录说明

编号 Prompt 是软件研发协作入口与门禁，不是人为停止点。已授权开发、验证或修复在必要门禁通过后继续；只读请求保持只读。入口与裁剪以 docs/00-项目治理/分级执行与裁剪规则.md 为准。

|文件|任务焦点|
|-|-|
|01_需求分析启动Prompt.md|启动约定、最小闭环，通过门禁后继续已授权开发|
|02_业务设计Prompt.md|本轮相关对象、流程、规则和权限|
|03_架构设计Prompt.md|本轮架构、数据、复用和契约变化|
|04_AI能力设计Prompt.md|实际触及的 AI/RAG/Agent 设计|
|05_开发Prompt.md|实现或分级缺陷修复|
|06_测试验收Prompt.md|受影响验证、失败修复与真实结果|
|07_部署交付Prompt.md|Release 或实际部署运行任务|
|08_复盘沉淀Prompt.md|相关结果与可复用资产|

业务入口为 Startup、Iteration、Release；Development 仅兼容完整设计评审。母版入口为 Audit、TemplateMaintenance、TemplateRegression。只读审计不初始化、不登记业务门禁、不生成记录。

仅读取当前任务相关的已确认事实及设计，复用已有适用性；普通读取排除 docs/.staging。system/、task/、evaluation/ 存放运行时 Prompt，history/ 保存被替代版本；这些资产不等同于协作阶段 Prompt。运行时资产统一按 docs/04-AI设计/Prompt资产管理.md 登记和验证，材料抽取专项不自动推广到通用 Prompt。
