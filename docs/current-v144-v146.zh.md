# v144 主链路与 v146 GPU 0 补充链路

这是 2026-10-09 的生产源码审阅副本，不包含生产绑定配置，不可直接一键启动。

## 完整数据流

```mermaid
flowchart LR
  S[未分配 stock] --> D[领域缺口排序 / 新 body-key 排除]
  D --> P[CPU 完整候选 / 参考来源门 / 预热落盘]
  P --> T[压缩传输 review + 不变证明]
  T --> G[GPU 完整协议与 Merkle 不存在证明核验]
  G --> Q[每 backend 8 并发动态 refill]
  Q --> I[CPU 核验 terminal / 完整私有 ledger / 物理结果]
  I --> W[共享单 writer]
  W --> E[全库存 exact-near / eval-family-split-heldout]
  E --> K[4096 tokenize-pack / SHA / loader]
  K --> R[SQL train-body + READY receipt 验真]
  R -->|同 scope 下一批反馈| P
```

## 主链路 v144

`deficit.py` 排序依据目标领域缺口，不按库存比例直接训练采样。`reference.py`、
`runtime_cpu.py` 与 `grounding.py` 处理独立参考、明确 parser 运行环境及完整证据绑定。
`portable.py` 用全历史 body/key Merkle 根和相邻边界证明排除旧尝试；不是抽样去重。
`remote_wire.py` 在传输较大控制参数时使用有界压缩 stdin。
`drain.py` 必须完整观察 sealed job 列表与持久队列，避免晚到任务遗漏。

实际参考/source 未通过的 scope 保持 HOLD；是否允许逐篇回退只由原规则决定。
不因服务健康或队列创建成功将候选称为 READY。

## 补充链路 v146

只使用原 physical GPU 0 endpoint 的 FineWiki 中文独立 scope，不跨 endpoint 借教师证据。
原参考的完整 acceptance 实际通过但缺少旧调度期待的 marker：v146 重新核验
16 正例/16 负例和同教师协议，只读复制到新私有参考，不重跑校准、不改旧 block。

`parallel_guard.py` 绑定原 v144 不变边界：原 GPU 0 路线全部 blocked、相同 scope
不能竞争；排除所有旧 body/key、旧队列分配以及其他活跃来源潜在 stock，再在原
rank/LIMIT 之前选择新 stock。库存 `records.h` 主键、原 stock queue 锁与发布锁不变。
`competing_stock()` 使用真实 `files.source JOIN records` schema，测试禁止使用不存在的
`records.source`。

v146 至多一个非终态同 scope 批次，同上一批完整 READY 反馈后自动下一批。
不能因为还有 GPU 空闲就解除原屏障、清 unknown、放行 held stratum 或降低原质量门。

## 审阅性能时的边界

每 backend QA 8、CPU 发布 compute 4、backlog 4 是当前配置，不是最优性证明。
物理 GPU 利用率为瞬时观察，不能当成稳态 READY token/h。
逐篇 512 路线的文档数不等于批量分层审核 token 产出。
总量只计去重/隔离/打包/SQL/收据全部通过的 train 正文，不含教师输入、heldout 或 EOS。

## 不包含

模型/语料/tokenizer 实物、真实 body/key 列表、授权、启动 intent、CONFIG、
SOURCE_CATALOG、EXCLUSION_BASE、PARALLEL_SCOPE_BOUNDARY、私有 ledger 和实际 READY。
这些边界的算法与合成 fixture 测试公开，真实运行证据留在私有机器上。
