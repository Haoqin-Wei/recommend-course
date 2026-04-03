# state/user_context.py
#
# 对应 SKILL.md：Step 1 —— 获取关键信息
#
# 定义本技能所需的所有用户上下文字段。
# 字段列表直接来源于 SKILL.md Step 1 中的定义，不做增减。
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class QueryMode(str, Enum):
    """
    对应 SKILL.md Step 1 中的两种问题类型：
      - POINT_QUERY：单点查询（先修、教授评分、时间冲突、GE归属等）
      - PERSONALIZED：个性化推荐 / 排课建议
    """
    POINT_QUERY   = "point_query"
    PERSONALIZED  = "personalized"
    UNKNOWN       = "unknown"   # 尚未分类


class DifficultyPreference(str, Enum):
    """
    对应 SKILL.md Step 1 中的 difficulty_preference 字段。
    具体取值由开发者根据产品定义补充。
    """
    EASY   = "easy"       # 轻松拿分
    MEDIUM = "medium"     # 中等难度
    HARD   = "hard"       # 挑战性强
    ANY    = "any"        # 无偏好


@dataclass
class UserContext:
    """
    SKILL.md Step 1 中所有关键信息字段的结构化表示。

    字段含义与来源均一一对应 SKILL.md，不额外添加业务字段。
    None 表示该字段尚未被收集，用于 context_checker 判断信息充足性。
    """

    # ── 来自 SKILL.md Step 1 ──────────────────────────────────────────────────

    term: Optional[str] = None
    # 学期，例如 "2025 Spring"、"2024 Fall"
    # SKILL.md 澄清优先级第 1 位

    major: Optional[str] = None
    # 专业，例如 "Computer Science"、"Data Science"
    # SKILL.md 澄清优先级第 2 位

    year: Optional[str] = None
    # 年级，例如 "freshman"、"sophomore"、"junior"、"senior"、"graduate"
    # SKILL.md 中标注"如果可获得"，非强制

    selected_courses: list[str] = field(default_factory=list)
    # 本学期已选择的课程列表
    # SKILL.md 澄清优先级第 3 位（推荐场景下必须）

    completed_courses: list[str] = field(default_factory=list)
    # 历史已修完的课程列表（用于先修判断）
    # SKILL.md 标注"如果和先修判断相关"

    preferred_time: Optional[list[str]] = None
    # 时间偏好，例如 ["MWF morning", "TR afternoon"]
    # SKILL.md 标注"如果和排课相关"，澄清优先级第 5 位

    difficulty_preference: DifficultyPreference = DifficultyPreference.ANY
    # 难度偏好，SKILL.md 标注"如果和推荐相关"

    recommendation_goal: Optional[str] = None
    # 推荐目标，例如 "轻松拿分"、"满足专业要求"、"填GE"、"找高口碑教授"
    # SKILL.md 澄清优先级第 4 位（推荐场景下需追问）

    # ── 运行时字段（非用户输入，由系统填写）────────────────────────────────────

    query_mode: QueryMode = QueryMode.UNKNOWN
    # 由 intent_classifier 写入，区分单点查询 vs 个性化推荐


@dataclass
class ConversationState:
    """
    完整的会话状态，贯穿整个 skill pipeline。
    """

    user_context: UserContext = field(default_factory=UserContext)

    history: list[dict] = field(default_factory=list)
    # 对话历史，格式: [{"role": "user"/"assistant", "content": "..."}]

    current_question: str = ""
    # 当前轮次的用户原始输入

    intent: Optional[str] = None
    # 当前轮次的子意图（由 intent_classifier 写入）

    awaiting_clarification: bool = False
    # 当前是否处于等待用户澄清的状态

    skill_triggered: bool = False
    # 本轮是否已触发 course skill
