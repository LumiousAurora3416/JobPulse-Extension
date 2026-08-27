# JobPulse · 岗位匹配度引擎契约（Match Schema）

| 项 | 值 |
|---|---|
| 版本 | v0.1 |
| 日期 | 2026-08-27 |
| 状态 | 已评审（2026-08-27，融合三项目调研） |
| 关联 | [PRD-MATCH.md](./PRD-MATCH.md) · [TECH-MATCH.md](./TECH-MATCH.md) |

> 本文档是匹配度引擎的**单一事实来源**：评分报告 Schema、prompt 模板、权重锚点、算法核对层公式、评测规范全部定死在此。Python 引擎（`agent/match_engine.py`）与 V3 的 JS 网页均按此实现，双端只允许绑定同一份规范，防止逻辑漂移。

---

## 1. 引擎接口

```python
# agent/match_engine.py
def evaluate(jd_text: str, resume_text: str, config: dict = None) -> dict:
    """JD + 简历 → 评分报告 dict（§2 的 Schema）。

    纯函数、无状态：不依赖飞书/插件，任何入口可调。
    内部流程：
      ① 算法预核对层（§5）：jieba 分词 + 停用词 + 整词匹配 → 关键词命中信号
      ② LLM 一次调用（§4）：prompt 里喂入 ① 的信号，输出完整评分报告
      ③ 后处理（§3）：钳制分数、verdict 一致性校验、字段清洗
    """
```

**调用约定**：单次 LLM 调用（v0.1 决策），`temperature=0.1`、`max_tokens=4000`、`response_format=json_object`（不支持时降级为无该参数 + 自动剥围栏/重试，复用现有 JSON 健壮性三板斧）。

**超长截断**：JD ≤2000 字符、简历 ≤4000 字符，超出截断（简历优先保留教育/技能/实习/项目段）。

---

## 2. 评分报告 JSON Schema（引擎与各入口的契约）

```jsonc
{
  "overall_score": 72,            // 0-100 加权分，钳制；硬性门槛不满足也不压低（见 §3）
  "verdict": "suggest_optimize",  // 可投 / 建议优化 / 不建议投（与分数及 hard_gate 强一致）
  "hard_gate": {                  // 硬性门槛布尔判定（独立于加权分，v0.1 决策：降权提示）
    "met": false,                 // 学历/专业/年限/证书是否全部满足
    "reasons": ["JD 要求硕士，简历为本科学历"]
  },
  "dimensions": [                 // 分维度加权，length=3，顺序固定
    {"name": "硬性门槛", "weight": 20, "score": 80, "reason": "专业对口，学历差一档"},
    {"name": "技能匹配", "weight": 40, "score": 65, "reason": "Vue3/TS 命中，缺微服务经验"},
    {"name": "经历相关性", "weight": 40, "score": 70, "reason": "实习与 JD 职责部分重叠"}
  ],
  "jd_requirements": [            // JD 要求命中表（可解释性核心，逐条可核对）
    {
      "category": "技能",         // 技能 / 职责 / 软性 / 加分项
      "requirement": "熟悉 Vue3",
      "matched": true,
      "evidence": "技能栏：Vue3 3年（简历原文摘录，1 句内）",
      "gap": "",                  // matched=false 时填：缺什么、差在哪
      "source": "resume"          // resume=简历已有体现 | addable=简历可补(有经历未写) | missing=真缺失
    },
    {"category": "职责", "requirement": "有电商项目经验", "matched": false,
     "evidence": "", "gap": "项目经历偏企业服务", "source": "missing"}
  ],
  "algorithm_check": {            // 算法核对信号（客观锚点，供 LLM 参考 + 评测交叉验证）
    "keyword_hit_rate": 0.42,     // 0-1，§5 公式
    "matched_keywords": ["Vue3", "TypeScript"],
    "discrepancy": "low"          // low | medium | high，LLM 分与算法命中差异过大时触发复核标记
  },
  "resume_diagnosis": [           // 逐段诊断（重点：实习/项目经历）
    {"section": "实习经历-XX公司", "issue": "只写了职责没写成果，JD 要求结果导向", "suggestion": "补量化指标"}
  ]
  // V2 起追加：optimized = { "internship": "...", "projects": "..." }（紧扣 JD 改写稿）
}
```

**字段约束**：
- `overall_score` 钳制 `[0,100]` 整数；`dimensions[*].score` 钳制 `[0,100]`。
- 数组长度：`dimensions` 固定 3 项；`jd_requirements` 建议 8-20 条（覆盖 JD 全部硬性要求与主要加分项）；`resume_diagnosis` 0-5 条。
- `verdict` 用中文值，与前端展示一致；后处理阶段强制对齐 §3 规则，LLM 输出矛盾则以规则为准覆盖。

---

## 3. verdict 一致性规则（后处理强约束）

> ResumeIQ 的坑：`match_score` 与 `verdict` 各自独立输出、可能自相矛盾（score 80 但 verdict=Weak）。本引擎在**后处理层强制对齐**，LLM 输出违反则以规则为准。

| 条件 | verdict |
|---|---|
| `hard_gate.met = false`（**无条件最高优先**） | `不建议投`（降权提示：总分保留实际加权分，不压低） |
| `overall_score ≥ 70` | `可投` |
| `55 ≤ overall_score < 70` | `建议优化` |
| `overall_score < 55` | `不建议投` |

一致性校验：若 LLM 输出的 verdict 与上表不符，后处理直接改写；同时 `hard_gate.met=false` 时无论分数一律 `不建议投`。

---

## 4. LLM Prompt 模板（一次调用）

### 4.1 System Prompt（原文，直接进代码）

```
你是一名资深技术面试官和 ATS 简历评估专家。任务是评估「岗位 JD」与「求职简历」的匹配度，输出结构化的可解释评分报告。

【评分框架】
总分 = Σ(维度分 × 权重)，钳制 0-100：
- 硬性门槛 20%：学历 / 专业 / 年限 / 证书是否满足 JD 硬性要求
- 技能匹配 40%：JD 技能清单逐条命中的比例与深度
- 经历相关性 40%：实习 / 项目经历与 JD 职责的契合度（重点看量化成果）

【评分锚点】（严格对照，保证两次评估分数稳定）
- 技能命中率 ≥80% → 技能维度 85+；50%-80% → 60-80；<50% → ≤55
- 经历高度相关且有量化成果 → 85+；部分相关 → 60-80；不相关 → ≤55

【硬性门槛判定】
- 逐项判断学历 / 专业 / 年限 / 证书是否满足 JD 硬性要求
- 任一项不满足 → hard_gate.met = false，且 verdict 强制为「不建议投」
- 但硬性门槛的维度分与总分仍按实际加权计算（不人为压低），如实反映技能与经历的真实匹配度

【JD 要求命中表】
- 把 JD 的要求拆成逐条清单，类别为：技能 / 职责 / 软性 / 加分项
- 每条判断简历是否命中；matched=true 必须给出 evidence（简历原文摘录，1 句内）
- matched=false 的条目给出 gap（缺什么、差在哪），并标注 source：
  - resume：简历里已有体现（命中）
  - addable：简历可补——你有相关经历只是没写清楚（可注入）
  - missing：简历与可补范围都没有（真缺失）
- 诚实原则：只基于简历实际内容判断，绝不虚构简历不存在的经历

【verdict 规则】（必须与分数和硬性门槛一致，禁止自相矛盾）
- hard_gate.met = false → 「不建议投」
- 否则：overall_score ≥70 → 「可投」；55-70 → 「建议优化」；<55 → 「不建议投」

【逐段诊断】
- 针对实习 / 项目经历等关键段落，指出「这段为什么不够匹配」+ 一句可执行的改写建议

【输出要求】
- 只输出一个 JSON 对象，不要 markdown 代码块，不要任何多余文字
- 结构严格符合调用方给定的 Schema
```

### 4.2 User Message 模板

```
【算法核对信号】（仅供参考，用于交叉验证；发现误判可用你的语义理解修正）
关键词命中率: 0.42（命中 5 / 12 个 JD 高频词）
命中的关键词: Vue3, TypeScript, 小程序
疑似缺失关键词: 微服务, 电商中台, 性能优化

【岗位 JD】
{jd_text}

【求职简历】
{resume_text}
```

**调用参数**：`temperature=0.1`、`max_tokens=4000`、优先 `response_format={"type":"json_object"}`（失败自动降级 + 剥围栏 + 追加"只输出 JSON"纠正指令重试一次）。

---

## 5. 算法核对层（客观锚点 + 防幻觉）

> 借鉴 @resurank/scoring 的「关键词命中 + 发散调整」思路，但不搬其源码（AGPL + 英文 tokenizer 对中文失效）。借鉴 Resume-Matcher 的「LLM 提取、算法判定」分层与整词边界正则。**定位**：只证伪"分数虚高"，不证伪"分数偏低"（词面不重叠但语义很配是它的盲区，靠 LLM 语义修正）。

### 5.1 流程

```python
def keyword_check(jd_text: str, resume_text: str) -> dict:
    # 1. jieba 分词（JD 与简历），过滤中文招聘停用词 + 停用词表
    # 2. 从 JD 提取高频关键词：词频 Top N（N=15，取词性为名词/专有名词/英数词）
    # 3. 整词匹配到简历：
    #    - 英文词：整词边界正则 (?<!\w)kw(?!\w)，大小写不敏感
    #    - 中文词：jieba 分词的简历 token 集合包含 或 子串包含
    # 4. hit_rate = 命中关键词数 / JD 关键词总数
    # 5. 发散调整：hit_rate < 0.15 → discrepancy = "high"（提醒 LLM 复核）
    return {
        "keyword_hit_rate": hit_rate,
        "matched_keywords": [...],
        "missing_keywords": [...],   # JD 高频但简历未命中的词，喂给 LLM 作疑似缺失
        "discrepancy": "low|medium|high",
    }
```

### 5.2 中文招聘停用词（示例，代码内维护一份）

```
五险一金、弹性工作、成长空间、福利待遇、带薪年假、零食下午茶、
年终奖、氛围好、发展空间、扁平化管理、免费三餐、节日福利 ...
```

### 5.3 在引擎中的角色

- 命中信号喂入 LLM prompt（§4.2），作为客观锚点，防 LLM 分数虚高；
- 输出进 `algorithm_check` 字段，评测时与 LLM 命中表对比（§6），差异过大触发复核标记；
- **算法层独立可测**：单测 + 评测集都直接断言它的 hit_rate，不依赖 LLM。

---

## 6. 评测规范（校准层）

> 借鉴 ResumeIQ 的 run_eval 骨架，**修正它的坑**：① 数据与数字必须同时入库、一条命令可复现；② 结构化 rubric（分维度人工分），不只一个全局数；③ 分层评测（总分 + 命中表 + verdict），不只总分 MAE。

### 6.1 目录与命令

```
agent/match_eval/
├── eval_set.json     # 结构化标注集（§6.2）
└── run_eval.py       # 一键评测：python run_eval.py → 输出 §6.3 全部指标
```

### 6.2 标注集格式

```jsonc
{
  "cases": [
    {
      "id": "case_01",
      "resume_excerpt": "300-400 字简历摘录",
      "jd_text": "200-300 字 JD",
      "human": {
        "overall_score": 72,
        "verdict": "建议优化",
        "hard_gate_met": true,
        "dimensions": [{"name": "硬性门槛", "score": 80}, {"name": "技能匹配", "score": 65}, {"name": "经历相关性", "score": 70}],
        "jd_requirements": [{"requirement": "熟悉Vue3", "matched": true}, {"requirement": "有电商项目经验", "matched": false}],
        "notes": "结构化备注：缺微服务，JD 要求结果导向，实习段需补量化"
      }
    }
  ]
}
```

- 目标 ≥10 组，覆盖：强匹配 / 强不匹配 / 部分匹配 / 硬性门槛不满足，各 ≥2 组；
- 标注人：用户本人（真实求职场景），标注数据入库，与评测脚本同目录；
- `human.dimensions` 与 `human.jd_requirements` 允许留空（该案例不评该指标），但 `overall_score` + `verdict` + `hard_gate_met` 必填。

### 6.3 评测指标（run_eval.py 输出）

| 指标 | 口径 |
|---|---|
| **总分 MAE** | `mean(|AI_overall - human_overall|)`，另输出 max error |
| **verdict 一致率** | AI verdict 与 human verdict 相同占比（经 §3 后处理对齐后） |
| **硬性门槛一致率** | AI hard_gate.met 与 human.hard_gate_met 相同占比 |
| **命中表 Precision / Recall** | 逐条 requirement：AI matched 判定 vs human 标注；P=判命中且标命中/判命中数，R=判命中且标命中/标命中数 |

**可复现要求**：README / CHANGELOG 里出现的任何 MAE / 一致率数字，必须能从 `python match_eval/run_eval.py` 一条命令重算出同一结果。绝不允许出现"宣称 15 组、仓库只有 3 组"的漂移。

### 6.4 校准循环

1. 跑评测 → 看分层指标，定位误差来源（总分偏 → 调权重/锚点；命中表差 → 调 prompt 或补充拆解示例；verdict 乱 → 查后处理规则）
2. 改 prompt / 锚点 / 后处理 → 重跑同标注集 → 对比指标是否收敛
3. 标注集只增不改（新增案例；已标注案例修改需在 notes 说明原因），保证可比性

---

## 7. 实现约束与 Config 新增

### 7.1 代码约束
- 引擎 `agent/match_engine.py` 纯 requests + jieba，不引新重型依赖（jieba 为新增唯一依赖，属分词必需；先在 requirements.txt 确认）；
- LLM 调用复用 `LLMClient` 的 key/base/model 配置，但**不直接复用 `classify()`**（其 max_tokens=2000 不够），在 match_engine 内直调 `chat/completions`，参数见 §4.2，复用 `LLMClient._extract_json` 的解析健壮性；
- 命中表 evidence 字段与 `resume_diagnosis.suggestion` 均为 LLM 自然语言输出，引擎只做字段存在性校验，不截断。

### 7.2 Config 新增（agent/config.py）

| 键 | 默认值 | 说明 |
|---|---|---|
| `MATCH_THRESHOLD` | 70 | 匹配度 ≥ 此值判「可投」（插件 V1 高分直接投递用） |
| `MATCH_WEIGHTS` | `{"硬性门槛": 0.2, "技能匹配": 0.4, "经历相关性": 0.4}` | 维度权重，可配 |
| `FEISHU_RESUME_TABLE_ID` | `""` | 简历库表 ID（V1 后端接口用） |
| `MATCH_MAX_JD_CHARS` | 2000 | JD 截断长度 |
| `MATCH_MAX_RESUME_CHARS` | 4000 | 简历截断长度 |

---

## 附录 · 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-08-27 | 初稿。融合三项目调研（Resume-Matcher 分层 + @resurank 算法核对 + ResumeIQ 评测骨架）；决策：一次调用、硬性门槛降权提示、verdict 后处理强一致 |
