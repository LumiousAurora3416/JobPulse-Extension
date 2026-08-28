# Changelog

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
