# v131 数据流与状态边界

## 1. CPU prepare

`prepare.main` 轮转来源目录，重新核验独立 reference/source teacher scope。`selection.select_fresh` 在所有 train/validation/test 的 reserve/rank/LIMIT 前应用 SQL 临时 exclusion 表；修复了旧版选完再删旧 body 导致 heldout 消失的问题。

只在原 queue 锁内分配一次 job；保留原 split。原文通过 SHA/指针适配器读取、评测隔离和 exact 库存检查，落为 `candidates.parquet`。每候选生成独立原始 QA Batch、协议 key、新旧排除证明和输入文件 SHA。最后发布 durable queue item。pressure/backlog 不通过只延后新增。

## 2. CPU → GPU transport

先写唯一 TRANSFER_INTENT，创建目标目录、rsync review payload（排除大份 candidates.parquet），远端逐 SHA 核验后创建 inbox，最后写 TRANSFERRED。原文大候选始终留 CPU 主机。传输结果未知不得重做启动/分配操作。

## 3. GPU consumer / worker

模型按实际 PID/startticks/cgroup/InvocationID 绑定，复用既有透明 aliases，不重启。逻辑 GPU 槽位是路由编号，不等于物理 GPU 数。每 lane 当前 8 个请求动态 refill，并发只由本 lane worker 提供。

协议固定完整正文、compact64 证据格式、8 evidence/3 findings、max output 2048、temperature 0；上下文/实际 teacher tokenizer 准入。不截断原文。前一请求未知即停止新增，排空已在途请求并保留原账本/结果。不会补 JSON 或自动重发。

## 4. Import / publisher

导入先检验 COMPLETE terminal、Batch/teacher/body/protocol identity、物理 JSONL 与每私有 SQL result 逐项一致。只有完整有效的 scope 入发布队列。来源校准 terminal 不计 READY。

主端发布队列容量 2。`publishing=pub.unfinished_tasks` **不是发布 worker 数**，例如值 3 表示 1 个处理+2 个排队。publisher 是唯一线程，调用原容量门、writer 锁和 full release engine；近重复过滤内部允许 4 CPU workers。

## 5. READY

必须同时满足：

1. 原 reference/source/individual 或完整 rolling 审计门；
2. 全库存 exact/near、family/split/heldout/evaluation 隔离及来源政策；
3. 固定 tokenizer、4096 pack 和物理 loader 校验；
4. 五项原发布门的全部证据 SHA；
5. READY receipt SHA 等于唯一 SQL releases.receipt_sha；
6. 正文计数等于该 batch 的 SQL documents 中 split=train 的 tokens SUM；
7. document index / manifest / 每个 bin、idx 的 SHA 和大小。

验证成功后才反馈同来源下一批。不同来源可重叠，但所有全局发布提交仍串行。

## 6. 冻结与恢复

CONFIG/代码/输入 scope 冻结。任何 intent 或 partial 不允许重启原控制器以“重试”。已完整可证的旧 GPU 分数允许独立 CPU-only 接续，但必须绑定原文件、原 candidate/protocol/teacher/terminal/ledger，不重新发教师请求。

公开源码没有现场 CONFIG、RECOVERY_PLAN 或授权；源码中的特定旧 job 允许列表仅展示严格恢复机制，不是可公开执行的部署计划。
