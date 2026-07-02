<p align="center">
  <h1 align="center">JobPulse</h1>
  <p align="center">一键同步 · 自动追踪 · AI 复盘</p>
  <p align="center">秋招投递管理的终点，不再靠脑子记</p>
</p>

---

## 这是什么

秋招投了几十家之后，你会发现最痛苦的不是投不出去，而是**投出去之后的失控感**——哪些石沉大海了、哪些该跟进了、自己的投递策略对不对，全靠脑子记。

JobPulse 是一套基于 **Chrome 插件 + 飞书多维表格 + AI Agent** 的求职投递管理系统：

- **Chrome 插件**：在招聘官网职位详情页一键抓取岗位信息，同步到飞书表格
- **AI Agent**：每天自动扫描待跟进记录，发飞书卡片提醒，按钮点击即可更新状态
- **数据看板**：投递漏斗、公司分布、时间线一目了然
- **归因分析**：每周 AI 复盘所有 JD，给出技能要求和投递策略建议

全程零成本，不需要服务器，飞书生态搞定一切。

---

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                   Chrome 插件                             │
│  招聘官网 → 一键抓取(岗位/公司/JD/薪资) → 飞书多维表格    │
│  支持: 阿里/腾讯/字节/快手/网易/美团/BOSS直聘/mokahr      │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  Python Agent                            │
│  每日定时查表格 → 筛选待跟进 → 发飞书交互卡片             │
│  周度 LLM 分析 → JD 技能提取 → 投递策略建议               │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   飞书生态                                │
│  多维表格(数据库) + 消息卡片(通知+交互) + 回调服务        │
└─────────────────────────────────────────────────────────┘
```

---

## 功能一览

### 插件侧
- 招聘官网职位详情页**一键抓取**：岗位名、公司名、JD、薪资、投递链接
- 智能提取 JD：自动识别 20+ 种「职位描述」「岗位职责」「任职要求」等标题变体
- 评分制岗位名提取：多源融合（JSON-LD / CSS 选择器 / 页面标题 / h1-h2）
- 内置 8 个主流招聘平台适配，BOSS直聘含 CSS 反爬干扰文字过滤
- 飞书**数据看板**：投递漏斗图、公司分布环形图、投递时间线

### Agent 侧
- **每日跟进提醒**：投递 ≥3 天未跟进的自动推送飞书卡片
- **交互按钮**：卡片内点「面试」「无反馈」「简历挂」，表格和卡片同步更新
- **面试日程提醒**：面试时间未来 1-2 天的自动推送提醒
- **数据统计**：投递总量 / 面试转化率 / 待跟进数
- **AI 归因分析**：每周 LLM 分析 JD 技能分布，输出投递策略建议

---

## 快速开始

### 1. 飞书准备

在飞书开放平台创建自建应用，开通以下权限并发布：

| 权限 | 用途 |
|---|---|
| `bitable:app` | 读写多维表格 |
| `im:message:send` | 发送消息卡片 |
| `im:message.p2p_msg:readonly` | 接收私聊消息（可选） |

新建一个多维表格，字段模板参见下方「表格字段」一节。

### 2. 加载 Chrome 插件

```
1. 打开 chrome://extensions/
2. 开启「开发者模式」
3. 「加载已解压的扩展程序」→ 选择本项目根目录
4. 打开任意招聘官网职位详情页，点击插件图标
```

### 3. 配置 Agent

```bash
cd agent
pip install -r requirements.txt
```

设置环境变量：

```bash
export FEISHU_APP_ID=cli_xxx
export FEISHU_APP_SECRET=xxx
export FEISHU_APP_TOKEN=Rcifxxx      # 多维表格 Base Token
export FEISHU_TABLE_ID=tblxxx        # 表格 ID
export FEISHU_RECEIVER_ID=ou_xxx     # 你的飞书 open_id
export LLM_API_KEY=sk-xxx            # LLM API Key（BYOK）
export LLM_API_BASE=https://api.openai.com/v1
export LLM_MODEL=gpt-4o
```

运行：

```bash
python agent.py           # 执行投递追踪
python agent.py --analyze # LLM 归因分析
python agent.py --full    # 全部执行
```

### 4. 定时运行（GitHub Actions）

在 GitHub 仓库 Settings → Secrets 中添加上述环境变量，Agent 每天 9:00 自动执行。

---

## 飞书表格字段

| 字段 | 类型 | 说明 |
|---|---|---|
| 岗位 | 文本 | 插件自动抓取 |
| 公司 | 文本 | 插件自动抓取 |
| 薪资 | 文本 | BOSS直聘自动抓取 |
| 岗位JD | 文本 | 自动提取职责+要求段落 |
| 投递链接 | URL | 当前页 URL |
| 投递时间 | 日期 | 手动填写 |
| 结果 | 单选 | 简历 / 面试 / offer！/ 简历挂 / 一面挂 / 二面挂 / 无反馈 |
| 提醒状态 | 单选 | 待跟进 / 已跟进 / 已失效 / 有反馈 |
| 投递天数 | 公式 | `DAYS(TODAY(), {投递时间})` |
| 消息ID | 文本 | Agent 自动写入，回调时读取 |
| 面试时间 | 日期 | 面试提醒用 |
| 来源平台 | 单选 | 官网 / Boss直聘 / 牛客 / 实习僧 |

---

## 支持平台

| 平台 | 网址 |
|---|---|
| 阿里巴巴 | talent.alibaba.com |
| 腾讯 | join.qq.com |
| 字节跳动 | jobs.bytedance.com |
| 快手 | zhaopin.kuaishou.cn |
| 网易 | hr.163.com |
| 美团 | zhaopin.meituan.com |
| BOSS直聘 | zhipin.com |
| mokahr 系 | *.mokahr.com（小米/OPPO/vivo/滴滴/京东等） |

---

## 项目结构

```
JobPulse_Extension/
├── manifest.json           # Chrome Extension Manifest V3
├── popup.html              # 弹窗 UI
├── popup.js                # 核心抓取 + 飞书写入逻辑
├── dashboard.html          # 数据看板页面
├── dashboard.js            # 看板数据拉取 + Chart.js 渲染
├── chart.umd.min.js        # Chart.js 本地依赖
├── CLAUDE.md               # AI 协作指南
│
├── agent/                  # Python Agent
│   ├── agent.py            # 主入口：追踪 & 归因分析
│   ├── feishu.py           # 飞书 API 客户端
│   ├── cards.py            # 消息卡片模板
│   ├── config.py           # 配置（环境变量覆盖）
│   ├── llm_client.py       # LLM 客户端（OpenAI / Claude 兼容）
│   ├── callback_server.py  # 卡片按钮回调服务（Flask）
│   └── requirements.txt
│
└── .github/workflows/
    └── agent.yml           # GitHub Actions 每日定时
```

---

## 技术栈

| 层 | 技术 |
|---|---|
| 插件 | Chrome Extension Manifest V3 · Vanilla JS |
| Agent | Python 3.11 · Flask · requests |
| AI | BYOK — 支持 OpenAI / Claude / DeepSeek 等兼容 API |
| 存储 & 通知 | 飞书多维表格 + 飞书消息卡片 |
| 看板 | Chart.js 4 |
| 部署 | Render.com + GitHub Actions |

---

## 开发方式

本项目完全由 **Claude Code** 辅助开发，从需求定义、技术选型、代码实现到产品闭环全程 AI 协作。

详细的开发历程、踩坑记录和产品决策见：
- [CHANGELOG.md](./CHANGELOG.md) — 版本迭代日志
- [PROJECT_REVIEW.md](./PROJECT_REVIEW.md) — 项目复盘文档（PM 视角）

---

## 已知限制

- Chrome 插件需开发者模式加载，未上架 Chrome Web Store
- 飞书自建应用权限开通后需**发布新版本**才生效
- 卡片交互按钮需部署回调服务接收飞书 webhook（默认使用 Render.com 免费计划）
- React SPA 页面（如快手）内容可能动态渲染，匹配率不如传统页面

---

## License

MIT
