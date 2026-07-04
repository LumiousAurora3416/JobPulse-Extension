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
- **飞书私聊机器人**：自然语言对话查投递、记面试时间、更新状态

全程零成本，不需要自建服务器。

---

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                   Chrome 插件                             │
│  招聘官网 → 一键抓取(岗位/公司/JD/薪资) → 飞书多维表格    │
│  支持: 阿里/腾讯/字节/快手/网易/美团/BOSS直聘/mokahr      │
│  配置: 插件内 setup 页面 → chrome.storage.local          │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  Python Agent                            │
│  每日定时查表格 → 筛选待跟进 → 发飞书交互卡片             │
│  周度 LLM 分析 → JD 技能提取 → 投递策略建议               │
│  配置: 环境变量注入 (config.py)                           │
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

### 机器人对话
- 查进度：「字节怎么样了」
- 记面试：「字节周三下午两点面试」
- 改状态：「腾讯有反馈了」
- 录投递：「投了字节前端」
- 统计：「投递统计」

---

## 快速开始

### 你需要准备

| 资源 | 获取方式 | 用途 |
|---|---|---|
| 飞书自建应用 | [飞书开放平台](https://open.feishu.cn/app) 创建 | 调用飞书 API |
| App ID / App Secret | 应用 → 凭证与基础信息 | 应用身份认证 |
| 飞书多维表格 | 新建一个 Base | 存储投递数据 |
| Base Token / Table ID | 表格 URL 中提取 | API 定位表格 |
| LLM API Key | DeepSeek / OpenAI 等 | Agent AI 能力（可选） |

### 1. Chrome 插件

```bash
# 下载代码
git clone https://github.com/LumiousAurora3416/JobPulse-Extension.git
```

```
1. 打开 chrome://extensions/
2. 开启「开发者模式」
3. 「加载已解压的扩展程序」→ 选择项目根目录
4. 点击插件图标 → 点「打开配置页面」
5. 填入你的 App ID / App Secret / Base Token / Table ID
6. 保存后，去任意招聘官网职位详情页，点击插件抓取
```

> 凭证仅保存在本地浏览器 `chrome.storage.local` 中，不会上传任何地方。

### 2. 飞书多维表格

按以下字段模板创建表格（字段名必须完全一致）：

| 字段 | 类型 | 说明 |
|---|---|---|
| 岗位 | 文本 | 插件自动抓取 |
| 公司 | 文本 | 插件自动抓取 |
| 薪资 | 文本 | BOSS直聘自动抓取 |
| 岗位JD | 文本 | 自动提取职责+要求段落 |
| 投递链接 | URL | 当前页 URL |
| 投递时间 | 日期 | 插件写入 |
| 结果 | 单选 | 简历 / 面试 / 简历挂 / 无反馈 |
| 提醒状态 | 单选 | 待跟进 / 已跟进 / 已失效 / 有反馈 |
| 投递天数 | 公式 | `DAYS(TODAY(), {投递时间})` |
| 消息ID | 文本 | Agent 自动写入 |
| 面试时间 | 日期 | Agent 写入或手动填写 |
| 来源平台 | 单选 | 官网 / Boss直聘 / 牛客 / 实习僧 |

在飞书开放平台为应用开通 `bitable:app` 权限并发布，然后将应用添加到多维表格的协作者中。

### 3. Agent 后端（可选）

需要 Python 3.11+：

```bash
cd agent
pip install -r requirements.txt
```

设置环境变量：

```bash
export FEISHU_APP_ID=cli_xxx
export FEISHU_APP_SECRET=xxx
export FEISHU_APP_TOKEN=Rcifxxx
export FEISHU_TABLE_ID=tblxxx
export FEISHU_RECEIVER_ID=ou_xxx     # 你的飞书 open_id
export LLM_API_KEY=sk-xxx            # LLM API Key（BYOK）
export LLM_API_BASE=https://api.openai.com/v1
export LLM_MODEL=gpt-4o
```

运行：

```bash
python agent.py           # 每日跟进提醒
python agent.py --analyze # LLM 归因分析
python agent.py --full    # 全部执行
```

### 4. 定时运行（可选）

在 GitHub 仓库 Settings → Secrets 中添加上述环境变量，启用 `.github/workflows/agent.yml`，Agent 每天 9:00 自动执行。

### 5. 回调服务 + 飞书机器人对话（可选）

```bash
cd agent
pip install flask gunicorn
python callback_server.py  # 启动回调服务
```

部署到 Render.com 或使用 ngrok 暴露公网地址，然后在飞书开放平台配置：
- 消息卡片 → 回调地址
- 事件订阅 → `im.message.receive_v1`

---

## 快速体验

如果你有 AI 编程助手（Claude Code / Cursor 等），把项目丢给它，说一句"帮我部署这个项目"，它就能引导你完成全部配置。

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
├── popup.html / popup.js   # 弹窗 UI + 核心抓取逻辑
├── setup.html / setup.js   # 配置页（填飞书凭证）
├── dashboard.html / .js    # 数据看板
├── chart.umd.min.js        # Chart.js 本地依赖
│
├── agent/                  # Python Agent
│   ├── agent.py            # 主入口：追踪 & 归因分析
│   ├── feishu.py           # 飞书 API 客户端
│   ├── cards.py            # 消息卡片模板
│   ├── config.py           # 配置（环境变量覆盖）
│   ├── llm_client.py       # LLM 客户端
│   ├── callback_server.py  # 卡片回调服务
│   ├── message_agent.py    # 机器人对话处理
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
| AI | BYOK — 支持 OpenAI / Claude / DeepSeek 等 |
| 存储 & 通知 | 飞书多维表格 + 飞书消息卡片 |
| 看板 | Chart.js 4 |
| 部署 | Render.com + GitHub Actions |

---

## 开发方式

本项目由 **Claude Code** 辅助开发，从需求定义、技术选型、代码实现到产品闭环全程 AI 协作。详细的开发历程和踩坑记录见 [CHANGELOG.md](./CHANGELOG.md)。

---

## Known Limits

- Chrome 插件需开发者模式加载，未上架 Chrome Web Store
- 飞书自建应用权限开通后需**发布新版本**才生效
- 卡片交互按钮需部署回调服务接收飞书 webhook
- React SPA 页面（如快手）内容可能动态渲染，匹配率不如传统页面

---

## License

MIT
