# router/intent_classifier.py
#
# 对应 SKILL.md：触发条件 / 不触发条件 + Step 1 中的问题类型判断
#
# 职责：
#   1. is_course_related()     —— 判断是否触发 course skill（来自 SKILL.md 触发规则）
#   2. classify_intent()       —— 判断子意图类型（先修 / 教授 / 推荐 / 排课等）
#   3. classify_query_mode()   —— 判断是"单点查询"还是"个性化推荐"（来自 SKILL.md Step 1）
#
# 规则来源：
#   触发条件和不触发条件的完整定义见 SKILL.md，不在此重新定义。
#   本文件只负责把规则转化为可执行的判断逻辑。
# ─────────────────────────────────────────────────────────────────────────────

from typing import Optional
from state.user_context import ConversationState, QueryMode


# ─────────────────────────────────────────────────────────────────────────────
# 子意图类型定义
# 直接对应 SKILL.md Step 3 中列出的 6 类问题类型
# ─────────────────────────────────────────────────────────────────────────────

class CourseIntent:
    RECOMMENDATION      = "recommendation"       # 课程推荐 / 筛选
    PROFESSOR_REVIEW    = "professor_review"     # 教授比较 / RMP 口碑
    GRADE_DISTRIBUTION  = "grade_distribution"   # 难度 / 给分率
    PREREQUISITE_CHECK  = "prerequisite_check"   # 先修判断
    SCHEDULE_CONFLICT   = "schedule_conflict"    # 时间冲突 / 排课
    GE_REQUIREMENT      = "ge_requirement"       # GE / 专业要求
    UNKNOWN             = "unknown"              # 无法分类


# ─────────────────────────────────────────────────────────────────────────────
# 函数 1：is_course_related
# ─────────────────────────────────────────────────────────────────────────────

def is_course_related(question: str, state: Optional[ConversationState] = None) -> bool:
    """
    判断用户问题是否应触发 course recommendation skill。

    判断依据直接来自 SKILL.md"触发条件"和"不触发条件"章节。
    本函数不重新定义规则，只实现判断逻辑。

    Args:
        question: 用户当前输入的原始文本。
        state:    当前会话状态（用于多轮上下文辅助判断）。
                  SKILL.md 中提到："用户虽然没有直接说'推荐课程'，但已明确处于
                  选课上下文中"时也应触发。

    Returns:
        True  → 触发 course skill
        False → 不触发，交由通用对话处理

    实现说明（SKILL.md 已定义规则，在此填写判断逻辑）：

        不触发条件（优先检查，命中任一则返回 False）：
          - 纯闲聊、情绪表达、寒暄
          - 与课程无关：天气、校园生活、交通、饮食、社团
          - 纯学习方法建议
          - 职业/实习/简历（不涉及课程选择）
          - 泛建议（不需要课程数据支持）
          - 问题主题不明确
          - 在问系统开发/编程/agent/skill/tool 技术问题

        触发条件（通过不触发检查后，命中任一则返回 True）：
          - 选课规划、课程推荐、课程比较
          - 教授比较
          - 课表安排、先修课判断
          - 专业/GE 满足情况
          - 已在选课上下文中且问题围绕课程展开

        多轮上下文：若 state.awaiting_clarification == True，
        则当前输入很可能是对上一轮追问的回答，需特殊处理。
    """

    # 多轮上下文：如果上一轮正在等待澄清，当前输入视为选课相关
    if state and state.awaiting_clarification:
        return True

    # TODO: 实现不触发条件检查
    # 建议优先用关键词 + 模式匹配，对边界情况可引入 LLM 语义判断
    # 参考 SKILL.md "满足以下任一情况不触发" 章节

    # TODO: 实现触发条件检查
    # 参考 SKILL.md "满足以下情况触发" 章节及例句列表

    # Demo 阶段占位：直接返回 True，等规则实现后替换
    # ⚠️ 此处是占位逻辑，生产环境必须替换
    raise NotImplementedError(
        "is_course_related() 尚未实现。"
        "请参照 SKILL.md 触发条件 / 不触发条件章节实现判断逻辑。"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 函数 2：classify_intent
# ─────────────────────────────────────────────────────────────────────────────

def classify_intent(question: str, state: Optional[ConversationState] = None) -> str:
    """
    在确认问题触发 skill 后，判断属于哪种子意图。

    子意图类型直接对应 SKILL.md Step 3 中列出的 6 类检索方向。
    每种子意图决定后续调用哪些 mock tool。

    Args:
        question: 用户当前输入。
        state:    当前会话状态（多轮上下文参考）。

    Returns:
        str: CourseIntent 中的一个值。

    意图映射（来自 SKILL.md Step 3）：
        "recommendation"      → 课程推荐 / 课程筛选
        "professor_review"    → 教授比较 / RMP 口碑
        "grade_distribution"  → 难度 / 给分率（Zotistics）
        "prerequisite_check"  → 先修判断
        "schedule_conflict"   → 时间冲突 / 排课
        "ge_requirement"      → GE / 专业要求
        "unknown"             → 无法归类

    SKILL.md 中对单点查询有特殊说明：
        先修、教授评分、时间冲突、GE 归属 → 可以是 POINT_QUERY 模式
        → 此处只分类 intent，query_mode 由 classify_query_mode() 单独判断
    """

    # TODO: 根据 question 内容判断子意图
    # 建议：关键词匹配 + 语义兜底
    # 参考 SKILL.md Step 3 中各子类型的描述

    raise NotImplementedError(
        "classify_intent() 尚未实现。"
        "请参照 SKILL.md Step 3 中的 6 类问题类型实现分类逻辑。"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 函数 3：classify_query_mode
# ─────────────────────────────────────────────────────────────────────────────

def classify_query_mode(question: str, intent: str) -> QueryMode:
    """
    判断用户问题属于"单点查询"还是"个性化推荐"。

    来源：SKILL.md Step 1 中的判断标准：
        "如果用户问题只是单点查询……则不必强求所有字段完整，可以直接进入第三步"
        "如果用户问题是个性化推荐或排课建议……则至少需要学期、专业……"

    Args:
        question: 用户当前输入。
        intent:   已分类的子意图（由 classify_intent 提供）。

    Returns:
        QueryMode.POINT_QUERY  → 单点查询（先修/教授评分/时间冲突/GE归属）
        QueryMode.PERSONALIZED → 个性化推荐 / 排课建议

    SKILL.md 中明确属于单点查询的场景：
        - 某门课有没有先修要求
        - 某教授评分怎么样
        - 某门课是否时间冲突
        - 某门课是否属于 GE / major requirement

    其余场景（推荐多门课、排课、比较等）默认为 PERSONALIZED。
    """

    # 根据 SKILL.md，这四类 intent 对应单点查询的典型场景
    POINT_QUERY_INTENTS = {
        CourseIntent.PREREQUISITE_CHECK,
        CourseIntent.PROFESSOR_REVIEW,
        CourseIntent.SCHEDULE_CONFLICT,
        CourseIntent.GE_REQUIREMENT,
    }

    # TODO: 仅靠 intent 判断不够精准
    # 例如 "帮我比较这两个教授" 虽然是 professor_review，但可能是个性化推荐
    # 需要结合 question 内容做更精细的判断
    if intent in POINT_QUERY_INTENTS:
        # TODO: 补充基于 question 文本的细化判断
        return QueryMode.POINT_QUERY

    return QueryMode.PERSONALIZED
