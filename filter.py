# query/filter.py
#
# 对应 SKILL.md：Step 3 中列出的 5 条推荐限制条件（过滤规则）
#
# 职责：
#   接收原始检索结果，应用 SKILL.md 中定义的 5 条过滤约束，
#   返回过滤后的主推荐列表和可作为备选的候补列表。
#
# 5 条过滤规则（直接来自 SKILL.md Step 3，不做修改）：
#   1. 已经选过或已修过的课程，不再重复推荐
#   2. 不满足先修条件的课程，默认不作为主推荐，可单独提示
#   3. 超出学分限制或明显增加负担的课程，要提示风险
#   4. 与当前课表时间冲突的课程，不作为主推荐，可作为备选
#   5. 如果用户明确给出偏好，优先按偏好过滤
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field
from tools.mock_tools import CourseInfo, SectionInfo
from state.user_context import UserContext


@dataclass
class FilteredResult:
    """
    过滤后的课程结果，区分主推荐和备选。
    """
    primary: list[dict]
    # 通过所有过滤条件的主推荐课程
    # 每项结构: {"course": CourseInfo, "sections": list[SectionInfo], "warnings": list[str]}

    fallback: list[dict]
    # 未通过某些过滤条件但可作为备选的课程
    # 每项结构: {"course": CourseInfo, "sections": list[SectionInfo],
    #             "reason": str, "warnings": list[str]}

    excluded: list[dict]
    # 完全排除的课程（已选过、已修过）
    # 每项结构: {"course_id": str, "reason": str}


def apply_filters(
    candidate_courses: list[CourseInfo],
    candidate_sections: list[SectionInfo],
    context: UserContext,
) -> FilteredResult:
    """
    对候选课程列表应用 SKILL.md Step 3 中定义的 5 条过滤规则。

    Args:
        candidate_courses:  从 query_layer 获取的原始候选课程列表。
        candidate_sections: 候选课程的 section 信息（用于时间冲突检查）。
        context:            当前用户上下文（包含已选课、已修课、偏好等）。

    Returns:
        FilteredResult: 分为主推荐、备选、完全排除三类。

    过滤规则实现（来自 SKILL.md Step 3）：
    """

    primary:  list[dict] = []
    fallback: list[dict] = []
    excluded: list[dict] = []

    for course in candidate_courses:

        # ── 规则 1：已选过或已修过 → 完全排除 ────────────────────────────────
        # SKILL.md: "已经选过或已经修过的课程，不再重复推荐"
        if (course.course_id in context.selected_courses or
                course.course_id in context.completed_courses):
            excluded.append({
                "course_id": course.course_id,
                "reason": "已选过或已修过",
            })
            continue

        warnings: list[str] = []
        is_fallback = False
        fallback_reason = ""

        # ── 规则 2：先修条件不满足 → 降为备选，附提示 ────────────────────────
        # SKILL.md: "不满足先修条件的课程，默认不作为主推荐，可单独提示"
        unmet_prereqs = _check_prerequisites(course, context)
        if unmet_prereqs:
            is_fallback = True
            fallback_reason = f"先修课未满足: {unmet_prereqs}"
            warnings.append(f"⚠️ 需要先修: {', '.join(unmet_prereqs)}")

        # ── 规则 3：学分负担 → 主推荐中附风险提示 ───────────────────────────
        # SKILL.md: "超出学分限制或明显增加负担的课程，要提示风险"
        credit_warning = _check_credit_burden(course, context)
        if credit_warning:
            warnings.append(f"⚠️ 学分提示: {credit_warning}")
        # TODO: 由开发者决定：学分超限是否导致降为备选，还是只提示？

        # ── 规则 4：时间冲突 → 降为备选 ──────────────────────────────────────
        # SKILL.md: "与当前课表时间冲突的课程，不作为主推荐，可作为备选"
        course_sections = [s for s in candidate_sections if s.course_id == course.course_id]
        conflict_sections, available_sections = _check_schedule_conflict(
            course_sections, context
        )
        if conflict_sections and not available_sections:
            # 所有 section 都冲突
            is_fallback = True
            fallback_reason = "所有 section 均与当前课表时间冲突"
            warnings.append("⚠️ 时间冲突: 当前无可选 section")
        elif conflict_sections:
            warnings.append(f"⚠️ 时间冲突: {len(conflict_sections)} 个 section 冲突，{len(available_sections)} 个可用")

        # ── 规则 5：用户偏好过滤 ──────────────────────────────────────────────
        # SKILL.md: "如果用户明确给出偏好，优先按偏好过滤"
        # TODO: 由开发者实现偏好过滤逻辑
        # 例如: 难度偏好、时间偏好、教授偏好
        # _apply_preference_filter(course, available_sections, context)

        # ── 分配到 primary 或 fallback ────────────────────────────────────────
        entry = {
            "course": course,
            "sections": available_sections if available_sections else course_sections,
            "warnings": warnings,
        }
        if is_fallback:
            fallback.append({**entry, "reason": fallback_reason})
        else:
            primary.append(entry)

    return FilteredResult(primary=primary, fallback=fallback, excluded=excluded)


# ─────────────────────────────────────────────────────────────────────────────
# 内部辅助函数（每条规则的具体实现）
# ─────────────────────────────────────────────────────────────────────────────

def _check_prerequisites(course: CourseInfo, context: UserContext) -> list[str]:
    """
    规则 2：检查用户是否满足先修条件。

    Returns:
        list[str]: 未满足的先修课 ID 列表。空列表表示先修条件满足。
    """
    return [
        prereq for prereq in course.prerequisites
        if prereq not in context.completed_courses
    ]


def _check_credit_burden(course: CourseInfo, context: UserContext) -> str:
    """
    规则 3：检查加选此课后的学分负担是否过重。

    Returns:
        str: 风险提示文本。空字符串表示无风险。

    TODO: 由开发者定义"学分上限"和"负担过重"的判断标准。
    例如：
        - UCI 全职学生一般选 12~16 学分
        - 超过 20 学分需要特别申请
        - 当前只有 selected_courses 列表，没有学分汇总，需要先查 catalog
    """

    # TODO: 实现学分负担检查逻辑
    # 当前占位：不检查，返回空字符串
    return ""


def _check_schedule_conflict(
    sections: list[SectionInfo],
    context: UserContext,
) -> tuple[list[SectionInfo], list[SectionInfo]]:
    """
    规则 4：检查课程 section 与用户已选课程的时间是否冲突。

    Returns:
        tuple[冲突的 sections, 不冲突的 sections]

    TODO: 由开发者实现时间冲突检测算法。
    需要：
        1. 获取 context.selected_courses 对应的 section 时间信息
        2. 与候选 section 时间做比对
    当前占位：假设无冲突，全部返回为可用 section
    """

    # TODO: 实现时间冲突检测
    # 当前占位：假设所有 section 都不冲突
    return [], sections
