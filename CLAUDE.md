# JobPulse · 招聘同步飞书

Chrome Extension + Agent 双组件项目。插件在招聘官网岗位详情页抓取岗位信息一键同步到飞书多维表格；Agent 定时追踪投递进度，通过 AI 进行归因分析并发送飞书卡片提醒。

---

## 项目结构

```
JobPulse_Extension/
├── manifest.json          # Chrome Extension Manifest V3
├── popup.html             # 弹窗 UI
├── popup.js               # 核心逻辑：页面抓取 + 飞书 API 写入
├── CLAUDE.md              # 本文件
├── .gitignore
│
├── agent/                 # 求职追踪 Agent（Python）
│   ├── agent.py           # 主入口：追踪 & 归因分析
│   ├── feishu.py          # 飞书 API 客户端
│   ├── cards.py           # 消息卡片模板
│   ├── config.py          # 配置（支持环境变量覆盖）
│   ├── llm_client.py      # LLM 客户端（OpenAI / Claude）
│   ├── callback_server.py # 卡片按钮回调服务（Flask）
│   ├── get_openid.py      # 获取飞书 open_id 工具
│   └── requirements.txt   # Python 依赖
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
高频追踪（每日）:
  飞书查表 → 筛选提醒状态=待跟进 且 投递天数≥3
          → 发送跟进提醒卡片（含按钮回调）

低频归因（每周）:
  读取所有 JD → LLM 分析技能要求分布
             → 生成匹配度报告与投递策略建议
             → 发送复盘周报卡片
```

### 飞书多维表格字段

| 字段 | 类型 | 说明 |
|---|---|---|
| 岗位 | 文本 | 插件自动抓取 |
| 公司 | 文本 | 插件自动抓取 |
| 岗位JD | 文本 | 插件自动抓取（仅职责+要求段落） |
| 投递链接 | 链接 | 当前页 URL |
| 结果 | 单选 | 简历 / 面试 / 无反馈（默认"简历"） |
| 提醒状态 | 单选 | 待跟进 / 已跟进 / 已失效 / 有反馈（默认"待跟进"） |
| 投递天数 | 公式 | `DAYS(TODAY(), {投递时间})` |
| 消息ID | 文本 | Agent 发送卡片后写入，回调时读取以更新卡片 |
| 面试时间 | 日期 | 面试提醒功能使用 |
| 是否复盘 | 复选框 | 面试后是否已完成复盘（待实现） |
| 复盘笔记 | 文本 | 面试复盘记录（待实现） |

---

## 开发路线图

### 第一阶段：抓取适配（已完成）
- [x] **国内主流招聘平台适配**：阿里/腾讯/字节/快手/网易/美团/mokahr/BOOS直聘
- [x] **CSS 干扰文字过滤**：BOSS直聘反爬对抗（getComputedStyle 可见性检测）
- [x] **薪资字段**：弹窗输入框 + 飞书表格「薪资」列

### 第二阶段：可视化数据看板（已完成）
- [x] **数据看板页面** `dashboard.html`：纯前端 HTML，通过飞书 API 拉取表格数据，用 Chart.js 渲染
  - 投递漏斗图（总投递→简历→面试）
  - 公司分布环形图
  - 投递时间线（按周统计）
  - 统计卡片（总投递/面试/待跟进/已失效）
- [x] **弹窗快捷入口**：飞书表格 / 飞书Bot / 数据看板 三个链接
- [ ] **完善 Agent 入口**：`--full` 模式串联追踪+统计+面试提醒+归因分析
- [ ] **更新 GitHub Actions**：增加统计定时任务（如每周一推送周报）

### 第三阶段：机器人对话增强与开源（已完成）
- [x] **飞书机器人对话增强**：新增 query_record / record_interview 意图，支持查进度、记面试时间、改状态
- [x] **对话 bug 修复**：面试查询不准、查进度误创建记录
- [x] **密钥外置**：popup.js/dashboard.js 删除硬编码，改为 chrome.storage.local + setup 配置页
- [x] **开源准备**：git 历史清洗、PROJECT_REVIEW.md 本地化、README 更新

### 第四阶段：全链路求职追踪
- [ ] **面试题预测**：LLM 读 JD 生成高频面试题，面试前推送
- [ ] **面试题预测**：LLM 读 JD 生成高频面试题，面试前推送
- [ ] **岗位匹配度评分** `--match`：LLM 对比简历文本与 JD，输出匹配度分数和改进建议
- [ ] **拒信归因**：`rejection_insight_card` 卡片模板已就绪，需接入 Agent 自动识别被拒记录并做 LLM 归因

---

## 开发规范

- **不构建**：纯原生 Chrome Extension，无 bundler
- **敏感信息**：通过环境变量注入，不硬编码提交
- **错误处理**：插件侧所有 API 调用有 try-catch + 用户提示
- **命名**：飞书表格字段名与代码对象 key 保持一致（岗位、公司、岗位JD、投递链接、结果）
- **Git 提交**：每完成一个有意义的改动主动 commit，提交信息用中文写清楚改了什么
- **文档同步**：用户说"更新版本记录"或每次阶段性完成功能后，同步更新：
  - `CHANGELOG.md` — 按版本号新增条目（新增/修复/变更），标注日期
  - `PROJECT_REVIEW.md` — **面试级深度复盘**：补充技术问题四段式记录、决策对比表、状态快照同步、数据递增，详见下方写作规范
  - CLAUDE.md — 路线图勾选已完成项、更新已知的坑、更新表格字段说明

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
- React SPA 页面（如快手招聘）内容动态渲染，岗位名可能在 `div` 而非 `h1/h2` 中
- BOSS直聘有 CSS 反爬干扰文本（display:none / opacity:0），需 getComputedStyle 过滤
- 页面标题分割提取岗位名时，公司名可能误占岗位位，需评分制+岗位关键词加权

### 飞书集成
- 飞书自建应用的权限开通后必须**发布新版本**才生效
- 卡片交互按钮需要部署回调服务接收飞书 card action webhook（Render / ngrok）
- 飞书事件订阅的 chat_type 字段 v2 版变为 "p2p" 而非旧版 "private"，必须兼容两种
- 多维表格字段名必须与 API 代码中的 key **一字不差**，否则 API 静默失败或写入错误列

### Git & 安全
- **git filter-branch --tree-filter 会丢失 untracked 文件**：运行前确认所有 untracked 文件已备份或提交。PROJECT_REVIEW.md 就是实际教训
- Chrome Extension 前端不能藏密钥（JS 源码可被查看）。开源必须改为用户自配置（chrome.storage.local），不能靠 .gitignore + config.js 解决
- 密钥一旦被提交到 git，即使后来删掉文件，历史记录里仍可找回。必须用 filter-branch / BFG 彻底清洗
