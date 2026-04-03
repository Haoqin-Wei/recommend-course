# SKILL.md → 代码模块映射说明

## 一、SKILL.md 核心处理阶段拆解

SKILL.md 中定义了以下明确阶段：

| SKILL.md 阶段       | 阶段描述                            | 关键判断/操作                                      |
|--------------------|-----------------------------------|--------------------------------------------------|
| 触发 / 不触发判断    | 判断用户输入是否属于选课范畴            | 触发条件 + 不触发条件（已在 SKILL.md 中完整定义）     |
| Step 1：获取关键信息 | 收集学期、专业、已选课、偏好等字段        | 判断是"单点查询"还是"个性化推荐"，信息是否充足         |
| Step 2：澄清        | 关键信息不足时，向用户追问最小必要信息    | 每次只追问 1~3 个最关键缺失项                        |
| Step 3：检索知识库   | 按问题类型调用对应工具查询数据           | 6 类数据来源，5 条推荐过滤限制条件                    |
| Step 4：整理 + 回答  | 对结果排序、整理，按结构化模板输出回答    | 结论 → 理由 → 风险 → 备选 → follow-up              |
| Step 5：推荐问       | 给出 2~3 个自然的后续引导问题          | 方向：缩小范围、比较、冲突检查、偏好优化               |

---

## 二、阶段 → 模块映射

```
SKILL.md 阶段                    →    Python 模块
─────────────────────────────────────────────────────────────────
触发/不触发判断                  →    router/intent_classifier.py
                                      router/skill_gate.py

Step 1：获取关键信息              →    state/user_context.py         (UserContext 数据结构)
        判断信息充足性             →    skill/context_checker.py      (is_context_sufficient)
        单点查询 vs 个性化推荐      →    router/intent_classifier.py   (classify_query_mode)

Step 2：澄清                     →    skill/clarifier.py             (generate_clarification)

Step 3：检索知识库                →    query/query_layer.py          (统一查询入口)
        6 类数据工具              →    tools/mock_tools.py           (全部用 mock 实现)
        5 条过滤限制              →    query/filter.py               (apply_filters)

Step 4：整理 + 回答              →    skill/answer_generator.py     (generate_answer)
        结果为空时的处理           →    skill/answer_generator.py     (handle_empty_result)

Step 5：推荐问                   →    skill/followup_generator.py   (generate_followups)

整体 5-step 编排                 →    skill/course_skill.py         (run_skill_pipeline)

Demo 入口                        →    main.py
```

---

## 三、demo 阶段暂缓的部分

以下内容在 SKILL.md 中有提及，但在初版 demo 中暂不实现：

| SKILL.md 内容              | demo 处理方式              |
|---------------------------|--------------------------|
| 真实 tool 调用（WebSoc、RMP、Zotistics 等） | 全部替换为 mock_tools.py 中的 mock 数据 |
| a2ui 前端卡片 / 动态课表联动  | 在 answer_generator 中预留 `ui_payload` 字段，不渲染 |
| 学分限制检查                | TODO 占位                 |
| GE / major requirement 检查 | TODO 占位                 |
| 多 agent / agentic 框架     | 暂不引入                  |
| 记忆压缩                    | 暂不实现                  |
