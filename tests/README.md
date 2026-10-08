# 普通版测试与回放入口

日期：2026-10-08。普通版默认离线测试是tests目录 `test_*.py`，在仓库根运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
node tests/test_frontend_runtime.cjs
```

Python套件核对身份、真实父链、条件、属性投影、统计、请求变更、会话、导入和错误边界；不少测试使用默认CSV与已知数量，不具备原始授权数据时不能据此宣称完整回归通过。套件会创建临时HTTP服务和目录，但不调用真实模型或改变既有腾讯云服务。本轮实际534项结果见交接核验记录。

`test_frontend_runtime.cjs`使用模拟DOM验证HTTP环境下页面初始化和会话生成，不是浏览器视觉验收。其他cjs文件包含真实页面、指定网址或Playwright依赖，不属于这一离线入口。

`replay_*.py`、`compare_*.py`、`run_acceptance.py`、`run_cloud_replay.py`等用于历次真实模型/指定服务对照。有些配置本机或云端目标、输出docs/.staging，也可能调用模型产生费用。执行前打开脚本核对URL、依赖、凭据来源、数据快照与问题集；不要对所有脚本做无差别批量运行。第三轮原问题本轮未重跑，不能从534项通过推断第三轮关闭。

测试预期应从独立原始行/父链得出。记录完整会话、选定主体、代码/Prompt版本、模型实际标识、结果和时延；旧断言失败与有据勘误分开。原始回放输出属于本地证据，不随Git推送，工程结论在docs/06-测试与验收唯一源登记。
