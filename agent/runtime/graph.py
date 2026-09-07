from __future__ import annotations

from collections.abc import Callable
from agent.config import AgentConfig, get_config
from agent.models import AgentEvent, Message, SessionState, TodoStatus, utc_now
from agent.runtime.executor import PollutionExecutor, todos_from_plan
from agent.runtime.planner import PollutionPlanner
from agent.runtime.planner_v2 import PollutionPlannerV2


EventSink = Callable[[AgentEvent], None]


class PlanAndExecuteGraph:
    def __init__(self, config: AgentConfig | None = None):
        self.config = config or get_config()
        self.planner = PollutionPlannerV2(self.config) if self.config.planner_version == "v2" else PollutionPlanner(self.config)
        self.executor = PollutionExecutor(self.config)

    def run(self, state: SessionState, user_message: str, emit: EventSink | None = None) -> SessionState:
        def send(event_type: str, payload: dict):
            if emit:
                emit(AgentEvent(type=event_type, session_id=state.id, payload=payload))

        tool_start = len(state.tool_results)
        artifact_start = len(state.artifacts)
        state.messages.append(Message(role="user", content=user_message))
        has_analysis_context = any(result.tool == "cmaq_forecast_qa" and result.ok for result in state.tool_results)
        state.plan = self.planner.create_plan(user_message, state=state, has_analysis_context=has_analysis_context)
        state.todos = todos_from_plan(state)
        state.updated_at = utc_now()
        send("plan", state.plan.model_dump())
        send("todo", {"todos": [todo.model_dump() for todo in state.todos]})

        step_index = 0
        executed_steps = 0
        max_steps = 24
        while step_index < len(state.plan.steps):
            if executed_steps >= max_steps:
                raise RuntimeError(f"执行步骤超过上限 {max_steps}，请检查 planner/replan 是否出现循环。")
            step = state.plan.steps[step_index]
            if step.tool_hint == "final":
                step_index += 1
                continue
            if step.status != TodoStatus.pending:
                step_index += 1
                continue
            step.status = TodoStatus.in_progress
            state.todos = todos_from_plan(state)
            send("todo", {"todos": [todo.model_dump() for todo in state.todos]})
            send("tool_call", {"step_id": step.id, "tool": step.tool_hint, "title": step.title})

            result = self.executor.execute_step(state, step)
            state.tool_results.append(result)
            state.artifacts.extend(result.artifacts)
            step.status = TodoStatus.completed if result.ok else TodoStatus.blocked
            state.todos = todos_from_plan(state)
            send("tool_result", result.model_dump())
            if result.artifacts:
                send("artifact", {"artifacts": [artifact.model_dump() for artifact in result.artifacts]})
            send("todo", {"todos": [todo.model_dump() for todo in state.todos]})

            if not result.ok:
                state.plan = self.planner.replan(state.plan, result)
                state.todos = todos_from_plan(state)
                send("plan", state.plan.model_dump())
                send("todo", {"todos": [todo.model_dump() for todo in state.todos]})
                step_index = 0
            else:
                step_index += 1
            executed_steps += 1

        turn_state = state.model_copy(
            update={
                "tool_results": state.tool_results[tool_start:],
                "artifacts": state.artifacts[artifact_start:],
            }
        )
        final_answer = self.executor.synthesize_answer(turn_state)
        for step in state.plan.steps:
            if step.tool_hint == "final":
                step.status = TodoStatus.completed
        state.todos = todos_from_plan(state)
        state.final_answer = final_answer
        state.messages.append(Message(role="assistant", content=final_answer))
        state.updated_at = utc_now()
        send("todo", {"todos": [todo.model_dump() for todo in state.todos]})
        send(
            "final",
            {
                "answer": final_answer,
                "artifacts": [artifact.model_dump() for artifact in state.artifacts[artifact_start:]],
            },
        )
        return state
