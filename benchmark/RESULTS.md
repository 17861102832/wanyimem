# wanyimem 公开基准结果（LongMemEval）

> 口径：LongMemEval（session 粒度检索）—— 把实例的会话按 turn 写入 wanyimem，用 question 召回，
> 判断证据会话（`answer_session_ids`）是否出现在 Top-K 命中会话中；跳过 30 条 abstention（官方惯例）。
> 每实例独立记忆库（符合官方独立评测，避免跨实例串扰）。
> 复现：`python benchmark/longmemeval_run.py --data <文件> --mode <core|full> --max-samples N`

## 结果

| 数据 | 模式 | 样本数 | Recall@5 | MRR | 说明 |
|---|---|---|---|---|---|
| oracle | core | 20 | **1.000** | **1.000** | 仅证据会话，最简单，全中 |
| s_cleaned | core | 50 | **0.960** | **0.907** | 含约 40 个干扰会话，难度高，最接近真实 |
| s_cleaned | full（bge-m3） | 待跑 | - | - | 多语言向量 + 精排，最强形态 |
| m_cleaned | 待跑 | - | - | - | ~500 会话，超大历史 |

> **亮点**：core 版（仅 BM25 + 知识图谱，**不含任何向量模型**，且数据是**英文**）在 s_cleaned 上已达
> Recall@5=0.96 / MRR=0.91。这说明 wanyimem 并非只靠向量模型 —— 纯关键词 + 图谱通道的跨会话事实召回
> 已经很能打。full 版（中英通吃的 bge-m3 + 精排）预计进一步提升 MRR（把证据会话排到更前）。

## 说明

- 数据来源：HuggingFace `xiaowu0162/longmemeval-cleaned`（自动走 hf-mirror 下载）。
- 指标口径：session 粒度（每条 turn 一条记忆，content 内嵌 `[[sid]]` 标记还原会话）。
- 该方法依赖 question 与证据 turn 的语义/关键词关联，不接入 LLM 生成答案，纯测量记忆召回。
