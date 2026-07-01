# Changelog

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
