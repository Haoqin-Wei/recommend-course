# skill/answer_generator.py
#
# 对应 SKILL.md：Step 4 —— 整理信息，进行回答
#
# 职责：
#   将 query_layer 返回的结构化数据，按 SKILL.md Step 4 定义的
#   回答结构和整理原则，转化为面向用户的自然语言回答。
#
# 核心规则（直接来自 SKILL.md，不做修改）：
#
#   推荐与整理原则（6 条）：
#     1. 优先推荐更符合用户目标的课程
#     2. 优先推荐相对简单、口碑较好、时间合适的课程
#     3. 同一门课多教授时，展示 RMP 更高的，保留 top 3
#     4. 高匹配课程与已选课程冲突时，必须明确提示
#     5. 与用户历史高意向/核心专业/毕业规划冲突，要重点提示
#     6. 最优选有明显冲突时，给出次优但更可执行的备选
#
#   回答结构（个性化推荐时）：
#     1. 先给结论（1~3 门课）
#     2. 再给理由（每项 1~3 句）
#     3. 再给风险提醒
#     4. 必要时给备选方案
#     5. 最后给 follow-up 问题（由 followup_generator 提供）
#
#   结果为空时的处理：
#     - 明确告知没有完全匹配的结果
#     - 说明可能原因
#     - 给出 1~2 个放宽建议
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field
from typing import Optional

from query.query_layer import QueryResult
from state.user_context import UserContext, QueryMode
from router.intent_classifier import CourseIntent


@dataclass
class AnswerPayload:
    """
    生成的回答结构，对应 SKILL.md Step 4 中的输出要求。
    """
    text: str
    # 给用户的自然语言回答（主体）

    conclusion: list[str] = field(default_factory=list)
    # 最终推荐的课程 ID 列表（结论部分）

    warnings: list[str] = field(default_factory=list)
    # 所有风险提示（时间冲突、先修不足、学分压力等）

    fallback_suggestions: list[str] = field(default_factory=list)
    # 备选方案课程 ID 列表

    ui_payload: Optional[dict] = None
    # 预留给前端 a2ui 卡片渲染的结构化数据
    # TODO: 当前 demo 不渲染，只填充结构
    # 格式: {"cards": [{"course_id": ..., "title": ..., "sections": [...]}]}


def generate_answer(
    query_result: QueryResult,
    context: UserContext,
    followups: list[str],
) -> AnswerPayload:
    """
    根据查询结果、用户上下文、follow-up 问题，生成结构化回答。

    Args:
        query_result: query_layer 返回的查询结果。
        context:      当前用户上下文。
        followups:    由 followup_generator 提供的 2~3 个后续问题。

    Returns:
        AnswerPayload: 完整回答结构。

    分发逻辑：
        - 结果为空 → handle_empty_result()
        - 单点查询 → generate_point_query_answer()
        - 个性化推荐 → generate_recommendation_answer()
    """

    if query_result.is_empty:
        return handle_empty_result(query_result, context, followups)

    if query_result.query_mode == QueryMode.POINT_QUERY:
        return generate_point_query_answer(query_result, context, followups)

    return generate_recommendation_answer(query_result, context, followups)


# ─────────────────────────────────────────────────────────────────────────────
# 个性化推荐回答（来自 SKILL.md Step 4 + 特殊要求 - 答案结构）
# ─────────────────────────────────────────────────────────────────────────────

def generate_recommendation_answer(
    query_result: QueryResult,
    context: UserContext,
    followups: list[str],
) -> AnswerPayload:
    """
    生成个性化推荐类回答，严格遵循 SKILL.md 的 5 步回答结构：
    结论 → 理由 → 风险 → 备选 → follow-up

    Args:
        query_result: 包含 FilteredResult 的查询结果。
        context:      用户上下文。
        followups:    2~3 个后续问题。

    Returns:
        AnswerPayload

    TODO: 实现以下各部分的自然语言生成逻辑：
        - 结论部分：从 primary 中选 top 1~3，说明选取依据
        - 理由部分：为每门课生成 1~3 句推荐理由
          （来自 SKILL.md：为什么适合这个专业/目标、为什么相对简单/评分高/时间合适）
        - 风险提醒：汇总所有 warnings
        - 备选方案：从 fallback 中选取
        - follow-up：拼接 followups
    """

    if not query_result.filtered:
        return AnswerPayload(text="[TODO] 推荐结果为空，无法生成回答。")

    primary  = query_result.filtered.primary
    fallback = query_result.filtered.fallback

    # ── 1. 结论（top 1~3 主推荐）───────────────────────────────────────────
    # TODO: 按 SKILL.md 整理原则排序（符合目标 > 简单 > 口碑好 > 时间合适）
    top_courses = primary[:3]  # 暂取前 3，排序逻辑待实现
    conclusion_ids = [entry["course"].course_id for entry in top_courses]

    conclusion_text = _format_conclusion(top_courses)

    # ── 2. 理由────────────────────────────────────────────────────────────────
    # TODO: 为每门课生成推荐理由
    reason_text = _format_reasons(top_courses, context)

    # ── 3. 风险提醒────────────────────────────────────────────────────────────
    all_warnings = []
    for entry in top_courses:
        all_warnings.extend(entry.get("warnings", []))
    # SKILL.md 规则 4/5：冲突必须明确提示
    warning_text = _format_warnings(all_warnings)

    # ── 4. 备选方案────────────────────────────────────────────────────────────
    fallback_ids = [entry["course"].course_id for entry in fallback[:2]]
    fallback_text = _format_fallback(fallback[:2]) if fallback else ""

    # ── 5. Follow-up 问题────────────────────────────────────────────────────
    followup_text = _format_followups(followups)

    # ── 拼接完整回答────────────────────────────────────────────────────────
    parts = [p for p in [conclusion_text, reason_text, warning_text, fallback_text, followup_text] if p]
    full_text = "\n\n".join(parts)

    # ── UI Payload（a2ui 卡片，demo 阶段只填充不渲染）──────────────────────
    # TODO: 当前只填充占位结构，前端接入时完善
    ui_payload = {
        "cards": [
            {
                "course_id": entry["course"].course_id,
                "title": entry["course"].title,
                "sections": [
                    {"section_id": s.section_id, "instructor": s.instructor,
                     "time": f"{s.meeting_days} {s.meeting_time}"}
                    for s in entry.get("sections", [])
                ],
                "warnings": entry.get("warnings", []),
            }
            for entry in top_courses
        ]
    }

    return AnswerPayload(
        text=full_text,
        conclusion=conclusion_ids,
        warnings=all_warnings,
        fallback_suggestions=fallback_ids,
        ui_payload=ui_payload,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 单点查询回答（来自 SKILL.md 特殊要求 - 单点查询的特殊处理）
# ─────────────────────────────────────────────────────────────────────────────

def generate_point_query_answer(
    query_result: QueryResult,
    context: UserContext,
    followups: list[str],
) -> AnswerPayload:
    """
    生成单点查询类回答。
    SKILL.md: "此时不要求完整收集用户画像，只需调用对应数据工具并简洁作答。"

    TODO: 根据不同 intent 生成对应的简洁回答。
    """
    raw = query_result.raw_data or {}
    intent = query_result.intent

    if intent == CourseIntent.PREREQUISITE_CHECK:
        # TODO: 生成先修查询的自然语言回答
        text = _format_prerequisite_answer(raw)

    elif intent == CourseIntent.PROFESSOR_REVIEW:
        # TODO: 生成教授评分的自然语言回答
        text = _format_professor_answer(raw)

    elif intent == CourseIntent.GRADE_DISTRIBUTION:
        # TODO: 生成给分率的自然语言回答
        text = _format_grade_answer(raw)

    elif intent == CourseIntent.SCHEDULE_CONFLICT:
        # TODO: 生成时间冲突的自然语言回答
        text = _format_schedule_answer(raw)

    elif intent == CourseIntent.GE_REQUIREMENT:
        # TODO: 生成 GE 要求的自然语言回答
        text = _format_ge_answer(raw)

    else:
        text = "[TODO] 未识别的单点查询类型。"

    followup_text = _format_followups(followups)
    full_text = "\n\n".join([t for t in [text, followup_text] if t])

    return AnswerPayload(text=full_text)


# ─────────────────────────────────────────────────────────────────────────────
# 结果为空时的处理（来自 SKILL.md 特殊要求 - 结果为空时的处理）
# ─────────────────────────────────────────────────────────────────────────────

def handle_empty_result(
    query_result: QueryResult,
    context: UserContext,
    followups: list[str],
) -> AnswerPayload:
    """
    SKILL.md: 结果为空时，不能只回答"没有结果"，需要：
      1. 明确告知没有完全匹配结果
      2. 说明可能原因（来自 query_result.empty_reason）
      3. 给出 1~2 个放宽建议

    TODO: 实现放宽建议的生成逻辑。
    SKILL.md 中给出的放宽方向：
      - 放宽时间段
      - 放宽教授偏好
      - 接受中等难度课程
      - 扩大到相近领域课程
    """

    # TODO: 根据 context 和 empty_reason 生成有针对性的放宽建议
    relax_suggestions = [
        "可以尝试放宽时间偏好，查看更多可用的 section。",
        "可以考虑接受不同教授的课程，部分教授评分也很不错。",
        # TODO: 根据具体情况动态生成更有针对性的建议
    ]

    text_parts = [
        f"当前没有找到完全符合条件的课程。",
        f"可能原因：{query_result.empty_reason}" if query_result.empty_reason else "",
        "你可以考虑：\n" + "\n".join(f"- {s}" for s in relax_suggestions),
    ]
    full_text = "\n".join([p for p in text_parts if p])

    followup_text = _format_followups(followups)
    if followup_text:
        full_text += "\n\n" + followup_text

    return AnswerPayload(text=full_text)


# ─────────────────────────────────────────────────────────────────────────────
# 格式化辅助函数（TODO: 由开发者实现自然语言生成）
# ─────────────────────────────────────────────────────────────────────────────

def _format_conclusion(top_courses: list[dict]) -> str:
    # TODO: 生成结论段落（"最推荐以下课程：..."）
    if not top_courses:
        return ""
    names = [f"{e['course'].course_id} {e['course'].title}" for e in top_courses]
    return "**推荐课程：**\n" + "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))


def _format_reasons(top_courses: list[dict], context: UserContext) -> str:
    # TODO: 为每门课生成推荐理由
    # 来自 SKILL.md：适合专业/目标、简单/评分高/时间合适、先修满足
    return "[TODO] 推荐理由生成逻辑尚未实现。"


def _format_warnings(warnings: list[str]) -> str:
    if not warnings:
        return ""
    return "**注意事项：**\n" + "\n".join(warnings)


def _format_fallback(fallback: list[dict]) -> str:
    if not fallback:
        return ""
    # TODO: 生成备选方案说明
    names = [f"{e['course'].course_id} {e['course'].title}" for e in fallback]
    return "**备选方案：**\n" + "\n".join(f"- {n}（{e['reason']}）" for n, e in zip(names, fallback))


def _format_followups(followups: list[str]) -> str:
    if not followups:
        return ""
    return "\n".join(f"- {q}" for q in followups)


def _format_prerequisite_answer(raw: dict) -> str:
    # TODO: 实现先修查询的自然语言格式化
    return f"[TODO] course={raw.get('course_id')} prereqs={raw.get('prerequisites')} unmet={raw.get('unmet')}"


def _format_professor_answer(raw: dict) -> str:
    # TODO: 实现教授评分的自然语言格式化
    return f"[TODO] professor ratings: {[r.name for r in raw.get('ratings', [])]}"


def _format_grade_answer(raw: dict) -> str:
    # TODO: 实现给分率的自然语言格式化
    return f"[TODO] grade distributions: {len(raw.get('distributions', []))} records"


def _format_schedule_answer(raw: dict) -> str:
    # TODO: 实现时间冲突的自然语言格式化
    return f"[TODO] schedule sections: {len(raw.get('sections', []))} sections"


def _format_ge_answer(raw: dict) -> str:
    # TODO: 实现 GE 要求的自然语言格式化
    return f"[TODO] GE courses: {len(raw.get('ge_courses', []))} courses"
