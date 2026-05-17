"""
Agent loop — drives a tool-using LLM conversation until it produces
a final answer (or a safety bound trips).

Each iteration:
    1. stream one LLM call with tools=TOOL_SCHEMAS, accumulating
       both content deltas and tool_call deltas
    2. if the model emitted tool calls, dispatch each one through
       app.agent.tools.dispatch, append the tool results to messages,
       and loop again
    3. otherwise the streamed content IS the final answer — yield a
       "final" event and stop

Event protocol (yielded to the caller, then forwarded to SSE):
    {"type": "token",            "text": "<delta>"}
        Final-answer text deltas. Also emitted for intermediate text
        the model produces BEFORE tool calls in the same iteration
        (Claude-style narration). The caller treats it as live text.

    {"type": "tool_call_start",  "name":..., "args":..., "label":...}
    {"type": "tool_call_done",   "name":..., "ok":bool, "label":...}
        Surround each tool dispatch. The frontend renders these as
        status chips ("查询 CS122A sections...").

    {"type": "final",            "text":..., "iterations":N, "tool_calls":M}
        Clean termination. text is the full accumulated assistant
        content from the final iteration (already streamed via
        "token" events; provided again for persistence).

    {"type": "error",            "message":"..."}
        Safety bound hit (max iterations / max tool calls) or fatal
        LLM error. Caller is expected to fall back to the legacy
        handler path.

Safety:
    MAX_ITERATIONS caps how many tool-call rounds the model gets.
    MAX_TOTAL_TOOLS caps cumulative tool dispatches across rounds.
    Both bounds exist to prevent runaway loops / cost spikes if a
    badly-tuned prompt makes the model spam tool calls.

Cancellation:
    asyncio.CancelledError propagates out unchanged — the user hit
    Stop, the SSE consumer cancelled the producer, we cancel the
    LLM call. Same model as stream_answer_llm.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

from app.agent import tools as agent_tools

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 6
MAX_TOTAL_TOOLS = 12


async def run_agent(
    messages: list[dict],
    *,
    client,
    model: str,
    user_id: str,
) -> AsyncIterator[dict]:
    """
    Run the agent loop on a prebuilt messages list. `messages` is
    mutated in place (assistant + tool messages are appended each
    round) so the caller can inspect the full trace.
    """
    tool_context = {"user_id": user_id}
    total_tool_calls = 0

    for iteration in range(MAX_ITERATIONS):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=agent_tools.TOOL_SCHEMAS,
                tool_choice="auto",
                stream=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[agent] LLM call failed (iter %d): %s: %s",
                         iteration, type(e).__name__, e)
            yield {"type": "error", "message": f"LLM call failed: {e}"}
            return

        accumulated_content = ""
        # DeepSeek's reasoning-mode models emit `reasoning_content`
        # deltas (the model's internal chain of thought). We don't
        # forward these to the user, but we MUST capture them and
        # echo them back on the assistant message — DeepSeek rejects
        # follow-up calls otherwise with "reasoning_content in the
        # thinking mode must be passed back to the API".
        accumulated_reasoning = ""
        # Tool-call accumulator keyed by `index` (the model can emit
        # multiple concurrent tool_calls; deltas carry their index).
        tool_calls_acc: dict[int, dict] = {}

        try:
            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    accumulated_content += delta.content
                    yield {"type": "token", "text": delta.content}

                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    accumulated_reasoning += reasoning

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        slot = tool_calls_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc_delta.id:
                            slot["id"] = tc_delta.id
                        fn = tc_delta.function
                        if fn:
                            if fn.name:
                                slot["name"] = fn.name
                            if fn.arguments:
                                slot["arguments"] += fn.arguments
        except asyncio.CancelledError:
            logger.info("[agent] cancelled at iter %d", iteration)
            raise

        # ── If no tool calls came back, this iteration's content IS
        #    the final answer. We've already streamed the tokens; emit
        #    the "final" event with the full text for persistence.
        if not tool_calls_acc:
            yield {
                "type": "final",
                "text": accumulated_content,
                "iterations": iteration + 1,
                "tool_calls": total_tool_calls,
            }
            return

        # ── Tool-call iteration. Append the assistant message that
        #    requested the calls (OpenAI tool-use protocol requires
        #    this so the model can see its own tool_calls when we
        #    feed back the results).
        ordered = [tool_calls_acc[k] for k in sorted(tool_calls_acc.keys())]
        assistant_msg: dict = {
            "role": "assistant",
            "content": accumulated_content or None,
            "tool_calls": [
                {
                    "id":   tc["id"],
                    "type": "function",
                    "function": {
                        "name":      tc["name"],
                        "arguments": tc["arguments"] or "{}",
                    },
                }
                for tc in ordered
            ],
        }
        if accumulated_reasoning:
            # DeepSeek thinking-mode requirement (see comment above).
            assistant_msg["reasoning_content"] = accumulated_reasoning
        messages.append(assistant_msg)

        for tc in ordered:
            if total_tool_calls >= MAX_TOTAL_TOOLS:
                yield {
                    "type": "error",
                    "message": f"exceeded max tool calls ({MAX_TOTAL_TOOLS})",
                }
                return
            total_tool_calls += 1

            # Parse args defensively — DeepSeek occasionally emits
            # malformed JSON on the first token of a delta; treat as
            # empty rather than crashing the whole turn.
            try:
                args = json.loads(tc["arguments"] or "{}")
            except json.JSONDecodeError as e:
                logger.warning("[agent] bad tool args from model (%s): %r → %s",
                               tc["name"], tc["arguments"], e)
                args = {}

            label = agent_tools.humanize_tool_call(tc["name"], args)
            yield {"type": "tool_call_start",
                   "name": tc["name"], "args": args, "label": label}

            result = agent_tools.dispatch(tc["name"], args, context=tool_context)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, default=str),
            })

            yield {"type": "tool_call_done",
                   "name": tc["name"],
                   "ok": "error" not in result,
                   "label": label}

    # Iteration cap exhausted without a final answer
    logger.warning("[agent] exceeded MAX_ITERATIONS=%d, %d tool calls used",
                   MAX_ITERATIONS, total_tool_calls)
    yield {
        "type": "error",
        "message": f"agent loop exceeded max iterations ({MAX_ITERATIONS})",
    }
