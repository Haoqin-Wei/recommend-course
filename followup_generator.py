# skill/followup_generator.py
#
# 对应 SKILL.md：Step 5 —— 给出推荐问
#
# 职责：
#   在每轮回答末尾，根据当前结果和上下文，生成 2~3 个自然的后续引导问题。
#
# 规则（直接来自 SKILL.md Step 5，不做修改）：
#   推荐 follow-up 方向：
#     - 进一步缩小范围
#     - 比较两个候选课程
#     - 检查时间冲突
#     - 检查是否满足 GE / major requirement
#     - 继续按用户偏好优化推荐
#
#   SKILL.md 示例：
#     "要不要我再帮你按'更容易拿高分'排序一次？"
#     "你想让我顺便检查一下这些课和你当前课表有没有冲突吗？"
#     "如果你更重视教授口碑，我也可以换一种标准再帮你筛一遍。"
# ─────────────────────────────────────────────────────────────────────────────

from query.query_layer import QueryResult
from state.user_context import UserContext, QueryMode
from router.intent_classifier import CourseIntent


# follow-up 问题候选模板（来自 SKILL.md Step 5 的方向和示例）
# TODO: 开发者可根据产品语调调整这些模板文本
_FOLLOWUP_TEMPLATES: dict[str, list[str]] = {
    "grade_sort": [
        "要不要我再帮你按"更容易拿高分"排序一次？",
    ],
    "conflict_check": [
        "你想让我顺便检查一下这些课和你当前课表有没有冲突吗？",
    ],
    "professor_sort": [
        "如果你更重视教授口碑，我也可以换一种标准再帮你筛一遍。",
    ],
    "narrow_down": [
        "要不要进一步缩小范围？比如只看周一三五的课？",
        "你对这几门课有具体偏好吗，比如时间段或者难度？",
    ],
    "compare": [
        "要不要我帮你详细比较一下这几门课的差别？",
    ],
    "ge_check": [
        "要不要我帮你确认一下这些课是否满足你的 GE 或专业要求？",
    ],
    "expand_search": [
        "如果这些课都不太合适，我可以帮你扩大搜索范围，你有其他偏好方向吗？",
    ],
}

# 每轮最多生成几个 follow-up 问题（来自 SKILL.md Step 5："给出 2~3 个"）
MAX_FOLLOWUPS = 3


def generate_followups(
    query_result: QueryResult,
    context: UserContext,
) -> list[str]:
    """
    根据当前查询结果和用户上下文，生成 2~3 个自然的后续引导问题。

    Args:
        query_result: 当前轮次的查询结果。
        context:      当前用户上下文。

    Returns:
        list[str]: 2~3 个 follow-up 问题文本列表。

    生成策略（来自 SKILL.md Step 5 的 5 个方向）：
        1. 优先推荐与当前结果最相关的后续方向
        2. 避免重复上一轮已经追问过的方向
        3. 总数控制在 2~3 个

    TODO: 当前使用规则模板，后续可替换为 LLM 动态生成（更自然）。
    """

    selected: list[str] = []

    # ── 判断哪些 follow-up 方向与当前结果相关 ─────────────────────────────────

    is_recommendation = query_result.intent == CourseIntent.RECOMMENDATION
    has_results = not query_result.is_empty
    has_warnings = (
        query_result.filtered is not None and
        any(e.get("warnings") for e in (query_result.filtered.primary or []))
    )

    # 方向 1：检查时间冲突（有推荐结果且用户还没检查过冲突时）
    # TODO: 判断条件：用户尚未提供 preferred_time 且当前是推荐模式
    if is_recommendation and has_results and not context.preferred_time:
        _pick_from(_FOLLOWUP_TEMPLATES["conflict_check"], selected)

    # 方向 2：按给分率重排（有推荐结果时）
    if is_recommendation and has_results:
        _pick_from(_FOLLOWUP_TEMPLATES["grade_sort"], selected)

    # 方向 3：按教授口碑重排（有推荐结果时）
    if is_recommendation and has_results and len(selected) < MAX_FOLLOWUPS:
        _pick_from(_FOLLOWUP_TEMPLATES["professor_sort"], selected)

    # 方向 4：缩小范围 / 比较
    if is_recommendation and has_results and len(selected) < MAX_FOLLOWUPS:
        _pick_from(_FOLLOWUP_TEMPLATES["narrow_down"], selected)

    # 方向 5：GE / 专业要求检查
    if len(selected) < MAX_FOLLOWUPS:
        _pick_from(_FOLLOWUP_TEMPLATES["ge_check"], selected)

    # 方向 6：扩大搜索（结果为空时）
    if query_result.is_empty:
        _pick_from(_FOLLOWUP_TEMPLATES["expand_search"], selected)

    # TODO: 单点查询的 follow-up 逻辑（SKILL.md: 单点查询基础上继续追问时进入完整流程）
    # 例如: 先修查询后，可引导"帮我推荐几门类似的课"

    return selected[:MAX_FOLLOWUPS]


def _pick_from(templates: list[str], selected: list[str]) -> None:
    """从模板列表中选一个未使用的问题加入 selected。"""
    for t in templates:
        if t not in selected:
            selected.append(t)
            return
