# 建议优先分析的问题

1. **近重复过滤**：`p0_parallel_near_v21.py` 的 SQLite postings JOIN/GROUP BY、每候选原文 ParquetPointer 读取、索引 query_only 和 reader 缓存上限。保持 minhash/threshold/ordered local merge 和全局 ledger snapshot 不变。
2. **未计时外围开销**：`p0_qwen_overnight_slot_v67._publish_locked` 到 release CLI 内核之间的重复质量检查、SHA 扫描/文件读取。阶段 timer 不覆盖所有 wall time。
3. **发布背压**：`primary.main` 的 `pub.full()` 会延后包括新 failure terminal 的观察/导入。不能通过跳过完整门禁来缓解。
4. **GPU 喂料**：prepare 单来源轮转、backlog=4、同来源 READY barrier 是否形成空档；逻辑 slot/lane 不等于物理 GPU。调参应使用真实连续 READY train-body/h，而不是 input token/s。
5. **请求超时**：8 并发下某个请求 240s 超时触发 unknown。不能重新提交未知原 key 来“补齐”。分析上下文、KV/输出长度、模型队列和冷却/压力，而不是放宽证据格式。
6. **分布式后处理**：让 GPU 主机 CPU 负责独立 tokenize/pack/验证或只读 near 子任务，主端保留唯一 stock/global dedup/ledger writer。需要 SHA 绑定任务、幂等传输、唯一提交和原 gate 等价测试。
7. **质量统计解释**：source_audit 分层样本批量路由与逐篇 individual 路由不是一回事。source keep signals 不能直接当成全库事实准确率。

此仓库保留当前代码与缺陷供审阅，不包含“GPU 主机 CPU 分担”尚未部署的假实现。提出补丁时不要直接修改冻结正在运行的版本；用独立版本和回归 fixture 证明行为等价。
