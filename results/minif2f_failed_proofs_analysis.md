# MiniF2F 未通过证明的相似性分析

涵盖：**minif2f round_2 / round_3**（官方数据集）、**minif2f_v2s**、**minif2f_v2c**（v2 额外数据）。  
数据来源：各目录下 `code_compilation_repl.json`。

---

## 1. 整体情况

| 数据集 | 总记录 | 通过 | 未通过 | 至少 1 通过的题数 | 主导错误题数(≥50%) |
|--------|--------|------|--------|--------------------|---------------------|
| minif2f round_2 | 7,808 | 5,066 | 2,742 | — | 153 |
| minif2f round_3 | 7,808 | 5,022 | 2,786 | — | 157 |
| minif2f_v2s | 15,616 | 9,364 | 6,252 | — | 324 |
| minif2f_v2c | 15,616 | 9,155 | 6,461 | — | 334 |

（round_2/round_3 为 244 题×32；v2s/v2c 为 488 题×32。）

---

## 2. 失败类型分布（按第一条错误归类）

### minif2f round_2

| 类别 | 数量 | 占比(约) |
|------|------|----------|
| **other** | 1,752 | 64% |
| tactic failed | 293 | 11% |
| omega failed | 286 | 10% |
| TIMEOUT | 187 | 7% |
| parse/syntax | 120 | 4% |
| simp | 52 | 2% |
| unknown identifier | 29 | 1% |
| type/function | 20 | <1% |

### minif2f round_3

与 round_2 类似：**other** 约 66%，其次 tactic failed、omega failed、TIMEOUT、parse/syntax。

### minif2f_v2s

| 类别 | 数量 |
|------|------|
| other | 3,755 |
| tactic failed | 728 |
| omega failed | 635 |
| TIMEOUT | 440 |
| parse/syntax | 296 |
| simp | 126 |
| unknown identifier | 88 |
| type/function | 79 |
| ambiguous | 65 |

### minif2f_v2c

| 类别 | 数量 |
|------|------|
| other | 3,772 |
| **parse/syntax** | **785** |
| tactic failed | 723 |
| omega failed | 571 |
| TIMEOUT | 320 |
| simp | 110 |
| unknown identifier | 77 |
| type/function | 45 |
| ambiguous | 31 |

v2c 中 **parse/syntax** 明显多于 v2s，与 v2c 题目/表述差异一致。

---

## 3. 相似性结论

### 3.1 错误类型集中

- **other** 在 round_2/round_3 中占失败样本约 **64–66%**，在 v2s/v2c 中约 **60%**，说明大量失败是“未归入常见标签”的各类错误，但多属策略/类型/目标未闭合等。
- **策略相关**（tactic failed + omega failed + simp）合计约 **20–25%**（round）与 **24–25%**（v2），与 Putnam 类似，策略层失败占相当比例。
- **parse/syntax** 在 round_2/3 约 4%，在 v2c 约 12%，在 v2s 约 5%；v2c 语法/解析问题更突出。
- **TIMEOUT** 约占 5–7%（round）与 5–7%（v2），存在一定比例超时。

### 3.2 题目内失败模式一致（同题同错）

- **153–334 题**（依数据集）中，未通过样本里 **≥50% 属于同一错误类型**。
- 多题 **32/32 全为同一类**，例如：
  - **other**：amc12a_2021_p14, amc12a_2020_p4, imo_1992_p1（round_2/round_3）；amc12a_2009_p7, mathd_algebra_478（v2s）；mathd_numbertheory_552, aime_1994_p3, amc12b_2020_p21（v2c）
  - **syntax**：mathd_numbertheory_198（v2s）；imo_1960_p2, imo_1992_p1, imo_1997_p5, imo_1981_p6（v2c）
  - **ambiguous**：imo_1962_p4, imo_1966_p4（v2s）

与 Putnam 一致：**同一题目下，未通过证明在错误类型上高度相似**。

### 3.3 常见具体错误（与 Putnam 可比）

- **omega could not prove the goal**（counterexample / No usable constraints）— 出现最多。
- **tactic 'rewrite' failed, did not find instance of the pattern**
- **simp made no progress** / **simp failed, maximum recursion depth**
- **unknown identifier**（如 k'）
- **type mismatch**（如 ℚ vs ℤ）
- **failed to synthesize**（类型类实例）
- **The rfl tactic failed**
- **unexpected token 'theorem'; expected term**（v2c 较多，多声明/格式问题）
- **ambiguous**（如 π 的多种解释）

### 3.4 代码长度

- **未通过**：中位数约 2,500–3,900 字符，最大约 19 万–28 万。
- **通过**：中位数约 750–840 字符，最大约 1.4 万–3.2 万。
- 与 Putnam 一致：**通过的证明更短**，过长证明更容易失败或超时。

---

## 4. 与 Putnam 的对比

| 维度 | Putnam | MiniF2F |
|------|--------|---------|
| 失败主因 | parse/syntax + type 占比极高 | other + tactic/omega 为主，syntax 在 v2c 较高 |
| 同题同错 | 520 题有主导错误类型 | 153–334 题有主导错误类型 |
| 通过样本长度 | 中位 518 | 中位 750–840 |
| 未通过样本长度 | 中位 2,426 | 中位 2,500–3,900 |

MiniF2F 整体通过率更高，失败更多集中在 **策略/类型/other**，语法问题比例低于 Putnam（v2c 除外）；但**“同题内失败模式相似”**在两边都成立。

---

## 5. 总结

- **有相似性**：minif2f 各数据集中，未通过证明在 **错误类型** 上以 other + tactic/omega/simp 为主，且 **同一题目下失败类型往往一致**（同题同错）。
- **数据集差异**：v2c 的 parse/syntax 明显多于 v2s 与 round_2/3，改进 v2c 时可重点排查生成格式与多声明结构。
- **可改进方向**：针对 **omega/rewrite/simp** 主导的题改进策略与约束；针对 **syntax** 主导的题（尤其 v2c）检查 prompt/输出格式；对 **other** 做细分统计便于进一步归类。
