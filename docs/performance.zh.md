# 实测阶段耗时（2026-10-06）

> 历史 v131 说明/观察窗口，非 v144/v146 当前性能。最新链路见 [current-v144-v146.zh.md](current-v144-v146.zh.md)。

不是 benchmark，也不是稳态 READY/h。不同批次阶段存在重叠，不能把跨批时间相加作为整条管线 wall time。

## 当前英文批次观察窗口：61m59s，尚未 READY

| 阶段 | 秒 | 观察窗口占比 |
|---|---:|---:|
| CPU 分配后预热 | 657.93 | 17.69% |
| 预热完成至传输确认 | 32.93 | 0.89% |
| 确认至 GPU worker 启动 | 2.20 | 0.06% |
| GPU worker 启动至完整 terminal | 510.69 | 13.73% |
| 结果回传/导入 | 10.27 | 0.28% |
| 导入至发布开始：队列/发布前检查 | 1012.71 | 27.23% |
| 发布开始至快照，仍 dedup | 1492.23 | 40.12% |

GPU worker 内部 scheduler 另记录 506.06s；边界总时长包含 worker 启动/终态开销。跨机 unix 与少数 immutable marker mtime 用于相对边界；毫秒精度不应理解成严格同步分布式 trace。

## 已完成数学教材 CPU-only 恢复发布：2228.94s

| 已 instrument 的子阶段 | 秒 | 占完整发布 wall time |
|---|---:|---:|
| dedup | 1266.57 | 56.82% |
| normalize | 42.01 | 1.88% |
| freeze | 7.88 | 0.35% |
| pack | 78.86 | 3.54% |
| verify | 86.95 | 3.90% |
| ingest + quality stage marker | 0.044 | <0.01% |
| 未被分阶段计时覆盖的外围开销 | 746.62 | 33.50% |

`quality` stage marker 的 0.03s **不是全部质量审核成本**，不包含 GPU/reference/source 审计及发布外围扫描。未覆盖的 33.50% 尚不能分成 I/O/校验/锁等待，需新冻结版本补 trace。

## 当前定位

- 大头是全局 dedup + 单 writer 发布等待，不是几十秒传输。
- 有限 backlog 包含尚未发布 CPU 批次，发布慢会使 prepare 限流、部分 GPU 等输入/反馈。
- 每 lane 8 并发是当前参数，不是最佳吞吐已认证值。
- GPU 主机 CPU 接入 distributed pack worker 尚未实现；仅把训练包存储位置改变不会移走计算瓶颈。
- 另有逐篇数学 scope 因一条 240s 请求超时 fail-closed；有效结果和未处理队列保留、不重放。它不应被当成通过的完整批次。
