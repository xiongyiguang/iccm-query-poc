# 本机Codex智能体演示

日期：2026-10-08；实现V4。通过官方本机Codex App Server实验接口调用固定只读工具，使用同一五份CSV及普通版数据执行器。独立监听127.0.0.1:8771，独立令牌、会话及缓存；未部署腾讯云。

Mac双击 `启动智能体.command`，或从仓库根运行 `python3 agent_demo/server.py --port 8771`。Python需3.11+，Codex需已安装、已登录、可联网调用模型。运行时发现顺序与数据路径见普通运行手册。默认模型gpt-6-luna，effort=low；页面模型选项不代表账户一定可用。

|文件|阅读目的|
|---|---|
|runtime.py|进程发现、JSONL协议、模型线程、动态工具调用与隔离开关|
|server.py|HTTP入口、会话、事件轮询、终态、一次补查|
|tools.py|固定工具目录、参数校验、业务执行与分页|
|bindings.py|显式主体的有据绑定与否定/歧义排除|
|answers.py|用真实工具回执形成答案，不采用模型计算数字|
|presentation.py|计划与回执映射到中文业务标签|
|knowledge.txt / query-guide.txt / completion-check.txt|知识V7、工具V4、补查V2|
|web/|独立页面、过程事件、结果与查询依据|

离线入口：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s agent_demo -p 'test_*.py'
```

测试需要原CSV，覆盖只读工具、标识、完整范围、分页、真实回执展示和知识约束，不调用Codex模型。live_smoke.py、compare_models.py、browser_live_test.cjs等是真实模型/页面实验，可能计费且需目标服务，不属于默认离线回归。

现有V6知识/V3工具对应29+13完整验证；最终V7/V4对应8步专项和2项UI记录，不能合并声称最终版完整29+13已复测。当前结构与验证唯一源见[本机Codex智能体演示](../docs/05-专项设计/本机Codex智能体演示.md)及[Agent工作流设计](../docs/04-AI设计/Agent工作流设计.md)。
