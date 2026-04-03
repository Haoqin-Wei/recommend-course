# main.py
#
# Demo 入口：驱动完整的 Router → Skill Pipeline → 回答生成流程。
# 当前阶段用于手动验证 pipeline 通路和各模块之间的数据流。
# ─────────────────────────────────────────────────────────────────────────────

from state.user_context import ConversationState, UserContext, DifficultyPreference
from router.intent_classifier import is_course_related
from skill.course_skill import run_skill_pipeline, SkillResponse


def chat(question: str, state: ConversationState) -> str:
    """
    单轮对话处理入口。

    完整流程：
        1. Router: is_course_related() 判断是否触发 skill
        2. Skill Pipeline: run_skill_pipeline() 执行 5 步流程
        3. 返回最终回复文本

    Args:
        question: 用户当前输入。
        state:    当前会话状态（多轮对话共享）。

    Returns:
        str: 最终给用户的回复文本。
    """

    # ── Router：判断是否触发 course skill ───────────────────────────────────
    state.current_question = question

    triggered = is_course_related(question, state)
    state.skill_triggered = triggered

    if not triggered:
        # TODO: 将非选课相关问题路由到通用对话模块
        # 当前占位：直接返回提示文本
        return "[通用对话] 这个问题超出了我的选课助手范围，你可以问我关于 UCI 课程、教授、排课等问题。"

    # ── Skill Pipeline：执行 SKILL.md 定义的 5 步流程 ────────────────────────
    response: SkillResponse = run_skill_pipeline(state)

    return response.reply


# ─────────────────────────────────────────────────────────────────────────────
# Demo 运行器
# ─────────────────────────────────────────────────────────────────────────────

def run_demo():
    """
    交互式 demo：模拟多轮对话，验证完整 pipeline。
    """

    print("=" * 60)
    print("UCI Course Recommendation Assistant — Demo")
    print("=" * 60)
    print("输入 'quit' 退出\n")

    # ── 初始化会话状态 ──────────────────────────────────────────────────────
    # TODO: 开发者可在此预填 profile，模拟不同学生场景
    profile = UserContext(
        major=None,               # TODO: 可预填 "Computer Science"
        year=None,                # TODO: 可预填 "junior"
        term=None,                # TODO: 可预填 "2025 Spring"
        selected_courses=[],      # TODO: 可预填 ["CS 161"]
        completed_courses=[],     # TODO: 可预填 ["ICS 31", "ICS 32", "ICS 33", "ICS 45C", "ICS 46"]
        difficulty_preference=DifficultyPreference.ANY,
    )
    state = ConversationState(user_context=profile)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("再见！")
            break

        reply = chat(user_input, state)
        print(f"\nAssistant: {reply}")

        # Debug 模式：显示当前状态（开发阶段可开启）
        # _debug_state(state)


def _debug_state(state: ConversationState):
    """开发阶段用：打印当前 state 摘要。"""
    print(f"\n[DEBUG] intent={state.intent} | "
          f"awaiting_clarification={state.awaiting_clarification} | "
          f"skill_triggered={state.skill_triggered} | "
          f"history_turns={len(state.history)//2}")
    ctx = state.user_context
    print(f"[DEBUG] context: term={ctx.term} major={ctx.major} "
          f"selected={ctx.selected_courses} completed={ctx.completed_courses[:3]}...")


# ─────────────────────────────────────────────────────────────────────────────
# 批量测试用例（验证各意图路由是否正确）
# ─────────────────────────────────────────────────────────────────────────────

TEST_CASES = [
    # (用户输入, 预期 is_course_related, 预期 intent)
    ("CS 161 有什么先修课要求？",         True,  "prerequisite_check"),
    ("Dr. Rina Dechter 的课好不好？",      True,  "professor_review"),
    ("CS 171 历史给分怎么样？",           True,  "grade_distribution"),
    ("帮我推荐几门适合 CS 大三的课",      True,  "recommendation"),
    ("我的课表会不会和 CS 175 冲突？",    True,  "schedule_conflict"),
    ("ICS 31 算不算 GE？",               True,  "ge_requirement"),
    ("今天天气怎么样？",                  False, None),
    ("怎么提高学习效率？",               False, None),
]


def run_batch_test():
    """
    批量验证各意图路由是否符合预期。
    TODO: 实现 intent_classifier 后启用此测试。
    """
    print("\n" + "=" * 60)
    print("Batch Routing Test")
    print("=" * 60)

    passed = 0
    for question, expected_related, expected_intent in TEST_CASES:
        state = ConversationState()
        state.current_question = question

        try:
            related = is_course_related(question, state)
            status = "✓" if related == expected_related else "✗"
            print(f"{status} [{related}→{expected_related}] {question[:40]}")
            if related == expected_related:
                passed += 1
        except NotImplementedError:
            print(f"⚠ [NOT IMPL] {question[:40]}")

    print(f"\n通过: {passed}/{len(TEST_CASES)}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_batch_test()
    else:
        run_demo()
