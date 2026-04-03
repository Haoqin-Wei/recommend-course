# skill/clarifier.py
#
# 对应 SKILL.md：Step 2 —— 做澄清
#
# 职责：
#   当 context_checker 返回信息不足时，生成自然语言的追问文本。
#
# 核心规则（直接来自 SKILL.md Step 2，不做修改）：
#   - 每次优先追问 1~3 个最关键缺失项
#   - 用自然语言提问，不要机械列字段名
#   - 如果当前问题只需要查单一事实，不做多余追问
#   - 追问优先级：term > major > selected_courses > recommendation_goal > preferred_time
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass
from skill.context_checker import SufficiencyResult
from state.user_context import UserContext, QueryMode


# ── 澄清优先级（对应 SKILL.md Step 2 中的追问优先级）─────────────────────────
# 顺序即优先级，越靠前越先追问
CLARIFICATION_PRIORITY = [
    "term",
    "major",
    "selected_courses",
    "recommendation_goal",
    "preferred_time",
]

# ── 字段 → 自然语言追问模板（来自 SKILL.md Step 2 示例，可扩展）────────────
# TODO: 开发者可根据实际产品语调调整这些模板
CLARIFICATION_TEMPLATES: dict[str, str] = {
    "term": "你想查的是哪个学期的课程？",
    "major": "你现在是什么专业，主要是想满足专业要求还是想找轻松一点的课？",
    "selected_courses": "你目前已经选了哪些课？我可以顺便帮你避开时间冲突。",
    "recommendation_goal": "你更看重教授口碑、时间合适，还是整体难度低？",
    "preferred_time": "你有没有特别想避开或偏好的上课时间段？",
    # TODO: 如需其他字段的追问模板，在此补充
}

# 每轮最多追问几个字段（来自 SKILL.md Step 2："每次优先追问 1~3 个最关键缺失项"）
MAX_QUESTIONS_PER_TURN = 3


@dataclass
class ClarificationResult:
    """
    澄清生成结果。
    """
    needs_clarification: bool
    message: str
    # 给用户的追问文本（自然语言）

    asked_fields: list[str]
    # 本轮实际追问的字段列表（用于 state 追踪）


def generate_clarification(
    sufficiency: SufficiencyResult,
    context: UserContext,
    query_mode: QueryMode,
) -> ClarificationResult:
    """
    根据信息充足性检查结果，生成自然语言追问文本。

    Args:
        sufficiency: context_checker 返回的充足性检查结果。
        context:     当前用户上下文（用于个性化追问措辞）。
        query_mode:  问题类型（单点查询不追问）。

    Returns:
        ClarificationResult:
            needs_clarification=False → 不需要追问，直接进入 Step 3
            needs_clarification=True  → message 是要发给用户的追问文本

    规则执行（来自 SKILL.md Step 2）：
        1. 如果 is_sufficient，不追问
        2. 按 CLARIFICATION_PRIORITY 从 missing_fields 中选最多 MAX_QUESTIONS_PER_TURN 个
        3. 用 CLARIFICATION_TEMPLATES 生成自然语言问题
        4. 多个问题时合并成一条自然语言消息
    """

    if sufficiency.is_sufficient:
        return ClarificationResult(
            needs_clarification=False,
            message="",
            asked_fields=[],
        )

    # 按优先级排序缺失字段
    ordered_missing = [
        f for f in CLARIFICATION_PRIORITY
        if f in sufficiency.missing_fields
    ]
    # 补充不在优先级列表中的缺失字段（兜底）
    for f in sufficiency.missing_fields:
        if f not in ordered_missing:
            ordered_missing.append(f)

    # 取最多 MAX_QUESTIONS_PER_TURN 个
    fields_to_ask = ordered_missing[:MAX_QUESTIONS_PER_TURN]

    # 生成追问文本
    questions = []
    for field in fields_to_ask:
        template = CLARIFICATION_TEMPLATES.get(field)
        if template:
            questions.append(template)
        else:
            # TODO: 对没有模板的字段，生成兜底追问
            questions.append(f"能告诉我你的 {field} 吗？")

    # TODO: 多个问题的合并方式由开发者决定
    # 当前实现：换行拼接，后续可改为更自然的 LLM 生成方式
    if len(questions) == 1:
        message = questions[0]
    else:
        intro = "在我帮你推荐之前，需要先了解一些信息："
        message = intro + "\n" + "\n".join(f"- {q}" for q in questions)

    return ClarificationResult(
        needs_clarification=True,
        message=message,
        asked_fields=fields_to_ask,
    )


def parse_clarification_response(
    user_response: str,
    asked_fields: list[str],
    context: UserContext,
) -> UserContext:
    """
    将用户对追问的回答解析并更新到 UserContext 中。

    Args:
        user_response: 用户对上一轮追问的回答文本。
        asked_fields:  上一轮实际追问的字段列表。
        context:       当前 UserContext（原地修改并返回）。

    Returns:
        更新后的 UserContext。

    TODO: 实现从自然语言提取字段值的逻辑。
    例如:
        问的是 "term" → 从 "Spring 2025" 提取 term="2025 Spring"
        问的是 "selected_courses" → 从 "我选了 CS 161 和 ICS 33" 提取课程列表

    实现建议：
        简单情况：正则 + 字符串匹配
        复杂情况：调用 LLM 做 slot filling（demo 阶段可暂不实现，返回原始 context）
    """

    # TODO: 由开发者实现自然语言 → 字段值的提取逻辑
    # Demo 阶段占位：直接返回未修改的 context
    # ⚠️ 生产环境必须实现此函数，否则澄清闭环无法完成

    return context
