# Changelog

## v1.9.1 (2026-09-14)

### 变更 — 插件体验：「企业性质」默认民企 + 写入前查重

- **企业性质默认选中「民营企业」**（`popup.html`）：民营企业占比最高，省掉一次点击；仍可自由改选。原首项「— 请选择 —」改为「— 不指定 —」——因为它现在是一个**可选的退出项**（不选则不写该列），而不再是提示语
- **插件写入前查重**（`popup.js`）：
  - 新增 `listAllRecords()`（分页拉全表，上限 20 页防死循环）+ `findDuplicateRecord()`，规则与 Bot 的 `create_record` 去重一致（同「公司」+同「岗位」）
  - 命中重复时**先不写入**，提示已有记录及其当前「结果」；**再点一次「写入飞书」才强制写入**（两步确认）
  - 改「岗位」或「公司」会重置确认状态——否则会绕过查重、把新岗位写成重复记录
  - **为什么不用 `window.confirm()`**：扩展弹窗里原生弹窗会抢焦点，有把 popup 直接关掉的风险，用户会以为写入失败。两步确认无弹窗、无焦点问题
- **实测表内现有 4 组重复**（星尘智能 ×3、杭州新中大 ×2、科大讯飞 ×2、光大证券 ×2）——查重上线后不会再新增；历史重复记录需手动清理
- manifest 版本 1.8.0 → 1.9.1（v1.9.0 只改了 Agent 侧，manifest 漏对齐）

**注意**：插件改动需 **reload 扩展** 才生效。

## v1.9.0 (2026-09-14)

### 重构 — 「结果」状态机：修掉"提醒状态与结果两列互相污染"的根

起因是一个用户报的 bug：「飞书 bot 在修改投递状态时，分不清结果列和提醒状态列」。查下去发现根不在 bot，而在**两列的设计本身**——`提醒状态` 有一半的值是 `结果` 列终态的副本，靠手工标注同步，于是必然分叉。

**分叉的实际后果（方向是反的）**：映射表把 `面试 → 有反馈 → 停止提醒`，但面试是**过程态**，面完正是最该催"面试结果"的时候，提醒反而被关掉；而「测评中」的岗位没有对应按钮，永远停在"待跟进"，于是**每天都被催**。你真正想催的被静音，不想催的天天响。

#### 核心变更

- **`agent/status_rules.py`（新增）——「结果」状态机唯一真相源**：结果选项集、过程态/终态划分、`should_remind()` / `is_terminal()`、卡片按钮映射、与飞书列的一致性校验。此前这些散落在 `agent.py` / `cards.py` / `callback_server.py` / `message_agent.py` 四处，任何一处漏改就是静默故障
- **`结果` 列当状态机**（11 值）：
  - 过程态：`待投递` / `简历` / `测评` / `面试`（**面试不分一二三面**——"在面"时还看不出挂在哪轮）
  - 终态：`简历挂` / `一面挂` / `二面挂` / `三面挂` / `offer` / `无反馈` / `放弃`（**挂要分到轮次**——"挂在哪一轮"是复盘/求职漏斗的关键数据）；`offer！` 更名 `offer`，新增 `放弃`（主动放弃，区别于被拒）
- **`提醒状态` 列改为公式字段**（纯展示）：`IF(OR({结果}="简历",{结果}="测评",{结果}="面试"),"待跟进","已静音")`。它是**聚类标签**——「待跟进」=还会被催的池子。公式列只读，**代码不读也不写**（读它会让推送行为依赖一个展示字段，正是要消灭的耦合）
- **提醒节奏改为排序 + 上限**（配置项 `FOLLOW_UP_FIRST_DAYS=5` / `FOLLOW_UP_INTERVAL_DAYS=7` / `FOLLOW_UP_MAX_CARDS=10`，替代 `FOLLOW_UP_HOURS`）：
  - 候选 = `结果 ∈ {简历,测评,面试}` 且 投递天数 ≥ 5 且（从未提醒 OR 距上次提醒 ≥ 7 天）
  - 按「距上次提醒天数」降序 → 取前 10 张；并列时按投递天数降序（否则一大批"从没催过"会并列，名次实际由记录顺序决定）
  - 推完写新增的**「上次提醒日期」**列；结果进终态时也写
- **卡片按钮按当前结果动态生成**：简历→进面试/测评/简历挂；面试→一面挂/二面挂/三面挂/offer。按钮写入的值必然取自 `RESULT_OPTIONS`，**结构上不可能再写错**
- **bot `update_status` 重写**：参数 `new_status` → `new_result`（enum 引用 `RESULT_OPTIONS`），只写 `结果` 列；新增提示词规则「挂要区分到轮次，没说清就先问，不要瞎猜」

#### 顺带修掉的 3 个既存 bug

1. **卡片「面试」按钮与「记面试时间」功能静默失效**：二者都写 `结果="面试"`，但该选项在结果列被细化（测评/一面挂/二面挂/offer）时已不存在 → 写入 FieldConvFail。数据佐证：结果列 0 条 `面试`、`面试时间` 列 0 条记录
2. **面试统计恒为 0**：`agent.py` 归因拿**结果**列的值去比 `"有反馈"` 这个**提醒状态**的值；`message_agent.py` 统计 `结果 == "面试"`（选项不存在）
3. **看板统计串列**：`dashboard.js` 的 `interview` 用 `结果 === "面试"`（恒 0）、`followed`/`lost` 读提醒状态。现全部改为按结果状态机分桶，漏斗改为「总投递 → 已投递 → 进入面试 → offer」

#### 一致性防线（防止同类 bug 重演）

- `init_match_tables.py` 新增前置校验：比对飞书「结果」列选项与 `status_rules.RESULT_OPTIONS`、校验「提醒状态」是公式列（type=20）、校验终态分组恰好划分 `RESULT_TERMINAL`
- 改列结构的顺序固化为：**先飞书网页端改列 → 再改代码 → 跑 `init_match_tables.py` 校验**

**验证**：`py_compile` + `node --check` 全通过；脚本实跑——建「上次提醒日期」列成功、其余字段全部「已存在，跳过」（幂等确认）；校验正确报出「结果」列缺 `放弃`（补上后转为全部一致）；**真实数据只读冒烟测试**——状态机无冲突、11 个结果值都能生成合法按钮（终态/待投递无按钮）、本轮候选 23 条 → 推送前 10 条且按"最久未催优先"正确排序

**注意**：`提醒状态` 与 `结果` 的列结构变更已在飞书网页端完成；插件侧无改动，但 `dashboard.js` 与 Agent 侧需重新部署（Render）才生效。

## v1.8.0 (2026-09-14)

### 新增 — 「企业性质」字段（全链路：飞书列 + 插件 + Bot 对话）

投递表新增「企业性质」单选列（央国企 / 民营企业 / 外企 / 其他），用于按企业性质切分投递数据（后续可做「央国企 vs 民企的回复率对比」这类归因）。

**背景**：原有字段无法区分企业性质，而秋招里「央国企 / 民企 / 外企」的投递策略和回复节奏差异很大，属于投递决策的关键维度。**不要求自动识别**——识别公司性质需要外部工商数据，成本高且易错，交给用户自选更可靠。

- **飞书建列**（`agent/init_match_tables.py`）：新增 `ensure_company_type_column()`，镜像已有 `ensure_match_score_column()` 的幂等写法；新增 `COMPANY_TYPE_OPTIONS` 常量；`main()` 中在「匹配分」之后调用；文件头 docstring 补第 4 条职责
- **插件**（`popup.html` / `popup.js`）：「薪资」与「结果」之间新增「企业性质」下拉框（首个选项为空「— 请选择 —」）；提交时读取，**选了才写**该列
- **Bot 对话**（`agent/message_agent.py`）：系统提示词字段清单 + 第 8 条规则（用户提到「国企/央企/外企/民企/合资」才传 `company_type`，**没说不许猜**）；`create_record` 工具 schema 加 `company_type`（`enum` 直接引用常量，杜绝非法值）；`_execute_create` 读参数并过滤非法值，非空才写字段

**关键技术点 — 单选字段不能写入不存在的选项**：飞书多维表格的单选字段，写入一个列里没有的选项名会**直接报错 `FieldConvFail`**，而不是自动新增选项。所以「建列时必须把 4 个选项一起写进 `property.options`」是硬前提，且三处选项值必须一致：

| 位置 | 载体 |
|---|---|
| 飞书列本身 | `init_match_tables.py` 的 `COMPANY_TYPE_OPTIONS`（建列时写入 `property.options`） |
| 插件下拉框 | `popup.html` 的 `<option>` 列表 |
| Bot 工具契约 | `message_agent.py` 的 `COMPANY_TYPES`（同时作为 schema 的 `enum`） |

**防御设计**：Bot 侧做了双重保险——`enum` 约束 LLM 只能从 4 个值里选或干脆不传，代码里 `if company_type not in COMPANY_TYPES: company_type = ""` 再兜一层。因为**一个非法值会让整条记录写入失败**（不只是这一列丢值），必须挡住。插件侧同理：未选择时不写该字段，避免把空值/脏值写进单选列。

**验证**：`node --check popup.js` 通过；`py_compile` 两个 py 文件通过；`python init_match_tables.py` 实跑——「企业性质」列新建成功，其余字段全部「已存在，跳过」（幂等性确认）；API 回读该列：`type=3`（单选），`options=['央国企','民营企业','外企','其他']`

**注意**：插件侧改动需 **reload 扩展** 才生效（MV3 无热更新）。

## v1.7.1 (2026-09-11)

### 修复 — 岗位名被误识别为公司名（moka 站点标题误判）

moka 岗位页（`app.mokahr.com/campus-recruitment/...`）点插件时，「岗位」被填成公司名「搜狐畅游」。

**根因**：moka 是 hash 路由 SPA（岗位 id 在 `#/job/<uuid>`），`document.title` 是「搜狐畅游 - 校园招聘」这种**站点标题，本身不含岗位名**。第 3 层 pageTitle 评分制把「搜狐畅游」当作唯一候选选中（「校园招聘」被 `isBadTitle` 过滤掉），第 4 层又会兜底把同一个值塞回来。本该拦截的末道防线要求 `company` 非空才生效，而 moka 的 URL 正则只认老的 `campus_apply/` 格式、`campus-recruitment/` 不匹配 → `company` 为空 → **防线失效**。

- **「站点标题」判定（站点无关）**：`popup.js` 第 3/4 层。`pageTitle` 切分后若非黑名单分段仅 1 个、不含岗位关键词、且标题存在黑名单分段 → 判定标题内没有岗位名，放弃取值并跳过第 4 层兜底。从根上堵死「把公司名当岗位名」这一类误判，不限 moka
- **moka 岗位名选择器**：新增 `[class*="sd-foundation-heading"]`。只匹配设计系统稳定前缀，避开每次发版都变的尾部 hash（真实类名 `sd-foundation-heading-40-axnSz`，`axnSz` 会变）
- **重构**：提取岗位关键词正则为 `JOB_KEYWORD` 常量供第 3 层共用（`popup.js` 另两处正则内容不同，未改动，避免改变其行为）

**连带修复（意外收获）**：第 6 层「反推公司名」依赖 `seg !== position`。岗位名填错时，「搜狐畅游」正好等于 position 而被跳过，公司名跟着一起空；岗位名修好后它不再等于 position，被正确认作公司名——**公司名字段随之自动填对，无需手动输入**。这也说明岗位/公司这两个字段是互相推导的，一个错会带错另一个。

**验证**：`node --check` 通过；站点标题规则抽出来跑 9 个用例全通过（含 4 个「不能误伤」反例：`总裁助理`、`产品经理`、`美团 - 产品经理` 等）；moka 实页重测 —— 岗位名 = 「【2027届秋招】产品经理」，公司名 = 「搜狐畅游」

## v1.7.0 (2026-09-05)

### 新增 — 岗位匹配度 V1 插件入口（方案 A：插件直读简历库）

把 v1.6.0 的匹配度引擎接进插件投递决策点：职位页打开弹窗 → 选简历版本 → 算匹配度 → 高分一键投递，匹配分随记录留档。

- **飞书「简历库」表**（JobPulse base 内新建 `tbl5E5qBJh8NX7fH`）：字段 简历名称 / 适用方向(单选) / 简历正文 / 来源版本 / 更新时间(自动)。新增 `agent/init_match_tables.py` 一次性幂等脚本（建表 + 种子主简历 + 给投递表加「匹配分」数字列），**只新建不改已有字段**
- **插件弹窗**：新增「简历版本」下拉（读简历库）、「🧮 算匹配度」按钮、分数摘要区——总分 + verdict 三色 pill（可投绿/建议优化琥珀/不建议投红）+ 三维度细进度条 + JD 缺口 ≤3 条（真缺/可补）+ 硬门槛未满足红字告警
- **高分直投**：verdict=可投（≥70 且硬门槛过）时提交按钮变「✓ 一键投递 · N分」，复用现有写飞书流程；写盘时附「匹配分」数字字段
- **契约容错**：verdict 按中文值、dimensions.weight 按小数解析（与 `docs/match-schema.md` §2 示例差异），`deriveVerdict` 防御硬门槛一票否决

### 安全 — /api/match 降级式可选鉴权

- `/api/match` 在 `MATCH_API_TOKEN` 环境变量存在时校验请求头 `X-Match-Token`，不符返 401；未配置则维持现状裸跑（本地 CLI / agent 不受影响）。`Access-Control-Allow-Headers` 扩展允许该自定义头
- 已在 Render 配置随机 token 并上线；线上三态实测通过（无 token 401 / 错 token 401 / 正确 token 进入业务逻辑）

### 变更
- `manifest.json`：`host_permissions` 增加 `jobpulse-extension.onrender.com` 与本地回环（MV3 下前端 fetch 自建后端必需）
- `setup.*`：新增 3 个**可选**配置（简历库 Table ID 留空自动查表 / 匹配后端地址默认 Render / 匹配 Token）
- 插件算分超时 30s→60s（吸收 Render 免费实例冷启动 + LLM 波动）
- `docs/PRD-MATCH.md` 纳入版本控制（v0.1→v0.2 状态：V1 落地中）

### ⏳ 待办（如实，未标完成）
- 标注集 + 人工标注（评测校准引擎分数可信度）——方法论暂停待续
- V2 优化闭环：联动网页（命中表全量 / 逐段简历诊断 / 紧扣 JD 改写稿左右对照 / 另存新版本）
- V3 独立化 / BYOK 分享

---

## v1.6.1 (2026-08-28)

### 修复 — 线上 Agent 版本落后 + 连错表（部署同步）

**根因**：Render 线上代码停留在 7/11（commit `9813915`），8 月本地开发的 16 个 commit 全部未推送、未部署；且 Render 环境变量的表格配置仍指向旧表。导致线上 Agent 既"笨"（缺 function calling 对话引擎，对话理解差）又查不到新投递（读的是旧表，8/26 投递为空）。

- **同步 Render 环境变量**：`FEISHU_APP_TOKEN` / `FEISHU_TABLE_ID` / 飞书应用凭证 / LLM 配置统一更新为当前值（JobPulse_Database 主表）
- **推送本地 16 个 commit 到 GitHub main**（`9061096`，含 function calling 重构、昨天/前天投递意图、匹配度引擎等），触发 Render 自动部署上线最新代码
- **处理 GitHub 历史分叉**：远程 `9813915` 与本地改动重叠，逐文件对比确认本地已完整覆盖远程功能后，`merge -X ours` 以本地为准
- **验证**：飞书对话「前天投了多少」正确返回 8/26 的 7 条投递；「今天」「昨天」查询正常；`/api/match` 接口确认新代码上线

### 变更
- 无代码改动；本条目为部署/运维层修复（GitHub main = Render 线上 = 本地 三方对齐）

---

## v1.6.0 (2026-08-27)

### 新增 — 岗位匹配度模块（第一阶段：引擎 + 接口 + 评测框架）

- **匹配度引擎** `agent/match_engine.py`：JD + 简历 → 结构化评分报告。分维度加权（硬性门槛20% / 技能匹配40% / 经历相关性40%）+ JD 要求命中表（逐条证据 + source 三分类）+ 硬性门槛布尔判定 + 逐段诊断
- **算法预核对层**：jieba 中文分词 + 招聘停用词 + 整词边界正则 → 关键词命中信号（`keyword_hit_rate` / `discrepancy`），喂给 LLM 作客观锚点防分数虚高（发散调整）
- **verdict 后处理强一致**：硬性门槛不满足 → 「不建议投」（降权提示，总分不压低）；分数档位映射（≥70 可投 / 55-70 建议优化 / <55 不建议投）
- **POST /api/match 接口**：jd_text + resume_text 直传，返回评分报告；json_resp 统一加 CORS 头 + OPTIONS 预检
- **`--match` CLI**：`python agent.py --match --jd <文件> --resume <文件>`
- **评测框架** `agent/match_eval/run_eval.py`：分层指标（总分 MAE / verdict 一致率 / 硬性门槛一致率 / 命中表 P/R）+ `--make-template` 生成待标注模板 + 结果缓存 + `--keyword-only` 秒级模式

### 文档
- `docs/match-schema.md`：匹配度引擎**契约**（评分报告 Schema / prompt 全文 / 权重锚点 / 算法核对层公式 / 评测规范）—— 双端实现唯一事实来源
- `docs/TECH-MATCH.md` 升级 v0.2：三项目**代码级实测**调研结论（§2.1）+ 融合分层架构（§3）+ 设计决策记录 D1-D5（§3.5）+ 风险补充（§9）
- `docs/PRD-MATCH.md`：岗位匹配度产品需求文档（v0.1，评审通过）

### 变更
- `config.py` 新增 `MATCH_THRESHOLD` / `MATCH_WEIGHTS` / `MATCH_MAX_JD_CHARS` / `MATCH_MAX_RESUME_CHARS`
- `requirements.txt` 新增 `jieba>=0.42.0`
- `.gitignore` 新增 `.codex/`（Codex CLI 配置含 Render token）、`agent/match_eval/` 的标注集/缓存/模板（含简历摘录，隐私）

### ⏳ 进行中 / 待做
- 标注集建立 + 人工标注（10 条真实 JD 已拉取入 eval_set.json，待用户标注）
- 插件 V1 入口（选简历版本 → 算分 → 高分直接投递）
- 简历库表（飞书新建「简历库」表）与 resume_version_id 支持

### 技术栈
| 层 | 技术 |
|---|---|
| 匹配度引擎 | jieba 分词 + DeepSeek（temperature 0.1 / json_object 降级重试） |
| 评测 | 结构化标注集 + 分层指标（MAE / 一致率 / P-R） |

---

## v1.5.0 (2026-08-22)

### 新增
- **对话引擎 Agent 化（function calling）**：飞书 bot 从「意图分类 + 硬编码分支」升级为真正的 agent —— LLM 自主决定调用工具、组合查询、用自然语言生成回复，不再靠模板拼文案
- **多轮对话记忆**：新增 `agent/memory.py`，按用户保留最近 5 轮对话（`conversation_store.json`），能接住「那腾讯呢？」这类指代追问
- **tool-use 循环**：`llm_client.py` 新增 `chat_with_tools()`，完整实现「模型决定调工具 → 执行 → 结果回填 → 再决策」循环，带轮数上限防死循环
- **工具注册表**：10 个工具全部改为结构化返回 + function schema 注册，LLM 可自主选择与组合

### 变更
- **handle_message 重构**：入口签名不变（callback_server 零改动），内部走 agent 循环；回复由 LLM 生成而非模板拼接
- **降级路径**：API 不支持 function calling（如 Anthropic 端点）时自动回退旧 classify 流程，能力不降级
- **`.gitignore`**：新增 `agent/conversation_store.json`

### 技术栈
| 层 | 技术 |
|---|---|
| LLM 对话引擎 | DeepSeek function calling（OpenAI 兼容 tools 协议） |
| 多轮记忆 | 本地 JSON（conversation_store.json，按 open_id 分桶） |

---

## v1.4.1 (2026-07-28)

### 新增
- **「待投递」状态支持**：插件弹窗结果字段新增「待投递」选项，用户在职位详情页可以标记"想投但还没准备好投递"的岗位，避免忘记同时不触发跟进提醒
- **数据看板待投递统计**：统计卡片新增"待投递"指标，漏斗图新增"待投递"阶段（总投递→待投递→简历筛选→进入面试）
- **Agent 待投递排除**：跟进提醒、归因分析、统计等所有逻辑均正确排除「结果=待投递」的记录，不干扰核心投递流程

### 变更
- **stats_card 卡片模板**：新增 `to_apply` 参数，飞书统计卡片展示待投递数量
- **飞书表格「结果」字段**：扩展选项为「待投递」/「简历」/「面试」/「简历挂」/「无反馈」（需在飞书多维表格中手动添加「待投递」选项）

---

## v1.4.0 (2026-07-11)

### 新增
- **bot 对话录入投递时支持保存岗位 JD**：create_record 意图新增 `jd` 参数，LLM 从用户的自然语言中提取职位描述并写入「岗位JD」字段
- **昨天/前天投递查询**：新增 `query_date_count` 意图，支持「昨天投了多少」「前天投递」「7月8号投了啥」
- **「推送卡片」手动指令**：飞书对话可直接触发跟进提醒卡片推送

### 修复
- **Agent 今日投递计数始终为空**：根因是 `_query_today_count` 从记录顶层读 `created_time`，但飞书列表 API 可能不返回该字段。改为优先从 `fields.投递时间` 读取，兼容多种格式
- **`_get_days` / `get_days_since` 天数计算不准**：同样改为优先读 `fields.投递时间`
- **飞书时间戳格式兼容**：`_parse_ts_ms` 加入秒级→毫秒级自动转换（1e9~1e11 范围启发式识别），解决飞书日期字段返回秒级时间戳导致比较失败的问题
- **Mokahr 页面公司名和岗位名抓不到**：添加 58→58同城 公司映射；补充 Mokahr SPA 岗位 CSS 选择器（apply-position/recruit-name/campus-name/position-title）；扩展 detail 容器内 h1/h2/h3 兜底提取

### 变更
- **意图识别提示词全部改为中文**：优化 DeepSeek V4 的中文理解能力
- **LLM classify 方法健壮化**：支持不带 `response_format` 回退；`_extract_json` 支持从 markdown 代码块和文本中搜索 JSON 对象
- `classify` 的 `max_tokens` 从 500 提至 2000，防止长 JD 被截断
- 已推送的卡片消息 ID 同时写入飞书表格「消息ID」字段和本地文件，回调时双路回退

### 技术栈
| 层 | 技术 |
|---|---|
| LLM 意图分类 | DeepSeek V4（中文提示词） |
| API 推送 | GitHub API（git data API 绕过网络限制） |

### 新增
- **飞书机器人对话全面增强**：新增 `query_record`（查进度）、`record_interview`（记面试时间）意图
- **配置页面** `setup.html`：用户自行填入飞书凭证，存入 chrome.storage.local，不在代码中硬编码
- **数据看板配置兼容**：dashboard.js 从 chrome.storage.local 读取凭证，无需修改代码

### 修复
- **面试查询不准**：`_query_interviews` 以前只查"面试时间"字段，现在同时检查"结果=面试"和"面试时间"字段，已进入面试但未填时间的单独列出
- **查进度被误当作新投递**：新增 `query_record` 意图，LLM 识别"字节怎么样了"等查询；`_execute_create` 加重复检查防误创建
- **README.md 移除 PROJECT_REVIEW.md 引用**：隐私文档不上传 GitHub

### 变更
- **密钥外置**：popup.js / dashboard.js 删除硬编码飞书密钥，改为 `setup.html` 配置页写入 chrome.storage.local
- **config.py 清理**：删除硬编码 FEISHU_RECEIVER_ID，全部走环境变量
- **manifest.json**：新增 `storage` 权限
- **git 历史清洗**：用 filter-branch 将全部 36 个 commit 中的密钥替换为占位符，__pycache__ 从追踪中移除
- **PROJECT_REVIEW.md**：移出 git 追踪（仅本地维护），加入 .gitignore
- **README 全面更新**：适配开源后的自配置流程

### 技术栈
| 层 | 技术 |
|---|---|
| 配置存储 | chrome.storage.local |
| 历史清洗 | git filter-branch |

## v1.2.0 (2026-07-01)

### 新增
- **BOSS直聘适配**：支持 zhipin.com 职位详情页一键抓取（岗位/公司/JD/薪资）
- **CSS 干扰文字过滤**：针对 BOSS直聘反爬机制，用 `getComputedStyle` 过滤 `display:none`/`visibility:hidden`/`opacity:0` 等隐藏干扰文本
- **薪资字段**：弹窗新增薪资输入框，BOSS直聘自动抓取，飞书表格新增「薪资」文本列
- **数据看板** `dashboard.html`：独立全屏页面，Chart.js 渲染投递漏斗图、公司分布环形图、投递时间线
- **弹窗快捷入口**：底部新增飞书表格、飞书Bot、数据看板三个快捷链接

### 修复
- **BOSS直聘公司名识别错误**：选择器从宽泛的 `[class*="company"] a` 改为 `a[href*="/company/"]`，并添加页面标题解析回退和 "BOSS直聘" 安全过滤
- **BOSS直聘薪资显示乱码**：添加 Unicode 字符过滤，丢弃图标字体等不可见字符
- **飞书卡片回调 200341 超时**：`handle_card_action` 改为先返回响应、后台线程处理 API 操作，避免飞书 3 秒超时导致误报错
- **美团岗位名抓取错误**：岗位名回退到"职位详情"等无效值时的修复，从页面标题分段重新提取

### 变更
- **CLAUDE.md 开发规范扩展**：新增文档同步规则和 PROJECT_REVIEW 写作规范
- **路线图更新**：第一阶段抓取适配和第二阶段数据看板标记为已完成

### 技术栈
| 层 | 技术 |
|---|---|
| 数据看板 | Chart.js 4.4.7（本地打包） |
| BOSS直聘抓取 | getComputedStyle 可见性检测 + 多级选择器回退 |
| 薪资提取 | CSS 选择器 + 页面标题正则匹配 |

## v1.1.0 (2026-06-26)

### 新增
- **Render 云部署**：回调服务从本地 ngrok 迁移至 Render.com 固定域名，7x24h 在线
- **飞书私聊机器人**：通过 `im.message.receive_v1` 事件订阅，用户可直接在飞书私聊与机器人对话
- **DeepSeek AI 集成**：接入 DeepSeek Chat，支持自然语言查询投递数据、记录投递、更新状态
- **lark-cli 集成**：使用飞书官方 CLI 工具进行 API 调试与事件管理

### 修复
- **chat_type 兼容**：飞书 v2 事件中 `chat_type` 值为 `"p2p"` 而非旧版 `"private"`，导致私聊消息被静默丢弃
- **环境变量读取**：`config.py` 中 LLM_API_KEY/LLM_API_BASE/LLM_MODEL 硬编码为空字符串，未使用 `env()` 读取环境变量
- **Render $PORT 转义**：Start Command 中 `\$PORT` 导致 shell 未展开变量，gunicorn 收到字面量

### 变更
- **安全加固**：移除 config.py 中硬编码的飞书密钥（FEISHU_APP_SECRET / FEISHU_APP_TOKEN），全部改为环境变量注入
- **.gitignore 更新**：排除 `__pycache__/`、`.Rhistory`、`agent/message_store.json`

### 技术栈
| 层 | 技术 |
|---|---|
| 回调服务 | Python Flask + Gunicorn |
| 部署平台 | Render.com（Free Plan, Singapore） |
| 飞书集成 | lark-cli（官方 CLI）/ Open API |
| AI 模型 | DeepSeek Chat（OpenAI 兼容格式） |
| CI/CD | GitHub → Render Auto Deploy |
