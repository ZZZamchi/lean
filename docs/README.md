# 仓库文档索引（`lean/` 根目录）

面向本仓库的**导航页**；**不包含** `mathlib4/` 上游内容（见下表）。

## 快速链接

| 文档 | 内容 |
|------|------|
| [REPOSITORY_MAP.md](REPOSITORY_MAP.md) | 顶层目录说明、数据与结果放哪 |
| [GOEDEL_V2_EVALUATION.md](GOEDEL_V2_EVALUATION.md) | Goedel-V2 **8B/32B** 与论文 ~90%（32B+SC）对齐检查清单 |
| [../prover/docs/technical_report.md](../prover/docs/technical_report.md) | 技术报告（实验数字、Phase1、32B JSON 快照） |
| [../prover/docs/paper.md](../prover/docs/paper.md) | 论文 Markdown 长稿 |
| [../prover/docs/academic_report.md](../prover/docs/academic_report.md) | 学术报告稿（方法/实验叙述） |
| [../prover/docs/latex/paper_full.tex](../prover/docs/latex/paper_full.tex) | LaTeX 主稿（投稿版） |
| [../scripts/README.md](../scripts/README.md) | Shell/Python 脚本入口（minif2f MVP、编译分块、Pass@32 汇总） |

## 编译与运行（简版）

1. **Lean / Mathlib**：`cd mathlib4 && lake build`（首次耗时较长）。  
2. **Python**：见仓库根目录 `goedelv2.yml` 或各脚本头部注释。  
3. **推理主入口**：`src/inference.py`（多轮 `correction_round`）；**prover 框架**：`python -m prover.run ...`。  
4. **结果**：`results/` 下按 benchmark 分子目录；说明见 [../results/README.md](../results/README.md)。

更细的脚本参数以 `scripts/README.md` 与各 `.sh` 内注释为准。
