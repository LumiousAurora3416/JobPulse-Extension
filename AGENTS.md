# JobPulse · 招聘同步飞书

> **本文件是项目规范的唯一来源**（`AGENTS.md`，跨工具通用格式）。Codex / Cursor / Gemini CLI 等工具直接读本文件；Claude Code 通过 `CLAUDE.md` 里的一行 `@AGENTS.md` 导入本文件。
> **改规范请只改本文件**，不要再建副本——历史上 `CLAUDE.md` 与 `AGENTS.md` 各存一份，导致内容分叉了 5 个版本。

Chrome Extension + Agent 双组件项目。插件在招聘官网岗位详情页抓取岗位信息一键同步到飞书多维表格；Agent 定时追踪投递进度，通过 AI 进行归因分析并发送飞书卡片提醒。

---

## 项目结构

```
JobPulse_Extension/
├── manifest.json          # Chrome Extension Manifest V3
├── popup.html             # 弹窗 UI
├── popup.js               # 核心逻辑：页面抓取 + 飞书 API 写入
├── AGENTS.md              # 本文件：项目规范（跨工具通用，Codex/Cursor 等直接读取）
├── CLAUDE.md              # 仅一行 @AGENTS.md，供 Claude Code 导入本文件
├── .gitignore
│
├── agent/                 # 求职追踪 Agent（Python）
│   ├── agent.py           # 主入口：追踪 & 归因分析
│   ├── status_rules.py    # 「结果」状态机唯一真相源（v1.9.0：终态判定/卡片按钮/校验）
│   ├── message_agent.py   # 飞书私聊对话 Agent（function calling + 工具注册表）
│   ├── feishu.py          # 飞书 API 客户端
│   ├── cards.py           # 消息卡片模板（按钮按结果动态生成）
│   ├── config.py          # 配置（支持环境变量覆盖）
│   ├── llm_client.py      # LLM 客户端（OpenAI / Claude）
│   ├── callback_server.py # 卡片按钮回调服务（Flask）
│   ├── match_engine.py    # 岗位匹配度引擎（v1.6.0，JD+简历→评分报告）
│   ├── match_eval/        # 匹配度评测（标注集 eval_set + run_eval.py）
│   ├── get_openid.py      # 获取飞书 open_id 工具
│   └── requirements.txt   # Python 依赖
│
├── docs/                  # 岗位匹配度文档（PRD-MATCH / TECH-MATCH / match-schema）
│
└── .github/workflows/
    └── agent.yml          # GitHub Actions 定时任务（每日 9:00）
```

---

## 技术栈

### Chrome Extension
- **Manifest V3** — Chrome Extension 最新规范
- **Vanilla JS** — 纯原生 JS，无框架依赖
- **Chrome APIs**: `tabs`, `scripting`, `activeTab`
- **飞书 Open API**: `auth/v3/tenant_access_token`, `bitable/v1/apps/.../records`

### Agent
- **Python 3.11** — 核心运行时
- **Flask** — 卡片回调服务（可选）
- **requests** — HTTP 客户端
- **OpenAI 兼容 API** — 支持 BYOK 接入任意 LLM

### 部署
- **GitHub Actions** — Cron 定时调度 Agent
- **飞书自定义机器人** / **Open API** — 消息触达

---

## 构建与运行

### Chrome Extension

无需构建，直接在 Chrome 加载：

1. 打开 `chrome://extensions/`
2. 开启「开发者模式」
3. 「加载已解压的扩展程序」→ 选择本项目根目录
4. 去招聘官网职位详情页，点击插件图标使用

### Agent（本地运行）

```bash
cd agent
pip install -r requirements.txt
python agent.py                # 执行投递追踪
python agent.py --analyze      # 执行归因分析
python agent.py --full         # 同时执行追踪 + 分析
```

### Agent（GitHub Actions 自动运行）

在 GitHub 仓库设置以下 Secrets：

| Secret | 说明 |
|---|---|
| `FEISHU_APP_ID` | 飞书自建应用 App ID |
| `FEISHU_APP_SECRET` | 飞书自建应用 App Secret |
| `FEISHU_APP_TOKEN` | 多维表格 Base Token |
| `FEISHU_TABLE_ID` | 多维表格 Table ID |
| `FEISHU_RECEIVER_ID` | 接收消息的飞书用户 open_id |
| `FEISHU_RECEIVER_TYPE` | 固定 `open_id` |
| `LLM_API_KEY` | 大模型 API Key（BYOK） |
| `LLM_API_BASE` | API 端点（默认 OpenAI 格式） |
| `LLM_MODEL` | 模型名 |

---

## 核心逻辑说明

### 插件页面抓取流程

```
页面 DOM → JSON-LD 结构化数据
         → hostname 内置公司名（阿里/腾讯/字节/快手）
         → CSS 选择器匹配岗位名
         → pageTitle 评分制提取
         → h1/h2 标签提取（跳过公司名和招聘标签）
         → 公司名 DOM 选择器兜底
         → JD 正文提取（colletDetailText → extractDescReqModules）
         → 填充弹窗表单 → 用户确认 → 写入飞书
```

### Agent 双轮驱动

```
高频追踪（每日，v1.9.0 起「结果」状态机驱动）:
  飞书查表 → 候选 = 结果 ∈ {简历,测评,面试}（终态与待投递都不催）
                   且 投递天数 ≥ 5           （首次提醒门槛：太早跟进没意义）
                   且 (从未提醒 OR 距上次提醒 ≥ 7 天)
          → 按「距上次提醒天数」降序（从没催过的最优先；并列时按投递天数）
          → 取前 10 张（单次上限）→ 发卡片 → 写「上次提醒日期」
          → 卡片按钮按当前结果动态生成（简历→进面试/测评/简历挂；面试→一面挂/二面挂/三面挂/offer）

低频归因（每周）:
  读取所有 JD → LLM 分析技能要求分布
             → 生成匹配度报告与投递策略建议
             → 发送复盘周报卡片
```

**「是否继续提醒」由代码从「结果」推导，不再人工维护**：结果 ∈ 过程态（简历/测评/面试）就继续跟，到终态自动停。这样"面试阶段"不会被误静音（面完正是最该催结果的时候），也避免出现"一份事实存两处"导致的分叉。

### 飞书对话 Agent（v1.5.0 · function calling）

```
用户私聊 → LLM 自主决定调用工具（查今日/查进度/录投递/改状态/记面试/推送卡片）
         → 工具执行（结构化返回）→ 结果回填 LLM → 自然语言回复
         → 每轮对话写入短期记忆（agent/memory.py，最近 5 轮），支持多轮指代
```

- 工具定义在 `agent/message_agent.py` 的 `TOOLS` 注册表，新增工具只需加一个函数 + schema
- 不支持 function calling 的端点自动降级到旧 classify 流程（`_fallback_reply`）
- 多轮记忆存本地 `agent/conversation_store.json`（已加入 .gitignore）

### 飞书多维表格字段

| 字段 | 类型 | 说明 |
|---|---|---|
| 岗位 | 文本 | 插件自动抓取 |
| 公司 | 文本 | 插件自动抓取 |
| 岗位JD | 文本 | 插件自动抓取（仅职责+要求段落） |
| 投递链接 | 链接 | 当前页 URL |
| 结果 | 单选 | **状态机**（v1.9.0）。过程态：待投递 / 简历 / 测评 / 面试；终态：简历挂 / 一面挂 / 二面挂 / 三面挂 / offer / 无反馈 / 放弃。**面试不分一二三面，挂要分到轮次**（"挂在哪一轮"是复盘/求职漏斗的关键数据） |
| 提醒状态 | 公式 | `IF(OR({结果}="简历",{结果}="测评",{结果}="面试"),"待跟进","已静音")`。**纯展示的聚类标签**（待跟进=还会被催的池子），只给人看，**代码不读不写** |
| 上次提醒日期 | 日期 | 追踪推送后写入；控制复催节奏（按"距今天数"降序取前 N 张）。结果进终态时也写入 |
| 投递天数 | 公式 | `DAYS(TODAY(), {投递时间})` |
| 消息ID | 文本 | Agent 发送卡片后写入，回调时读取以更新卡片 |
| 面试时间 | 日期 | 面试提醒功能使用 |
| 是否复盘 | 复选框 | 面试后是否已完成复盘（待实现） |
| 复盘笔记 | 文本 | 面试复盘记录（待实现） |
| 薪资 | 文本 | 插件自动抓取（BOSS直聘）或弹窗手动输入 |
| 匹配分 | 数字 | 插件算匹配度后写入（v1.7.0），投递时匹配度留档供归因/校准 |
| 企业性质 | 单选 | 央国企 / 民营企业 / 外企 / 其他（v1.8.0）。插件下拉手选、Bot 对话提到才写，**不做自动识别**；没选则不写该列 |

---

## 开发路线图

### 第一阶段：抓取适配（已完成）
- [x] **国内主流招聘平台适配**：阿里/腾讯/字节/快手/网易/美团/mokahr/BOOS直聘
- [x] **CSS 干扰文字过滤**：BOSS直聘反爬对抗（getComputedStyle 可见性检测）
- [x] **薪资字段**：弹窗输入框 + 飞书表格「薪资」列

### 第二阶段：可视化数据看板（已完成）
- [x] **数据看板页面** `dashboard.html`：纯前端 HTML，通过飞书 API 拉取表格数据，用 Chart.js 渲染
  - 投递漏斗图（总投递→待投递→简历→面试）
  - 公司分布环形图
  - 投递时间线（按周统计）
  - 统计卡片（总投递/待投递/面试/待跟进/已失效）
- [x] **弹窗快捷入口**：飞书表格 / 飞书Bot / 数据看板 三个链接
- [ ] **完善 Agent 入口**：`--full` 模式串联追踪+统计+面试提醒+归因分析
- [ ] **更新 GitHub Actions**：增加统计定时任务（如每周一推送周报）

### 第三阶段：机器人对话增强与开源（已完成）
- [x] **飞书机器人对话增强**：新增 query_record / record_interview 意图，支持查进度、记面试时间、改状态
- [x] **对话 bug 修复**：面试查询不准、查进度误创建记录
- [x] **密钥外置**：popup.js/dashboard.js 删除硬编码，改为 chrome.storage.local + setup 配置页
- [x] **开源准备**：git 历史清洗、PROJECT_REVIEW.md 本地化、README 更新

### 第四阶段：全链路求职追踪
- [x] **bot 对话录入带 JD**：create_record 支持提取职位描述，写入岗位JD 字段
- [x] **意图识别优化**：中文提示词适配 DeepSeek V4，新增 query_date_count（昨天/前天查询）
- [x] **时间戳兼容**：修复飞书日期字段秒级/毫秒级格式兼容问题
- [x] **「待投递」状态支持**：插件/看板/Agent 全链路支持"想投暂未投"的岗位记录
- [x] **对话引擎 Agent 化**：DeepSeek function calling + 多轮记忆，LLM 自主调工具、自然语言回复（v1.5.0）
- [ ] **面试题预测**：LLM 读 JD 生成高频面试题，面试前推送
- [x] **岗位匹配度评分（第一阶段完成 v1.6.0）** `--match`：引擎 + /api/match + CLI + 评测框架
  - [ ] 标注集建立 + 人工标注（10 条真实 JD 已拉取，方法论暂停待续）
  - [x] **插件 V1 入口 + 简历库表（v1.7.0）**：飞书「简历库」表 + 插件选版本算分 + 高分直投 + 「匹配分」入投递表
  - [ ] **V2 优化闭环**：联动网页（命中表全量 / 逐段简历诊断 / 紧扣 JD 改写稿左右对照 / 另存新版本）
- [x] **企业性质字段（v1.8.0）**：投递表新增「企业性质」单选列（央国企/民营企业/外企/其他），插件下拉手选 + Bot 对话提到才写；`init_match_tables.py` 幂等建列
- [x] **「结果」状态机重构（v1.9.0）**：`status_rules.py` 做唯一真相源；结果列当状态机（过程态/终态，挂分轮次）；提醒状态改**公式列**只当聚类标签；提醒节奏改为「首次5天 + 复催7天 + 单次上限10张，最久未催优先」并新增「上次提醒日期」列；卡片按钮按当前结果动态生成；bot 改状态只写结果列（顺带修好一直失效的卡片「面试」按钮、恒为 0 的面试统计、看板串列统计）
- [ ] **拒信归因**：`rejection_insight_card` 卡片模板已就绪，需接入 Agent 自动识别被拒记录并做 LLM 归因

---

## 开发规范

- **不构建**：纯原生 Chrome Extension，无 bundler
- **敏感信息**：通过环境变量注入，不硬编码提交
- **错误处理**：插件侧所有 API 调用有 try-catch + 用户提示
- **命名**：飞书表格字段名与代码对象 key 保持一致（岗位、公司、岗位JD、投递链接、结果）
- **本地素材目录**：面试素材 / 思考过程 / 复盘（简历、PROJECT_REVIEW、面试题、架构图等）统一放 `private/` 目录，已被 `.gitignore` 保护，**绝不上传 GitHub**。新增此类文件一律丢 `private/`，禁止 `git add` 该目录下的文件
- **Git 提交**：每完成一个有意义的改动主动 commit，提交信息用中文写清楚改了什么
- **文档同步**：用户说"更新版本记录"或每次阶段性完成功能后，同步更新：
  - `CHANGELOG.md` — 按版本号新增条目（新增/修复/变更），标注日期
  - `PROJECT_REVIEW.md` — **面试级深度复盘**：补充技术问题四段式记录、决策对比表、状态快照同步、数据递增，详见下方写作规范
  - `AGENTS.md` — 路线图勾选已完成项、更新已知的坑、更新表格字段说明（**本文件，唯一规范源**）

### PROJECT_REVIEW 写作规范

PROJECT_REVIEW.md 本质是**你的面试作品集级复盘文档**，受众是自己（深度反思用）和面试官（展示项目能力和产品思维）。它不是技术日志，而是你**怎么思考问题、怎么做决策、怎么从失败中学到东西**的证据。

要求：

1. **技术问题四段式**（每个技术问题都要写）：现象 → 根因 → 解决方案 → 学到了什么
2. **决策对比表**：凡是产品和技术的选型（A vs B），用表格对比维度+决策，说明为什么选这个不选那个
3. **状态快照同步**：附录的 ✅ 已完成 / ⏳ 下一迭代待做 必须和实际进度一致，每次版本更新都更新
4. **数据递增**：代码行数、commit 数、文件数每次迭代更新，体现项目成长
5. **面试总结**：一句话说清解决了什么、怎么做的、学到了什么（放在附录最上方，方便面试官一眼看到）

## 已知的坑

### 插件 & 页面抓取
- React SPA 页面（如快手招聘、Mokahr 校招）内容动态渲染，岗位名可能在 `div` / `span` / `h3` 而非 `h1/h2` 中，CSS 选择器需持续补充
- BOSS直聘有 CSS 反爬干扰文本（display:none / opacity:0），需 getComputedStyle 过滤
- 页面标题分割提取岗位名时，公司名可能误占岗位位。**光靠评分制+岗位关键词加权不够**：标题若是「公司名 - 校园招聘」这类**站点标题**（本身不含岗位名），评分制挑出来的必然是公司名。已加「站点标题」判定兜住这一类（`popup.js` 第 3/4 层，站点无关）
- **moka 是 hash 路由 SPA**（岗位 id 在 `#/job/<uuid>`），`document.title` 是「公司名 - 校园招聘」这种站点标题、**不含岗位名**；岗位名在 `div[class*="sd-foundation-heading"]` 里，**页面没有 h1**。类名尾部是发版就变的 hash，只能匹配前缀
- **moka 公司名靠第 6 层「反推」拿到**：`og:site_name` 为 `null`、公司名不在 DOM 独立节点，靠 pageTitle 分段反推；生效前提是 `position` 已正确——岗位名填错，公司名会一起错，两个字段是互相推导的
- `[class*="post-title"]` 不匹配 `position-title`（子串不包含 "post-title"），双 attribute 选择器 `[class*="position"][class*="title"]` 更可靠

### 飞书集成
- 飞书自建应用的权限开通后必须**发布新版本**才生效
- 卡片交互按钮需要部署回调服务接收飞书 card action webhook（Render / ngrok）
- 飞书事件订阅的 chat_type 字段 v2 版变为 "p2p" 而非旧版 "private"，必须兼容两种
- 多维表格字段名必须与 API 代码中的 key **一字不差**，否则 API 静默失败或写入错误列
- 飞书表格**已有字段**的修改必须走网页端，API 只能建新字段（踩过：误改导致列错位）
- **单选字段写入不存在的选项会直接报错**（`FieldConvFail`），飞书**不会自动新增选项** → 必须先建列时就把选项带全（`property.options`）。两个踩过的实例：①「企业性质」选项值同时存在于 `agent/init_match_tables.py` 的 `COMPANY_TYPE_OPTIONS` / `popup.html` 下拉框 / `agent/message_agent.py` 的 `COMPANY_TYPES` 三处；②卡片「面试」按钮写 `结果="面试"`，但结果列后来被细化成 测评/一面挂/二面挂/offer，没有「面试」了 → 该按钮与"记面试时间"功能**静默失效数月**（表现是"点了没反应"）。**改选项顺序：先在飞书网页端改列 → 再改代码 → 跑 `init_match_tables.py` 校验**（脚本会打印选项差异）
- **同一份事实不要存在两处**（v1.9.0 的教训源头）：「提醒状态」原本一半的值（有反馈/已失效）是「结果」列终态的副本，靠手工标注同步，于是必然分叉——映射表把 `面试 → 有反馈 → 停止提醒`，而面试是**过程态**，面完正是最该催结果的时候，结果反被静音；同时"测评中"的岗位没有对应按钮，只能天天被催。**方向是反的**。修法：把"是否继续提醒"改成从「结果」**推导**（终态即停），提醒状态降级为公式列只做展示。**凡是需要两列手工同步的设计，迟早会分叉**
- **公式列是只读的**：API 写不进去、表格里也点不动。所以凡是被改成公式的列（如「提醒状态」），代码里所有写入点都必须删干净，否则整条记录写入失败
- **枚举值散落多处就必须显式标注同步关系**：`status_rules.py` 是「结果」状态机的唯一真相源，`dashboard.js` 顶部的分组数组必须与它一致（JS 无法直接 import Python，只能靠注释约束 + `init_match_tables.py` 校验）

### 匹配度引擎 & 评测
- 匹配度是主观判断，评测真值是用户标注（一致性评测），不是客观对错；标注者对自己判断的自信度是关键卡点
- 评测 P/R 必须对齐粒度：`--make-template` 以 AI 命中表为基准生成标注模板；人工另拆粒度会导致指标失真
- 评测缓存只存 AI 报告，`human` 实时读标注集（缓存复用旧标注会让指标不更新）
- 借鉴开源方案必须读源码：ResumeIQ 宣称"15 组标注 MAE 5.0"但仓库实际只有 3 组；@resurank 英文 tokenizer 对中文直接报废
- 算法核对层只证伪"分数虚高"：词面不重叠但语义很配是盲区，靠 LLM 语义兜底
- 插件直调自建后端要过两层：manifest `host_permissions` 放行域名 + 后端 CORS `Access-Control-Allow-Headers` 含自定义头（如 X-Match-Token），缺一浏览器都拦
- Render 免费实例闲置约 15 分钟休眠、冷启动可达数十秒：/api/match 前端超时设 60s；manifest/JS 改动后必须 reload 扩展才生效

### Git & 安全
- **git filter-branch --tree-filter 会丢失 untracked 文件**：运行前确认所有 untracked 文件已备份或提交。PROJECT_REVIEW.md 就是实际教训
- Chrome Extension 前端不能藏密钥（JS 源码可被查看）。开源必须改为用户自配置（chrome.storage.local），不能靠 .gitignore + config.js 解决
- 密钥一旦被提交到 git，即使后来删掉文件，历史记录里仍可找回。必须用 filter-branch / BFG 彻底清洗
- **指令文件单一来源**：`AGENTS.md` 是唯一规范源，`CLAUDE.md` 只放一行 `@AGENTS.md`。两份内容并存会分叉（本文件与旧副本曾差 5 个版本）
