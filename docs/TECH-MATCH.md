# JobPulse · 岗位匹配度模块 · 技术架构文档

| 项 | 值 |
|---|---|
| 版本 | v0.2 |
| 日期 | 2026-08-27 |
| 状态 | 已评审（契约已定，见 match-schema.md） |
| 关联 | [PRD-MATCH.md](./PRD-MATCH.md) · [match-schema.md](./match-schema.md) |

---

## 1. 架构总览

匹配度模块的核心是一个**与任何入口解耦的「匹配度引擎」**：输入 `JD 文本 + 简历文本`，输出 `结构化评分报告`。引擎不依赖飞书、不依赖插件，可被多个入口复用。

```
                     ┌──────────────────────────┐
  JD文本 + 简历文本    │      匹配度引擎          │   评分报告 JSON
  ──────────────────► │  分维度加权 + JD命中核对   │ ──────────────►
                     │  + 评分锚点 + 逐段诊断     │   (分数/依据/诊断/优化稿)
                     └──────────────────────────┘

  入口 A：JobPulse 插件（投递闭环，从飞书简历库选版本）→ 走后端引擎
  入口 B：联动优化网页（与插件联动 / 独立粘贴）       → 后端引擎（V2）
  入口 C：独立 BYOK 静态页（V3，分享/脱离使用）      → 前端 JS 引擎
```

### 1.1 调用链

```
插件(抓JD) → POST /api/match {jd, resume_version_id}  → 后端(Flask)
    → 飞书简历库取简历正文 → 匹配度引擎(Python) → DeepSeek
    → 返回评分报告 → 插件展示 / 跳转网页

独立网页(V3) → 前端 JS 引擎 → DeepSeek(用户自带Key, localStorage) → 本地渲染
```

### 1.2 技术栈约束
- 后端沿用现有 **Python + Flask + requests**（纯 requests，不引新依赖）
- 插件沿用 **Vanilla JS + Chrome MV3**
- 网页 **静态 HTML + JS**（V3 BYOK）
- LLM：DeepSeek（OpenAI 兼容），结构化输出用 `response_format: json_object`

---

## 2. 参考项目技术架构（调研）

| 项目 | 架构要点 | 本模块借鉴 |
|---|---|---|
| [Resume-Matcher](https://github.com/srbhr/Resume-Matcher) | Next.js + FastAPI；前后端分离；多模型可切换 | 前后端分离骨架；多模型抽象 |
| [Career-Ops](https://github.com/) | Agentic 架构；A-F 评分 = 10 加权维度 | **加权维度评分**方案 |
| [ResumeIQ](https://github.com/ayush-s-tomar/ResumeIQ) | Flask + Groq；0-100 分；15 组人工标注 MAE 5.0 | **评测基准校准法** |
| [@resurank/scoring](https://www.npmjs.com/package/@resurank/scoring) | 60% 语义嵌入 + 40% TF-IDF，纯本地算法 | **算法辅助核对层** |
| [ApplyRight-AI](https://github.com/Rowe83/ApplyRight-AI) | 自托管 + 自带 Key；章节 Diff 左右对照 | **优化稿 Diff 呈现** |
| [ai-job-search-cn](https://github.com/sunyet-01/ai-job-search-cn) | 零依赖；工具与知识分离；7 维框架 | **prompt/框架与代码解耦** |
| [ai-job-search](https://github.com/MadsLorentzen/ai-job-search)（1.9万星） | 双 Agent 起草+复审；编译校验 | **双 Agent 增强**（V2+） |

### 2.1 实测调研结论（2026-08-27，逐一读源码）

> 本节为对三个核心参考项目的**代码级实测**（子代理逐一读了关键源码，非 README 摘要），是本模块设计的事实依据。调研笔记如需追溯，已沉淀在各文件的 commit 记录。

| 项目 | 实测实现（读了什么） | 结论 / 我们的决策 |
|---|---|---|
| **Resume-Matcher** | LLM 只提取 JD 关键词（`EXTRACT_KEYWORDS_PROMPT`），命中判定用**整词边界正则** `(?<!\w)...(?!\w)`；分数 = 纯加权 `kw×0.55 + skills×0.25 + section×0.20`；**无嵌入、无 LLM 打分**（README 的 embedding 标签是旧版遗留） | ✅ 借鉴「LLM 提取 + 算法判定」分层、整词正则细节、source 三分类（可注入 vs 真缺失）。⚠️ 它提取了年限/学历要求却**不进评分**，纯关键词可被堆砌欺骗、无语义 → 我们补硬性门槛布尔判定 |
| **ResumeIQ** | 单次 LLM 调用直接输出 0-100（`temperature=0`、无分维度）；评测骨架 `eval/run_eval.py` = 逐条 diff + MAE | ⚠️ **README 宣称「15 组标注、MAE 5.0」，仓库 `eval_set.json` 实际只有 3 组，不可复现** —— 这是营销话术。→ 我们评测必须数据与数字同入库、一条命令可重算。✅ 借鉴 JSON 健壮性三板斧（剥围栏/失败重试+纠正指令）、sha256 缓存键、run_eval 骨架 |
| **@resurank/scoring** | 60% 语义嵌入（jina-v2-small-en 本地 ONNX）+ 40% TF-IDF（双文档余弦 + top-150 重叠加成 + **发散调整**），输出 0-1；embedder 可插拔 | ⚠️ **AGPL-3.0 传染性许可 + 英文 tokenizer 对中文直接报废**，不搬源码。✅ 借鉴算法核对思路：jieba 分词 + 中文招聘停用词 + 命中率 + 发散调整（算法分≈0 时压低语义权重防幻觉） |

---

## 3. 匹配度引擎设计（核心）

> ⚠️ 自 v0.2 起，引擎已落地**融合三项目调研的分层架构**，详细契约（Schema / prompt 全文 / 权重锚点 / 算法公式 / 评测规范）见 [match-schema.md](./match-schema.md)。本文档只保留概要，**两处冲突以 match-schema.md 为准**。

**融合后引擎流程（一次 LLM 调用）**：

```
JD 文本 + 简历文本
  │
  ▼
① 算法预核对层（借鉴 @resurank 思路 + Resume-Matcher 正则）
   jieba 分词 + 中文招聘停用词 + 整词边界正则 → 关键词命中信号
  │
  ▼
② LLM 主评分（一次调用，借鉴 ResumeIQ 健壮性 + 分维度加权）
   prompt 喂入 ① 的信号 → 分维度分 + JD 命中表 + 硬性门槛布尔判定
  │
  ▼
③ 后处理（verdict 强一致 + 分数钳制 + 字段清洗）
```

**三个已定决策（详见 §3.5 决策记录）**：
- 硬性门槛**布尔判定 + 降权提示**：不满足 → `hard_gate.met=false` + verdict「不建议投」，但总分保留实际加权分
- **算法命中信号喂给 LLM** 作客观锚点（防分数虚高，借鉴 @resurank 发散调整）
- verdict 由**后处理层强制对齐规则**（补 ResumeIQ 分数与结论打架的坑）

### 3.1 评分算法：分维度加权 + 命中核对 + 锚点

**一句话**：不是让 LLM 拍一个数，而是拆成可解释的维度逐项评分，用 JD 要求命中核对作为客观依据，用锚点控制稳定性。

**维度与权重**（可配置，默认值）：

| 维度 | 权重 | 评什么 | 评分锚点 |
|---|---|---|---|
| 硬性门槛 | 20% | 学历/专业/年限/证书是否满足 | 不满足 → `hard_gate.met=false` + verdict「不建议投」（**降权提示**：维度分与总分不压低，如实反映技能/经历匹配度） |
| 技能匹配 | 40% | JD 技能清单逐条命中 | 命中 ≥80% → 85+；50-80% → 60-80；<50% → ≤55 |
| 经历相关性 | 40% | 实习/项目经历与 JD 职责契合度 | 高度相关且有量化成果 → 85+；部分相关 → 60-80 |

总分 = Σ(维度分 × 权重)，钳制 0-100。

**JD 要求命中核对（可解释性的核心）**：
1. LLM 先把 JD 拆成结构化要求清单：`[{category: 技能/职责/软性/加分项, requirement, ...}]`
2. 逐条判断简历是否命中，给出 `matched: true/false` + `evidence`（简历里的对应原文）
3. 命中率直接决定"技能匹配"维度的分，且**命中表就是网页上摊开的依据**

**评分锚点**：固定上述标准写进 prompt，要求 LLM 严格对照锚点打分，避免两次评估波动。

### 3.2 一次 LLM 调用，输出完整报告

引擎一次调用 DeepSeek（`temperature=0.1`、`max_tokens=4000`、`response_format: json_object`，失败自动降级 + 剥围栏重试），返回完整评分报告。**完整 Schema 见 [match-schema.md §2](./match-schema.md)**，v0.2 相对初稿的关键变化：

- 新增 `hard_gate`：硬性门槛布尔判定，独立于加权分（§3.1 决策）
- 新增 `algorithm_check`：算法核对信号（`keyword_hit_rate` / `discrepancy`）
- `jd_requirements[*].source`：三分类 `resume`（简历已有）/ `addable`（可补，有经历未写）/ `missing`（真缺失）—— 借鉴 Resume-Matcher 的可注入分类，守诚实性
- `verdict` 改用中文值（可投 / 建议优化 / 不建议投），由后处理层强制对齐 §3.3 规则
- `optimized` 优化稿移入 V2（V1 prompt 不要求输出，控制响应体积）

### 3.3 引擎接口（纯函数）

```python
# agent/match_engine.py（命名待定，可能并入现有 match.py）
def evaluate(jd_text: str, resume_text: str, config: dict = None) -> dict:
    """JD + 简历 → 评分报告 dict（上述 JSON）"""
```

- **无状态**：不依赖飞书/插件，任何入口可调
- 内部：构造 prompt → **直调 `chat/completions`**（`classify()` 的 `max_tokens=2000` 不够评分报告，见 match-schema §7.1）→ 复用 `_extract_json` 健壮性 → 后处理（verdict 强一致 + 钳制）→ 返回
- 简历/ JD 超长时截断（简历 ≤4000、JD ≤2000，见 match-schema §1）
- **评测校准**：见 match-schema §6 —— 结构化标注集 + 分层指标（总分 MAE / verdict 一致率 / 硬门槛一致率 / 命中表 P-R），数据与数字同入库、一键可重算（吸取 ResumeIQ"15 组标注不可复现"教训）

### 3.4 分层与可选增强

| 组件 | 状态 | 说明 |
|---|---|---|
| 算法预核对层（关键词命中信号） | **V1 核心**（原"可选增强"升格） | jieba + 中文停用词 + 整词正则 + 发散调整，见 match-schema §5 |
| 语义嵌入核对层（bge-m3 等） | 后置（V1.1+） | 算法层只能证伪"分虚高"；词面不重叠但语义很配是盲区，需嵌入语义分弥补；embedder 做成可插拔（借鉴 @resurank） |
| 双 Agent 起草+复审 | V2+ | 改写稿由第二个 Agent 复审"是否虚构经历/是否紧扣 JD"（参考 ai-job-search） |

### 3.5 设计决策记录（v0.2，防中断追溯）

| # | 决策 | 选项对比 | 结论与理由 |
|---|---|---|---|
| D1 | **LLM 调用次数** | A. 一次调用（≤15s，输出量大偶漏）；B. 两次调用（拆解+评分分离，更稳但 20-30s） | 选 A。先跑通，命中表不稳靠评测集迭代；需要时再升级两次调用 |
| D2 | **硬性门槛不满足的处理** | A. 一票否决（压分≤40）；B. 纯加权不管；C. 降权提示 | 选 C。verdict 强制「不建议投」+ 总分不压，既诚实又不误导（用户拍板） |
| D3 | **算法核对层定位** | 直接搬 @resurank（AGPL + 英文 tokenizer 不匹配）；借鉴思路自实现 | 自实现。jieba + 中文停用词 + 整词正则 + 发散调整，≤100 行；只证伪"分虚高" |
| D4 | **评分判定分层** | 全 LLM 逐条核对；LLM 提取 + 算法判定 | 分层。LLM 拆 JD + 语义兜底，正则/集合先判命中（借鉴 Resume-Matcher），可调试、防堆砌欺骗 |
| D5 | **评测可复现性** | 学 ResumeIQ（README 15 组 / 仓库 3 组）；数据与数字同入库 | 同入库。标注集 + 脚本同目录、`python run_eval.py` 一键重算，禁止数字漂移 |

---

## 4. 接口设计（后端）

### 4.1 POST /api/match（新增，供插件 / 联动网页调用）

```jsonc
// 请求
{
  "jd_text": "岗位JD全文",
  "resume_version_id": "recXXX",          // 从简历库选中的版本（二选一）
  "resume_text": "也可直接传简历文本",     // 独立使用时
  "sender_id": "ou_xxx"                   // 用户标识（可选）
}

// 响应（200）
{
  "code": 0,
  "data": { /* 评分报告 JSON，见 §3.2 */ }
}

// 错误（4xx/5xx）
{ "code": 400, "msg": "未找到简历版本" }
{ "code": 500, "msg": "LLM 调用失败" }
```

### 4.2 简历库接口（复用现有 FeishuClient，新增方法）

| 操作 | 飞书 API | 说明 |
|---|---|---|
| 拉简历版本列表 | `GET /bitable/.../records` | 返回 `[{record_id, 简历名称, 适用方向, ...}]` |
| 取简历正文 | `GET /bitable/.../records/{id}` | 按 record_id 取「简历正文」字段 |
| 新增版本 | `POST /bitable/.../records` | 「另存为新版本」写入新行 |

---

## 5. 数据模型

### 5.1 简历库（飞书新建表「简历库」）

| 字段 | 类型 | 说明 |
|---|---|---|
| 简历名称 | 文本 | 如「原始版」「前端通用版」「字节电商-优化版」 |
| 适用方向 | 单选 | 通用 / 前端 / 后端 / 产品 / ...（可扩展） |
| 简历正文 | 文本 | 简历全文（注意飞书文本字段长度上限，超长拆分） |
| 来源版本 | 文本 | 由哪个版本优化而来（形成版本链，可空） |
| 创建时间 | 日期 | 自动 |
| 更新时间 | 日期 | 自动 |

> ⚠️ 遵循项目规范：**只新建表/字段，不修改已有字段**（参照飞书 API 约束经验）。

### 5.2 评分报告 JSON Schema（见 §3.2，作为引擎与各入口的契约）

引擎（Python）与 BYOK 网页（JS）两端实现时，**共用同一份 schema + prompt 模板**，避免逻辑漂移（见 §6.2）。

---

## 6. 三个入口的实现

### 6.1 入口 A：插件（V1）

- `popup.html/js`：新增「匹配度计算」按钮 + 简历版本下拉 + 分数展示区
- 流程：抓 JD（现有）→ 用户选简历版本 → `fetch` 后端 `/api/match` → 渲染分数 + 维度摘要
- 高分（≥70）→ 显示"直接投递"按钮，走现有投递流程
- 低分 → 显示"去优化简历"跳转联动网页（带参：jd + resume_version_id）

### 6.2 入口 B：联动优化网页（V2）

- 项目内静态页 `match.html`（与 dashboard.html 同层，插件快捷入口并列）
- **联动模式**：URL 带 `?jd=...&resume=...`，自动带入插件抓到的 JD 与选中简历
- **独立模式**：页内可粘贴 JD、粘贴/上传简历
- 页面展示（参考 ApplyRight-AI 的 Diff 对照）：
  1. 顶部：总分 + 结论（可投/建议优化/不建议）
  2. 得分依据：JD 要求命中表（✅/❌ + 证据）、各维度得分理由
  3. 逐段诊断：每段简历的问题 + 建议
  4. 优化稿：**原文 vs 优化稿左右对照**，实习/项目经历可编辑
  5. 「另存为新版本」按钮 → POST 简历库新增行
- V2 网页计算走后端 `/api/match`（复用引擎）

### 6.3 入口 C：独立 BYOK 静态页（V3）

- 纯静态 HTML + JS，用户填写 DeepSeek Key（存 localStorage）
- **前端直调 DeepSeek**，需要一份 **JS 版引擎**（同 schema + prompt 模板）
- 部署到任意静态托管（GitHub Pages / Render Static），发链接即分享
- ⚠️ 前置验证：**DeepSeek 是否允许浏览器 CORS 直调**。若不允许，V3 需加一个薄后端代理（用用户传来的 key 调 DeepSeek），或改为走现有 agent 后端

### 6.4 引擎双端实现策略

| 方案 | 说明 | 取舍 |
|---|---|---|
| A. 双端各实现一份（Py + JS） | 后端引擎 Python，BYOK 页 JS | 需共用 schema/prompt 模板文件防漂移 |
| B. 统一走薄后端 | BYOK 页也调后端，key 由用户传给后端 | 静态页不再纯静态；可规避 CORS |

**建议**：V1/V2 先只做 Python 引擎（后端），V3 再做 JS 版时，把 **prompt 模板 + JSON Schema 抽成项目内共享规范文件**（如 `docs/match-schema.md` 或 JSON 文件），两端各自实现但绑定同一规范。

---

## 7. 安全与隐私

- **密钥**：插件用 chrome.storage.local；网页 BYOK 用 localStorage；后端沿用环境变量。均不硬编码、不写日志
- **CORS**：后端接口仅允许插件/网页域名访问（配置白名单）
- **简历数据**：简历文本只在"入口 → LLM 调用"链路流转，不落盘到插件侧；飞书简历库受飞书权限保护
- **防滥用**（若 V3 走公共后端）：限流 + 单用户配额；BYOK 模式天然隔离

---

## 8. 部署与发布

| 入口 | 载体 | 部署 |
|---|---|---|
| 后端 `/api/match` | 现有 agent Flask 服务（Render） | 随现有服务一起部署 |
| 插件 | Chrome 扩展 | 本地加载（现有方式） |
| 联动网页 `match.html` | 静态页 | 随仓库发布，插件/看板同级入口 |
| 独立静态页（V3） | 静态托管 | GitHub Pages / Render Static |

---

## 9. 风险与待验证

| # | 风险 | 应对 |
|---|---|---|
| 1 | **DeepSeek 浏览器 CORS**（V3 前置） | 落地 V3 前先验证；不支持则走薄后端代理 |
| 2 | LLM 评分稳定性 | 锚点 + 固定 prompt；建评测集量化 MAE，据此校准 |
| 3 | 简历超长（飞书文本字段/LLM 上下文） | 截断策略 + 分节评估增强 |
| 4 | 改写稿虚构经历 | prompt 强制"只基于简历实际内容"；V2+ 双 Agent 复审 |
| 5 | 飞书「简历库」表新建权限 | 遵循"只建新表/字段"规范；发布版本后生效 |
| 6 | 引擎 Py/JS 双端逻辑漂移 | 共享 [match-schema.md](./match-schema.md) 单一契约（v0.1 已落）；V3 才引入 JS 版 |
| 7 | **评测数字漂移**（ResumeIQ 教训：README 15 组 / 仓库 3 组） | 标注集与评测脚本同入库；README 里的任何 MAE/一致率必须 `python match_eval/run_eval.py` 一条命令重算出同结果 |
| 8 | **纯关键词可堆砌欺骗** LLM 命中表 | 命中表 source 三分类 + 诚实原则 + 算法信号交叉验证；硬性门槛独立布尔判定、不进加权分 |
| 9 | **中文分词 / 嵌入支持** | jieba + 中文招聘停用词（@resurank 的英文 tokenizer 对中文直接报废）；嵌入层后置选 bge-m3 等中文模型 |

---

## 附录 · 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-08-24 | 初稿：架构总览、调研、引擎初版设计、接口、数据模型、三入口、安全、部署、风险 |
| v0.2 | 2026-08-27 | 评审通过 + 三项目**代码级实测**（§2.1）+ 融合分层架构（§3）+ 决策记录（§3.5）+ 风险补充（§9）；详细契约落 [match-schema.md](./match-schema.md) |

---

## 附录 · 参考链接

- [ApplyRight-AI](https://github.com/Rowe83/ApplyRight-AI)
- [Resume-Matcher](https://github.com/srbhr/Resume-Matcher)
- [ResumeIQ](https://github.com/ayush-s-tomar/ResumeIQ)
- [@resurank/scoring](https://www.npmjs.com/package/@resurank/scoring)
- [Career-Ops](https://github.com/)（41.7K 星）
- [ai-job-search](https://github.com/MadsLorentzen/ai-job-search)（1.9万星）
- [ai-job-search-cn](https://github.com/sunyet-01/ai-job-search-cn)
- [BossHunter](https://github.com/powerycy/BossHunter)
