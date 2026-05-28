# UCI Course Advisor — ROADMAP

> 下一阶段的开发按本文件从上往下执行。
> 顶部是 v1.0 测试反馈的 8 项改进（按优先级排），下面是更长期的版本规划。

---

## 当前版本 v1.0 状态

**已完成**
- FastAPI 后端 + 单页前端（[static/index.html](static/index.html)）
- Agent loop 工具调用 + SSE 流式输出（[app/agent/loop.py](app/agent/loop.py)）
- 工具层：course / sections / professor / grade distribution / prerequisite（[app/agent/tools.py](app/agent/tools.py)）
- 数据层 DB-first → Anteater API 回退（[app/data/db.py](app/data/db.py)、[app/data/anteater.py](app/data/anteater.py)）
- Catalog 缓存 + 校验框架（[app/catalog/](app/catalog/)、[app/validation/](app/validation/)）
- 多会话 + 记忆系统（[app/memory/](app/memory/)、[app/routers/sessions.py](app/routers/sessions.py)）
- Skill-style intent → clarification → query → answer → follow-up 流水线（[app/modules/](app/modules/)）

**已知瓶颈**
1. 数据只有 `spring_sections_relational.xlsx` 一份，多学期 / 历史数据未入库
2. 前端 [static/index.html](static/index.html) 单文件 3147 行
3. 无用户认证，pending schedule 仅会话内
4. 无自动化测试（只有 `scripts/smoke_test.py` 等手动脚本）
5. 无部署配置（Dockerfile、CI、生产配置缺失）

---

## v1.0 → v1.1：测试反馈 8 项（按优先级执行）

| 优先级 | 项 | 工作量 | 说明 |
|---|---|---|---|
| 🔴 P0 | ⑦ Max tool call + 错误降级 | 1h | 防 demo 翻车，立刻做 |
| 🔴 P0 | ⑥ 删除 keyword extraction | 1h | 清旧代码债，配合 Agent Loop 落地 |
| 🟡 P1 | ① 首次登录引导 | 2-3h | 用户体验起点 |
| 🟡 P1 | ⑤ 表格可点选 | 2h | UX 提升肉眼可见 |
| 🟡 P1 | ③ 记忆 fallback / 主动维护 | 3-4h | 工程亮点 |
| 🟢 P2 | ④ 联网搜索补教授信息 | 2h | 需要 search API |
| 🟢 P2 | ⑧ 每个选课季前更新数据 | 1h 脚本 + 长期维护 | 周期任务 |
| 🟣 P3 | ② AI 学习用户行为（协同过滤） | 1-2 周 | 等真实用户数据积累，**放到 v2.0** |

---

### 🔴 P0-1 ⑦ Max tool call + 错误降级

**现状**：[app/agent/loop.py](app/agent/loop.py) 已有 `MAX_ITERATIONS=6` 和 `MAX_TOTAL_TOOLS=12`，但触发后只是 `error` 事件，没有用户友好降级。单个 tool 失败时也没有 fallback 链路。

**目标**
- [ ] 每个 tool dispatcher 包一层 try/except，失败返回结构化 `{found: false, reason: "..."}` 而不是抛错
- [ ] Loop 达到 MAX 时优雅收尾：让 LLM 用已有信息给一个"尽力而为"的回答，而不是直接 error
- [ ] 前端收到 `error` 事件时显示友好提示，不是空白

**涉及文件**：[app/agent/loop.py](app/agent/loop.py)、[app/agent/tools.py](app/agent/tools.py)、[static/index.html](static/index.html)

**验收**：手动断网 + 故意触发限制，用户看到的不应是 500 或空白。

---

### 🔴 P0-2 ⑥ 删除 keyword extraction

**现状**：Agent Loop + Tool System 上线后，LLM 自己从原文抽实体；前置 keyword 步骤变成冗余 + 噪声源。

**目标**
- [ ] 审查 [app/modules/query.py](app/modules/query.py)、[app/modules/intent.py](app/modules/intent.py) 中 keyword 相关代码
- [ ] 确认 chat 路由不再依赖 keyword 后整段删除（不是注释掉）
- [ ] 跑一遍 `scripts/smoke_test.py` 确认无回归

**涉及文件**：[app/modules/query.py](app/modules/query.py)、[app/modules/intent.py](app/modules/intent.py)、[app/routers/chat.py](app/routers/chat.py)

**验收**：grep `keyword` 在 app/ 下没有遗留引用；smoke test 通过。

---

### 🟡 P1-1 ① 前端首次登录引导

**现状**：新用户直接进 chat，无 profile，LLM 第一句回答没法个性化。

**目标**
- [ ] 新会话首次打开时检测 profile 是否为空
- [ ] 弹出引导卡片收集：**专业 / 学院 / 年级 / 当前学期**（最小集，不要一次问太多）
- [ ] 填写后写入 memory（[app/memory/](app/memory/)），后续对话直接用
- [ ] 提供"跳过"按钮，但跳过的用户在第一条消息后再温和追问一次

**涉及文件**：[static/index.html](static/index.html)、[app/routers/memory.py](app/routers/memory.py)、[app/memory/manager.py](app/memory/manager.py)

**验收**：清空 memory 后打开页面 → 看到引导 → 填完 → 问"推荐一门课" → LLM 回答里要引用刚填的专业。

---

### 🟡 P1-2 ⑤ 聊天表格 → 可点选

**现状**：LLM 输出的课程表格只能看，用户得手动打字"我选第二个"。

**目标**
- [ ] 前端解析 assistant message 里的 markdown 表格，给每行加点击区
- [ ] 点击行 → 自动发送一条结构化消息（如"我想选 CS122A"）或直接调用 add-to-schedule
- [ ] 表格行 hover 状态 + 已选标识
- [ ] 与现有 follow-up chip 系统视觉风格统一

**涉及文件**：[static/index.html](static/index.html) 单文件改

**验收**：在表格上点一行就能加进左侧 pending schedule。

---

### 🟡 P1-3 ③ 记忆 fallback / 主动维护

**现状**：[app/memory/](app/memory/) 已有基础存储，但记忆无时间戳，无 staleness 检测，用户偏好长期错误也不会被察觉。

**目标**
- [ ] 每条 memory 加 `last_modified_at` + `last_confirmed_at` 字段（schema migration）
- [ ] 设定阈值（如 14 天）后，agent 在合适时机主动 double-check：
  - "你之前说想选早上课，现在还是吗？"
  - "记得你专业是 CS，本学期还是吗？"
- [ ] 用户输入与记忆冲突时优先信任新输入，并更新时间戳
- [ ] 提供 `/api/memory/review` 端点列出过期记忆（调试用）

**涉及文件**：[app/memory/base.py](app/memory/base.py)、[app/memory/json_provider.py](app/memory/json_provider.py)、[app/memory/manager.py](app/memory/manager.py)、新增迁移脚本到 [scripts/](scripts/)

**验收**：手动把某条 memory 的 `last_modified_at` 改到 30 天前 → 下一轮对话 agent 会主动确认。

---

### 🟢 P2-1 ④ 联网搜索补教授信息

**现状**：教授数据只有 RMP 静态 cache，没法覆盖 Reddit、学院公告、近期评价。

**目标**
- [ ] 新增 tool `web_search_professor(name)` 调用 search API（Brave / Tavily / SerpAPI 任选）
- [ ] 触发条件：用户问"XX 教授怎么样"且本地数据 ≤ N 条评价
- [ ] 结果过滤到信任域名（reddit.com/r/UCI、ratemyprofessors.com、官方域名）
- [ ] 加 in-memory cache 防重复请求

**涉及文件**：[app/agent/tools.py](app/agent/tools.py)、[app/data/professor_summary.py](app/data/professor_summary.py)

**验收**：问"Pattis 教授近年评价怎么样" → 工具调用日志能看到 web search → 答案里有非 RMP 信息源。

---

### 🟢 P2-2 ⑧ 每选课季前刷新数据

**目标**
- [ ] 写一个 `scripts/refresh_all.sh`，串联：
  - [scripts/fetch_uci_data.py](scripts/fetch_uci_data.py)
  - [scripts/import_term_data.py](scripts/import_term_data.py)
  - [scripts/import_professor_reviews.py](scripts/import_professor_reviews.py)
  - grades cache 重建
- [ ] README 里加触发说明：Fall / Winter / Spring / Summer 各一次
- [ ] （可选）GitHub Action cron 自动跑

**涉及文件**：新增 [scripts/refresh_all.sh](scripts/refresh_all.sh)、更新 [README.md](README.md)

**验收**：一条命令能把所有数据刷新到最新学期。

---

### 🟣 P3 ② AI 主动学习用户行为（协同过滤）

**为什么放后面**：协同过滤需要多个真实用户行为日志，demo 阶段只有 `demo_001` 一个用户，做不出来。

**前置条件**
- 至少有 50+ 真实用户使用过
- 行为日志 schema 设计好（query / 选课 / 否决 等动作 × user × timestamp）

**等部署上线积累数据后再启动，挪到 v2.0**。

---

## v1.x：数据底盘补齐（完成 8 项后）

> 现在 demo 能跑，但数据不够撑真实场景

- [ ] 多学期 WebSoc 数据落库（近 3 年 × Fall/Winter/Spring/Summer）
- [ ] 历史 grade distribution 全量抓取（[app/data/grades.py](app/data/grades.py) 已有 cache 层）
- [ ] 教授评价数据扩充（RMP + UCI eval），打通 [app/data/professor_summary.py](app/data/professor_summary.py)
- [ ] Major requirement 结构化（[scripts/scrape_major_requirements.py](scripts/scrape_major_requirements.py) 落地）
- [ ] GE 分类完整入库

---

## v2.0：Agent 能力深化

- [ ] ② **协同过滤推荐**（"同专业同学也在选这些课"）
- [ ] 真正的 prerequisite 图遍历（不是文本匹配）
- [ ] 排课冲突检测下沉到工具层（[app/modules/conflict.py](app/modules/conflict.py) 已有雏形）
- [ ] Pending schedule ↔ 后端状态双向同步
- [ ] Major / GE 满足度计算工具（transcript + requirement → 还差什么）
- [ ] Multi-quarter 规划（2-3 学期联动）
- [ ] Tool 调用预算 / 成本观测（token / latency 上报）

---

## v2.x：前端可维护性 + UX

- [ ] [static/index.html](static/index.html) 拆分（Vite + React/Vue/Svelte 任选）
- [ ] Schedule UI 升级：拖拽、冲突高亮、周视图
- [ ] 对话历史搜索 UI 入口
- [ ] 课程卡片组件化（a2ui 卡片落地）
- [ ] 移动端响应式

---

## v3.0：用户系统 + 个性化

- [ ] UCI SSO 或本地账号（目前只有匿名 user_id）
- [ ] 个人 transcript 上传 / 解析
- [ ] 长期 memory 跨会话沉淀
- [ ] 个性化偏好持久化（[scripts/migrate_preferences_schema.py](scripts/migrate_preferences_schema.py) 在动这块）

---

## v3.x：工程化 + 上线

- [ ] pytest 覆盖核心模块（intent / query / conflict / validation）
- [ ] Dockerfile + docker-compose
- [ ] GitHub Actions CI（lint + test + 数据抓取）
- [ ] DB 从 SQLite/CSV 迁到 Postgres
- [ ] 监控：请求日志 / LLM 调用日志 / 错误上报
- [ ] Rate limiting + API key 管理

---

## v4.0+：进阶能力

- [ ] 多人共享课表 / 同学之间对比
- [ ] Waitlist / 实时选课开放提醒
- [ ] Degree audit 自动生成
- [ ] 中英文双语界面
- [ ] 公开 API 给其他 UCI 工具用

---

## 进度记录

每完成一项请在对应 `[ ]` 打勾，并在下面记录日期 + commit。

- _待填_
