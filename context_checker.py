# skill/context_checker.py
#
# 对应 SKILL.md：Step 1 末尾的"信息充足性判断"
#
# 职责：
#   根据 query_mode，判断当前 UserContext 中的信息是否足以进入 Step 3（检索）。
#   如果不足，返回缺失字段列表，交由 clarifier.py 生成追问。
#
# 来源规则（SKILL.md Step 1）：
#   - 单点查询：不必强求所有字段完整，可直接进入 Step 3
#   - 个性化推荐：至少需要 term、major、selected_courses；
#     若涉及时间安排还需要 preferred_time
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass
from state.user_context import UserContext, QueryMode


@dataclass
class SufficiencyResult:
    """
    信息充足性检查结果。
    """
    is_sufficient: bool
    missing_fields: list[str]
    # 缺失字段列表，字段名对应 UserContext 中的属性名
    # 例如: ["term", "major", "selected_courses"]
    # 用于 clarifier 决定优先追问哪些字段

    hint: str = ""
    # 给 clarifier 的额外提示，说明为什么缺失这些字段
    # 例如: "用户问题涉及时间排课，需要 preferred_time"


def check_context_sufficiency(
    context: UserContext,
    query_mode: QueryMode,
    intent: str,
) -> SufficiencyResult:
    """
    检查当前 UserContext 是否满足进入 Step 3 的最低信息要求。

    Args:
        context:    当前用户上下文（可能含 None 字段）。
        query_mode: 问题类型，POINT_QUERY 或 PERSONALIZED。
        intent:     子意图类型，用于判断是否涉及时间排课等特殊需求。

    Returns:
        SufficiencyResult:
            is_sufficient=True  → 信息充足，直接进入 Step 3
            is_sufficient=False → 信息不足，missing_fields 指出缺失项

    规则来源（SKILL.md Step 1）：

        单点查询（POINT_QUERY）：
            → 不强求完整字段，直接返回 is_sufficient=True
            → TODO: 是否有例外？例如先修判断是否需要 completed_courses？

        个性化推荐（PERSONALIZED）：
            必须字段: term, major, selected_courses
            → 若缺少任一，返回 is_sufficient=False

            可选但情境相关：
            → 若 intent == "schedule_conflict" 或 recommendation_goal 涉及时间：
              还需要 preferred_time
            → TODO: 其他情境相关字段的判断规则由开发者补充

        澄清优先级对应 SKILL.md Step 2 中的追问优先级顺序：
            1. term
            2. major
            3. selected_courses
            4. recommendation_goal（推荐场景）
            5. preferred_time（时间排课场景）
    """

    # 单点查询：信息要求宽松，直接放行
    if query_mode == QueryMode.POINT_QUERY:
        # TODO: 评估单点查询是否有最低字段要求（如先修判断是否需要 completed_courses）
        return SufficiencyResult(is_sufficient=True, missing_fields=[])

    # 个性化推荐：检查必须字段
    missing: list[str] = []

    # 按 SKILL.md Step 2 澄清优先级顺序检查
    if not context.term:
        missing.append("term")
    if not context.major:
        missing.append("major")
    if not context.selected_courses:
        missing.append("selected_courses")

    # 情境相关字段
    # TODO: 判断当前 intent 是否涉及时间排课，若是则检查 preferred_time
    # if intent == "schedule_conflict" and not context.preferred_time:
    #     missing.append("preferred_time")

    # TODO: 判断是否需要 recommendation_goal（如用户明确在问"推荐"）
    # if intent == "recommendation" and not context.recommendation_goal:
    #     missing.append("recommendation_goal")

    if missing:
        return SufficiencyResult(
            is_sufficient=False,
            missing_fields=missing,
            hint=f"个性化推荐模式下缺少以下字段: {missing}",
        )

    return SufficiencyResult(is_sufficient=True, missing_fields=[])
