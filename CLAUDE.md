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

### 第二阶段：可视化数据看板
- [ ] **数据看板页面** `dashboard.html`：纯前端 HTML，通过飞书 API 拉取表格数据，用 Chart.js 渲染
  - 投递漏斗图（总投递→面试→offer）
  - 公司分布饼图
  - 投递时间线
  - 状态分布统计
- [ ] **完善 Agent 入口**：`--full` 模式串联追踪+统计+面试提醒+归因分析
- [ ] **更新 GitHub Actions**：增加统计定时任务（如每周一推送周报）

### 第三阶段：全链路求职追踪
- [ ] **岗位匹配度评分** `--match`：LLM 对比简历文本与 JD，输出匹配度分数和改进建议
  - 简历文本放在 `config.py` 的 `RESUME_TEXT` 配置项
  - 生成匹配度卡片推送到飞书
- [ ] **面试复盘记录**：
  - 飞书表格新增"是否复盘""复盘笔记"字段
  - 跟进卡片增加"已复盘"按钮，点击后标记并提示填写复盘笔记
- [ ] **拒信归因**：`rejection_insight_card` 卡片模板已就绪，需接入 Agent 自动识别被拒记录并做 LLM 归因

---

## 开发规范

- **不构建**：纯原生 Chrome Extension，无 bundler
- **敏感信息**：通过环境变量注入，不硬编码提交
- **错误处理**：插件侧所有 API 调用有 try-catch + 用户提示
- **命名**：飞书表格字段名与代码对象 key 保持一致（岗位、公司、岗位JD、投递链接、结果）

## 已知的坑

- React SPA 页面（如快手招聘）内容动态渲染，岗位名可能在 `div` 而非 `h1/h2` 中
- 飞书自建应用的权限开通后需发布新版本才生效
- 卡片交互按钮需要部署回调服务接收飞书 card action webhook
