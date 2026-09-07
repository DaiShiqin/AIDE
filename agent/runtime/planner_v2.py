from __future__ import annotations

import os

from agent.config import AgentConfig, get_config
from agent.models import Message, Plan, PlanStep, SessionState, TodoStatus, ToolResult
from agent.runtime.context_vars import extract_dialog_context
from agent.runtime.planner import (
    PlannerOutput,
    PollutionPlanner,
    _apply_context_to_steps,
    _asks_for_analysis,
    _create_deterministic_plan,
    _is_qualitative_cmaq_bias_question,
    _planner_context,
    _should_add_supporting_cmaq_plot,
    _should_use_basic_knowledge,
    _should_use_cmaq_correction,
    _should_use_cmaq_plot,
    _should_use_cmaq_qa,
    _should_use_end_to_end_report,
    _should_use_pollution_warning,
    _should_use_report_guidance,
    _should_use_rsm_reduction,
)


TOOL_SKILL_DEFAULTS = {
    "cmaq_forecast_qa": "cmaq-forecast-qa",
    "cmaq_plot_data": "cmaq-plot-data",
    "cmaq_forecast_correction": "chengdu-cmaq-forecast-correction",
    "pollution_warning": "chengdu-pollution-alerming",
    "rsm_reduction": "run-rsm-reduction",
}


class PollutionPlannerV2(PollutionPlanner):
    """LLM-first planner with rules demoted to guardrails, repair, and fallback."""

    def __init__(self, config: AgentConfig | None = None):
        super().__init__(config or get_config())

    def create_plan(
        self,
        user_request: str,
        state: SessionState | None = None,
        has_analysis_context: bool | None = None,
    ) -> Plan:
        del has_analysis_context
        context_variables = extract_dialog_context(
            user_request,
            previous=state.context_variables if state is not None else None,
        )
        if state is not None:
            state.context_variables = context_variables

        guardrail_plan = _create_guardrail_plan(user_request, context_variables)
        if guardrail_plan is not None:
            return guardrail_plan

        try:
            llm_plan = self._create_plan_with_llm(user_request, state)
        except Exception as exc:
            fallback = _create_deterministic_plan(user_request, context_variables)
            if fallback is None:
                raise
            fallback.rationale = f"[fallback_rules_v2] LLM planner failed: {exc}. {fallback.rationale}"
            return fallback

        steps = [
            PlanStep(title=step.title, tool_hint=step.tool_hint or "reasoning", skill_hint=step.skill_hint)
            for step in llm_plan.steps
            if step.tool_hint != "final"
        ]
        steps = _repair_llm_steps(user_request, steps, self.config)
        steps = _apply_context_to_steps(steps, context_variables)
        steps.append(_final_step())
        rationale = f"[llm_planner_v2] {llm_plan.rationale}".strip()
        return Plan(
            objective=llm_plan.objective or user_request,
            steps=steps,
            rationale=rationale,
            context_variables=context_variables,
        )

    def replan(self, plan: Plan, result: ToolResult) -> Plan:
        updated_steps: list[PlanStep] = []
        for step in plan.steps:
            if step.id == result.step_id or (step.tool_hint == result.tool and step.status == TodoStatus.in_progress):
                step.status = TodoStatus.completed if result.ok else TodoStatus.blocked
            updated_steps.append(step)

        if result.ok:
            return Plan(
                objective=plan.objective,
                steps=updated_steps,
                rationale=plan.rationale,
                context_variables=plan.context_variables,
            )

        recovery_steps = self._create_recovery_steps_with_llm(plan, result)
        if not recovery_steps:
            recovery_steps = [
                PlanStep(
                    title=f"处理 {result.tool} 的失败信息，并判断是否重试、改用其他工具或直接总结当前已知结果",
                    tool_hint="reasoning",
                    status=TodoStatus.pending,
                )
            ]

        rebuilt = [step for step in updated_steps if step.tool_hint != "final"]
        rebuilt.extend(recovery_steps)
        rebuilt.append(_final_step())
        return Plan(
            objective=plan.objective,
            steps=rebuilt,
            rationale=f"{plan.rationale}\n[replan_v2] {result.tool} failed, inserted recovery steps.",
            context_variables=plan.context_variables,
        )

    def _build_planner_agent(self):
        if self.model is None:
            return None
        try:
            from langchain.agents import create_agent  # type: ignore
        except Exception:
            return None

        return create_agent(
            model=self.model,
            tools=[],
            response_format=PlannerOutput,
            system_prompt=(
                "你是成都污染分析智能体的 LLM Planner。\n"
                "你的首要职责是独立判断用户意图，并选择必要的 tool_hint/skill_hint 形成短而可执行的计划。\n"
                "规则只会在你遗漏关键业务步骤或明显误用工具时做最小修补；请不要依赖固定模板。\n"
                "涉及成都本地来源贡献、近年污染特征、比例数值、政策措施、研究证据或需要引用外部资料的问题，可以优先考虑 web_search；纯概念定义题通常用 reasoning 即可。\n"
                "CMAQ 结果路径、订正和绘图由 cmaq_* 专用工具自行读取数据；除非用户明确要求读取某个普通文件，不要为 CMAQ 数据额外安排 read_file。\n"
                "如果用户已经给出具体日期或时间范围，不要为了确认“未来三天”额外安排 current_time。\n"
                "不要输出 final 步骤，系统会自动补上。"
            ),
        )

    def _create_recovery_steps_with_llm(self, plan: Plan, result: ToolResult) -> list[PlanStep]:
        if self.agent is None:
            return []
        current_steps = "\n".join(
            f"- {step.status.value}: {step.tool_hint or 'reasoning'} | {step.title}" for step in plan.steps
        )
        prompt = (
            "上一个工具步骤失败了，请重新规划后续恢复步骤。\n"
            f"目标：{plan.objective}\n\n"
            f"当前计划：\n{current_steps}\n\n"
            f"失败工具：{result.tool}\n"
            f"失败摘要：{result.summary}\n\n"
            "请只输出后续需要新增执行的步骤，不要包含已经完成或 blocked 的步骤，也不要包含 final。"
        )
        scratch_state = SessionState(context_variables=plan.context_variables)
        scratch_state.messages.append(Message(role="user", content=prompt))
        try:
            llm_plan = self._create_plan_with_prompt(prompt, scratch_state)
        except Exception:
            return []
        return _repair_recovery_steps(
            [
                PlanStep(title=step.title, tool_hint=step.tool_hint or "reasoning", skill_hint=step.skill_hint)
                for step in llm_plan.steps
                if step.tool_hint != "final"
            ],
            failed_tool=result.tool,
        )

    def _create_plan_with_prompt(self, prompt: str, state: SessionState | None) -> PlannerOutput:
        if self.agent is None:
            raise RuntimeError("Planner 缺少可用的 DeepSeek LLM，请先配置 DEEPSEEK_API_KEY。")
        context = _planner_context(prompt, state, self.config)
        result = self.agent.invoke({"messages": [{"role": "user", "content": context}]})
        structured = result.get("structured_response")
        if isinstance(structured, PlannerOutput):
            return structured
        if isinstance(structured, dict):
            return PlannerOutput.model_validate(structured)
        raise RuntimeError("Planner 没有返回合法的结构化重规划。")


def _create_guardrail_plan(user_request: str, context_variables: dict) -> Plan | None:
    if not _is_qualitative_cmaq_bias_question(user_request):
        return None
    steps = [
        PlanStep(title="定性解释CMAQ在成都本地可能存在的系统性误差来源和诊断边界", tool_hint="reasoning"),
        _final_step(),
    ]
    return Plan(
        objective=user_request,
        steps=steps,
        rationale="[guardrail_v2] 用户未提供CMAQ路径、评估时段或同期观测数据，只能做定性问答，不调用CMAQ数据工具。",
        context_variables=context_variables,
    )


def _repair_llm_steps(user_request: str, steps: list[PlanStep], config: AgentConfig) -> list[PlanStep]:
    repaired = _sanitize_steps(steps)
    if not repaired:
        fallback = _create_deterministic_plan(user_request, {})
        return [step for step in (fallback.steps if fallback else []) if step.tool_hint != "final"]

    if _should_use_basic_knowledge(user_request):
        if _web_search_available(config) and any(step.tool_hint == "web_search" for step in repaired):
            return [step for step in repaired if step.tool_hint == "web_search"][:1]
        return [PlanStep(title="基于已有知识解释生态环境业务概念", tool_hint="reasoning")]

    if _should_use_report_guidance(user_request):
        _ensure_step(repaired, "read_skill", "读取污染过程报告生成 skill，归纳报告应覆盖的分析内容", "chengdu-pollution-report")
        return _dedupe_steps(repaired)

    if _should_use_end_to_end_report(user_request):
        _ensure_step(repaired, "read_skill", "读取成都端到端污染报告生成 skill，明确报告结构、证据规则和自检要求", "chengdu-pollution-report", position=0)
        _ensure_step(repaired, "cmaq_forecast_qa", "提取 CMAQ 关键污染过程和高值特征", "chengdu-pollution-report,cmaq-forecast-qa")
        _ensure_step(repaired, "cmaq_forecast_correction", "执行模式结果订正并生成研判图表", "chengdu-pollution-report,chengdu-cmaq-forecast-correction")
        _ensure_step(repaired, "pollution_warning", "结合预测日AQI和主污染物开展污染预警研判", "chengdu-pollution-report,chengdu-pollution-alerming")
    elif _should_use_cmaq_correction(user_request):
        _ensure_step(repaired, "cmaq_forecast_correction", "融合 Windy/EC 气象、CMAQ 和观测执行预报员经验订正", "chengdu-cmaq-forecast-correction")
    elif _should_use_pollution_warning(user_request):
        _ensure_step(repaired, "pollution_warning", "计算AQI并判断成都市重污染天气预警级别及响应措施", "chengdu-pollution-alerming")
    elif _should_use_cmaq_plot(user_request):
        if _asks_for_analysis(user_request):
            _ensure_step(repaired, "cmaq_forecast_qa", "提取并分析 CMAQ 预报数值特征", "cmaq-forecast-qa", position=0)
        _ensure_step(repaired, "cmaq_plot_data", "生成 CMAQ 结果图表", "cmaq-plot-data")
    elif _should_use_cmaq_qa(user_request):
        _ensure_step(repaired, "cmaq_forecast_qa", "读取并分析 CMAQ 预报结果", "cmaq-forecast-qa")
        if _should_add_supporting_cmaq_plot(user_request):
            _ensure_step(repaired, "cmaq_plot_data", "生成与CMAQ分析对应的时序或空间图件", "cmaq-plot-data")
    elif _should_use_rsm_reduction(user_request):
        _ensure_step(repaired, "rsm_reduction", "运行或解析 DeepRSM 减排情景并返回PM2.5改善量", "run-rsm-reduction")

    return _prune_noisy_steps(user_request, _dedupe_steps(repaired))


def _repair_recovery_steps(steps: list[PlanStep], failed_tool: str) -> list[PlanStep]:
    repaired = _sanitize_steps(steps)
    if len(repaired) > 3:
        repaired = repaired[:3]
    for step in repaired:
        if step.tool_hint == failed_tool:
            step.title = f"重试或降级执行：{step.title}"
    return repaired


def _prune_noisy_steps(user_request: str, steps: list[PlanStep]) -> list[PlanStep]:
    domain_tools = {
        "cmaq_forecast_qa",
        "cmaq_plot_data",
        "cmaq_forecast_correction",
        "pollution_warning",
        "rsm_reduction",
        "read_skill",
    }
    has_domain_tool = any(step.tool_hint in domain_tools for step in steps)
    if not has_domain_tool:
        return steps
    pruned: list[PlanStep] = []
    allow_web = _explicitly_requests_web(user_request)
    for step in steps:
        if step.tool_hint in {"current_time", "read_file"}:
            continue
        if step.tool_hint == "web_search" and not allow_web:
            continue
        if step.tool_hint == "reasoning" and len(steps) > 1:
            continue
        pruned.append(step)
    return pruned or steps


def _explicitly_requests_web(user_request: str) -> bool:
    text = user_request.lower()
    return any(token in text for token in ("联网", "搜索", "检索", "最新", "新闻", "web", "internet"))


def _web_search_available(config: AgentConfig) -> bool:
    provider = (config.web_search_provider or "stub").lower().strip()
    if provider == "tavily":
        return bool(os.getenv("TAVILY_API_KEY") or os.getenv("WEB_SEARCH_API_KEY"))
    if provider == "serpapi":
        return bool(os.getenv("SERPAPI_API_KEY") or os.getenv("SERP_API_KEY") or os.getenv("WEB_SEARCH_API_KEY"))
    return provider in {"duckduckgo", "ddg"}


def _sanitize_steps(steps: list[PlanStep]) -> list[PlanStep]:
    sanitized: list[PlanStep] = []
    for step in steps:
        tool_hint = step.tool_hint or "reasoning"
        if tool_hint == "final":
            continue
        skill_hint = step.skill_hint or TOOL_SKILL_DEFAULTS.get(tool_hint)
        sanitized.append(
            PlanStep(title=step.title.strip() or f"执行 {tool_hint}", tool_hint=tool_hint, skill_hint=skill_hint)
        )
    return sanitized


def _ensure_step(
    steps: list[PlanStep],
    tool_hint: str,
    title: str,
    skill_hint: str | None = None,
    position: int | None = None,
) -> None:
    if any(step.tool_hint == tool_hint for step in steps):
        for step in steps:
            if step.tool_hint == tool_hint and not step.skill_hint:
                step.skill_hint = skill_hint or TOOL_SKILL_DEFAULTS.get(tool_hint)
        return
    new_step = PlanStep(title=title, tool_hint=tool_hint, skill_hint=skill_hint or TOOL_SKILL_DEFAULTS.get(tool_hint))
    if position is None or position >= len(steps):
        steps.append(new_step)
    else:
        steps.insert(position, new_step)


def _dedupe_steps(steps: list[PlanStep]) -> list[PlanStep]:
    seen: set[tuple[str | None, str | None]] = set()
    deduped: list[PlanStep] = []
    for step in steps:
        key = (step.tool_hint, step.skill_hint)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(step)
    return deduped


def _final_step() -> PlanStep:
    return PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final")
