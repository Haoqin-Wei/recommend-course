# query/query_layer.py
#
# 对应 SKILL.md：Step 3 —— 检索知识库
#
# 职责：
#   作为统一查询入口，根据 intent 类型调用对应的 mock tool，
#   并将结果传给 filter.py 应用过滤规则。
#
# 来源规则（SKILL.md Step 3）：
#   按问题类型调用对应工具：
#   - 课程推荐 / 筛选：course_catalog_tool
#   - 教授比较 / RMP：professor_rating_tool
#   - 难度 / 给分率：grade_distribution_tool
#   - 先修判断：prerequisite_tool
#   - 时间冲突 / 排课：course_schedule_tool
#   - GE / 专业要求：course_catalog_tool（按 ge_categories / major_requirements 过滤）
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass
from typing import Optional

from state.user_context import UserContext, QueryMode
from router.intent_classifier import CourseIntent
from tools.mock_tools import (
    get_course_catalog,
    get_course_schedule,
    get_prerequisites,
    get_professor_ratings,
    get_grade_distribution,
)
from query.filter import apply_filters, FilteredResult


@dataclass
class QueryResult:
    """
    query_layer 的统一输出结构。
    """
    intent: str
    query_mode: QueryMode

    filtered: Optional[FilteredResult] = None
    # 推荐 / 排课 / 比较类查询的过滤结果

    raw_data: Optional[dict] = None
    # 单点查询的原始数据（先修、教授评分、给分率等）
    # 格式由各子查询定义

    is_empty: bool = False
    # 是否无结果（触发 SKILL.md 中的"结果为空时的处理"）

    empty_reason: str = ""
    # 为空的原因，用于 answer_generator 生成放宽建议


def run_query(
    question: str,
    intent: str,
    context: UserContext,
) -> QueryResult:
    """
    统一查询入口：根据 intent 调用对应工具，返回结构化查询结果。

    Args:
        question: 用户原始输入（用于提取实体，如课程名、教授名）。
        intent:   子意图类型（来自 intent_classifier）。
        context:  当前用户上下文。

    Returns:
        QueryResult: 包含过滤后结果或原始数据。

    路由逻辑（来自 SKILL.md Step 3）：
        intent → 对应工具 → 过滤（推荐类）或直接返回（单点查询类）
    """

    if intent == CourseIntent.RECOMMENDATION:
        return _query_recommendation(question, context)

    elif intent == CourseIntent.PROFESSOR_REVIEW:
        return _query_professor(question, context)

    elif intent == CourseIntent.GRADE_DISTRIBUTION:
        return _query_grade_distribution(question, context)

    elif intent == CourseIntent.PREREQUISITE_CHECK:
        return _query_prerequisites(question, context)

    elif intent == CourseIntent.SCHEDULE_CONFLICT:
        return _query_schedule(question, context)

    elif intent == CourseIntent.GE_REQUIREMENT:
        return _query_ge_requirement(question, context)

    else:
        # unknown intent: 尝试通用课程查询
        return _query_recommendation(question, context)


# ─────────────────────────────────────────────────────────────────────────────
# 各子查询实现
# ─────────────────────────────────────────────────────────────────────────────

def _query_recommendation(question: str, context: UserContext) -> QueryResult:
    """
    课程推荐 / 筛选查询。

    调用 course_catalog_tool + course_schedule_tool，再过滤。
    """
    term = context.term or ""

    # Step 1: 获取候选课程列表
    # TODO: 根据 question 和 context 传入更精确的筛选参数
    candidates = get_course_catalog(term=term, major=context.major)

    if not candidates:
        return QueryResult(
            intent=CourseIntent.RECOMMENDATION,
            query_mode=context.query_mode,
            is_empty=True,
            empty_reason="当前学期暂无课程数据",
        )

    # Step 2: 获取 section 信息（用于时间冲突检查）
    course_ids = [c.course_id for c in candidates]
    sections = get_course_schedule(course_ids=course_ids, term=term)

    # Step 3: 应用 SKILL.md Step 3 的 5 条过滤规则
    filtered = apply_filters(
        candidate_courses=candidates,
        candidate_sections=sections,
        context=context,
    )

    is_empty = len(filtered.primary) == 0 and len(filtered.fallback) == 0
    return QueryResult(
        intent=CourseIntent.RECOMMENDATION,
        query_mode=context.query_mode,
        filtered=filtered,
        is_empty=is_empty,
        empty_reason="没有找到满足条件的课程，可尝试放宽筛选条件" if is_empty else "",
    )


def _query_professor(question: str, context: UserContext) -> QueryResult:
    """
    教授比较 / RMP 口碑查询。

    TODO: 从 question 中提取教授姓名或课程名（实体提取）。
    """
    # TODO: 实现教授名实体提取
    # 当前 mock：返回所有 mock 教授数据
    instructor_names = list(["Dr. Shindler", "Dr. Dillencourt", "Dr. Rina Dechter"])
    ratings = get_professor_ratings(instructor_names)

    return QueryResult(
        intent=CourseIntent.PROFESSOR_REVIEW,
        query_mode=context.query_mode,
        raw_data={"ratings": ratings},
        is_empty=len(ratings) == 0,
        empty_reason="未找到该教授的评分数据" if not ratings else "",
    )


def _query_grade_distribution(question: str, context: UserContext) -> QueryResult:
    """
    历史给分率 / GPA 分布查询（Zotistics）。

    TODO: 从 question 中提取课程 ID 和教授姓名。
    """
    # TODO: 实现课程 ID 实体提取
    course_id = "CS 161"  # Mock：固定查 CS 161
    distributions = get_grade_distribution(course_id=course_id)

    return QueryResult(
        intent=CourseIntent.GRADE_DISTRIBUTION,
        query_mode=context.query_mode,
        raw_data={"distributions": distributions},
        is_empty=len(distributions) == 0,
    )


def _query_prerequisites(question: str, context: UserContext) -> QueryResult:
    """
    先修课判断查询。

    TODO: 从 question 中提取目标课程 ID。
    """
    # TODO: 实现课程 ID 实体提取
    course_id = "CS 171"  # Mock：固定查 CS 171
    prereqs = get_prerequisites(course_id)

    # 与用户已修课程对比，判断是否满足
    unmet = [p for p in prereqs if p not in context.completed_courses]
    met   = [p for p in prereqs if p in context.completed_courses]

    return QueryResult(
        intent=CourseIntent.PREREQUISITE_CHECK,
        query_mode=context.query_mode,
        raw_data={
            "course_id": course_id,
            "prerequisites": prereqs,
            "met": met,
            "unmet": unmet,
        },
        is_empty=False,
    )


def _query_schedule(question: str, context: UserContext) -> QueryResult:
    """
    时间冲突 / 排课查询。

    TODO: 从 question 中提取目标课程 ID，与已选课时间比对。
    """
    term = context.term or ""
    # TODO: 实现目标课程 ID 提取
    target_course_ids = ["CS 171"]  # Mock
    sections = get_course_schedule(course_ids=target_course_ids, term=term)

    # TODO: 与 context.selected_courses 的时间做实际比对
    return QueryResult(
        intent=CourseIntent.SCHEDULE_CONFLICT,
        query_mode=context.query_mode,
        raw_data={"sections": sections},
        is_empty=len(sections) == 0,
    )


def _query_ge_requirement(question: str, context: UserContext) -> QueryResult:
    """
    GE / 专业要求查询。

    TODO: 从 question 中提取课程 ID，查询其 GE 和专业要求归属。
    """
    term = context.term or ""
    # TODO: 实现课程 ID 提取
    all_courses = get_course_catalog(term=term)
    ge_courses = [c for c in all_courses if c.ge_categories]

    return QueryResult(
        intent=CourseIntent.GE_REQUIREMENT,
        query_mode=context.query_mode,
        raw_data={"ge_courses": ge_courses},
        is_empty=len(ge_courses) == 0,
    )
