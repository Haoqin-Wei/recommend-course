# skill/course_skill.py
#
# 对应 SKILL.md：整体执行步骤编排（Step 1 → Step 2 → Step 3 → Step 4 → Step 5）
#
# 职责：
#   串联所有子模块，按 SKILL.md 定义的顺序执行完整技能流程。
#   这是 skill 层的主入口，router 调用此函数后获得最终回答。
#
# Pipeline 流程（严格对应 SKILL.md 执行步骤）：
#   Step 1: 获取/检查关键信息         → context_checker.check_context_sufficiency()
#   Step 2: 做澄清（信息不足时）      → clarifier.generate_clarification()
#   Step 3: 检索知识库                → query_layer.run_query()
#   Step 4: 整理信息，生成回答        → answer_generator.generate_answer()
#   Step 5: 给出推荐问                → followup_generator.generate_followups()
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass
from typing import Optional

from state.user_context import ConversationState, QueryMode
from router.intent_classifier import classify_intent, classify_query_mode, CourseIntent
from skill.context_checker import check_context_sufficiency
from skill.clarifier import generate_clarification, parse_clarification_response, ClarificationResult
from query.query_layer import run_query
from skill.answer_generator import generate_answer, AnswerPayload
from skill.followup_generator import generate_followups


@dataclass
class SkillResponse:
    """
    skill pipeline 的最终输出。
    """
    reply: str
    # 给用户的自然语言回复（直接展示）

    needs_clarification: bool = False
    # 是否处于等待用户澄清的状态

    clarification_fields: list[str] = None
    # 本轮追问的字段列表（用于下一轮 parse_clarification_response）

    answer_payload: Optional[AnswerPayload] = None
    # 完整回答结构（含 ui_payload，用于前端渲染）

    def __post_init__(self):
        if self.clarification_fields is None:
            self.clarification_fields = []


def run_skill_pipeline(
    state: ConversationState,
) -> SkillResponse:
    """
    执行完整的 course recommendation skill pipeline。

    Args:
        state: 当前会话状态，包含 current_question、user_context 和对话历史。

    Returns:
        SkillResponse: 最终回复内容 + 状态更新信息。

    执行流程（严格按 SKILL.md 执行步骤）：
    ─────────────────────────────────────────────────────────────────────────
    [多轮澄清处理]
        如果上一轮在等待澄清（state.awaiting_clarification == True），
        先解析用户回答并更新 context，再重新进入 Step 1

    [Step 1] 获取关键信息
        调用 context_checker，判断当前信息是否充足
        同时确定 intent 和 query_mode（单点查询 vs 个性化推荐）

    [Step 2] 做澄清（仅在信息不足时）
        生成追问文本，返回 SkillResponse(needs_clarification=True)
        等待用户下一轮输入，再回到 Step 1

    [Step 3] 检索知识库
        按 intent 调用对应工具查询数据，应用 5 条过滤规则

    [Step 4] 整理信息，生成回答
        调用 answer_generator，按回答结构生成自然语言

    [Step 5] 给出推荐问
        调用 followup_generator，生成 2~3 个后续引导问题
        follow-up 问题追加到回答末尾
    ─────────────────────────────────────────────────────────────────────────
    """

    question = state.current_question
    context  = state.user_context

    # ── 多轮澄清：解析上一轮追问的回答 ─────────────────────────────────────
    if state.awaiting_clarification and state.intent:
        # TODO: 从 state 中获取上一轮 asked_fields
        # 当前占位：直接跳过解析，后续需要在 state 中存储 asked_fields
        asked_fields: list[str] = []  # TODO: 从 state 读取
        context = parse_clarification_response(question, asked_fields, context)
        state.user_context = context
        state.awaiting_clarification = False

    # ── Step 1：确定 intent 和 query_mode ────────────────────────────────────
    # intent 可能在上一轮已经分类过（多轮对话保留）
    if not state.intent:
        intent = classify_intent(question, state)
        state.intent = intent
    else:
        intent = state.intent

    query_mode = classify_query_mode(question, intent)
    context.query_mode = query_mode

    # ── Step 1：检查信息充足性 ──────────────────────────────────────────────
    sufficiency = check_context_sufficiency(context, query_mode, intent)

    # ── Step 2：做澄清（信息不足时）────────────────────────────────────────
    if not sufficiency.is_sufficient:
        clarification: ClarificationResult = generate_clarification(
            sufficiency, context, query_mode
        )
        if clarification.needs_clarification:
            state.awaiting_clarification = True
            # TODO: 将 clarification.asked_fields 存入 state，供下一轮解析使用
            return SkillResponse(
                reply=clarification.message,
                needs_clarification=True,
                clarification_fields=clarification.asked_fields,
            )

    # ── Step 3：检索知识库 ──────────────────────────────────────────────────
    query_result = run_query(
        question=question,
        intent=intent,
        context=context,
    )

    # ── Step 4 + 5：生成回答 + follow-up ────────────────────────────────────
    followups = generate_followups(query_result, context)
    answer = generate_answer(query_result, context, followups)

    # ── 更新会话状态 ────────────────────────────────────────────────────────
    state.skill_triggered = True
    state.history.append({"role": "user",      "content": question})
    state.history.append({"role": "assistant",  "content": answer.text})
    # 重置 intent，允许下一轮重新分类
    # TODO: 开发者决定 intent 是否需要跨轮保留（对话连续性）
    state.intent = None

    return SkillResponse(
        reply=answer.text,
        needs_clarification=False,
        answer_payload=answer,
    )
