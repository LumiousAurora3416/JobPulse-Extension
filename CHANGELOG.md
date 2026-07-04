# Changelog

## v1.3.0 (2026-07-05)

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
