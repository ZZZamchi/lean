# Goedel-Prover-V2 评测：为何本地 32B 远低于论文 ~90%？

论文中 **32B** 常见报道为 **miniF2F valid 约 88%（pass@32）/ 约 90%（+ self-correction）**，协议以 Goedel-Prover-V2 论文为准：<https://arxiv.org/abs/2508.03613>。本仓库内 **`results/prover/*32b*` 的 `proof_results.json` 通过率往往只有几十个百分点**，多数情况下**不是模型坏了**，而是下面几类 **协议/实现不一致**。

## 1. 推理协议未对齐（最常见）

| 项目 | 论文 / 官方推理习惯 | 本仓库常见偏差 |
|------|---------------------|----------------|
| **Chat template** | Qwen3 chat，`apply_chat_template` | 若使用 `prover.run --no-chat`，对 Goedel-V2 通常 **错误**（模型按 chat 训练） |
| **max_tokens** | 常 **16K–32K** 量级 | `prover.run` 默认 **`--max-tokens 4096`**，长证明易截断 |
| **max_model_len** | 需 **≥ 提示 + 生成长度** | 默认 **8192** 可能提前截断上下文 |
| **Prompt 文本** | 官方 *proof plan* 句式（见 `src/inference.py` + `experiments/phase1_official_config.py`） | `prover/prompts.py` 的 `WHOLE_PROOF_COT` **句式不同**，分布会偏移 |
| **Self-correction** | 多轮纠错可 +2～3pp（32B） | `prover.run` 默认 **仅 whole_proof 单阶段**，无 `correction_round` 循环 |

**建议（prover 跑 Goedel-8B/32B 对齐实验时）**：

```bash
python -m prover.run --dataset minif2f --split valid \
  --model Goedel-LM/Goedel-Prover-V2-32B --tp 2 --gpus 0,1 \
  --strategies whole_proof --samples 32 \
  --max-tokens 32768 --max-model-len 40960 \
  # 不要加 --no-chat（Goedel-V2 应开启 chat）
```

若要对齐 **官方 self-correction**，请使用 **`src/inference.py`** 的 `--correction_round 1/2` 流水线，或 `experiments/phase1_official_config.py` 一类脚本，而不是仅 `whole_proof`。

## 2. 子集与分母错误（第二常见）

- `minif2f_goedel32b/` 等目录往往只有 **部分题目**（分片、调试 `limit`、中途停止）。  
- **34/158** 是 **34 题在 158 题子集上通过**，**不能**与 **220/244** 类 headline 直接比。  
- 正确做法：对 **同一 split 全部 244 题** 跑满，再用 `prover/evaluate.py` 或 `scripts/report_pass_at_32.py` 算 pass@32。

## 3. 验证口径

- 成功需 **kernel-complete、无 `sorry`**（与论文一致）。  
- Mathlib **commit** 与 miniF2F **形式化版本** 与论文实验可能不同，会有小幅波动。

## 4. 结论

在改 **chat / token / prompt / SC / 全 split** 之前，**不应**用当前 `*32b*` 子目录的粗通过率去质疑「官方 90%」。完成对齐后，若仍显著偏低，再查 vLLM 版本、dtype、`tensor_parallel_size` 与显存是否触发静默截断。
