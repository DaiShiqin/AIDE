from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent.config import AgentConfig, get_config
from agent.models import Plan, PlanStep, SessionState, TodoStatus, ToolResult
from agent.runtime.context_vars import extract_dialog_context, format_context_variables
from agent.runtime.langchain_middleware import create_deepseek_model
from agent.tools.skill_tools import load_skill_context


PLANNER_TOOL_HINTS = (
    "web_search",
    "cmaq_forecast_qa",
    "cmaq_plot_data",
    "cmaq_forecast_correction",
    "pollution_warning",
    "rsm_reduction",
    "memory",
    "shell",
    "read_skill",
    "read_file",
    "current_time",
    "reasoning",
)


class PlannerStepDraft(BaseModel):
    title: str
    tool_hint: Literal[
        "web_search",
        "cmaq_forecast_qa",
        "cmaq_plot_data",
        "cmaq_forecast_correction",
        "pollution_warning",
        "rsm_reduction",
        "memory",
        "shell",
        "read_skill",
        "read_file",
        "current_time",
        "reasoning",
    ] | None = None
    skill_hint: str | None = None


class PlannerOutput(BaseModel):
    objective: str
    rationale: str = ""
    steps: list[PlannerStepDraft] = Field(default_factory=list)


class PollutionPlanner:
    def __init__(self, config: AgentConfig | None = None):
        self.config = config or get_config()
        self.model = create_deepseek_model(self.config)
        self.agent = self._build_planner_agent()

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
        deterministic_plan = _create_deterministic_plan(user_request, context_variables)
        if deterministic_plan is not None:
            return deterministic_plan
        if _should_use_cmaq_correction(user_request):
            steps = [
                PlanStep(
                    title="融合 Windy/EC 气象、CMAQ 和观测执行预报员经验订正，并生成研判报告和图件",
                    tool_hint="cmaq_forecast_correction",
                    skill_hint="chengdu-cmaq-forecast-correction",
                )
            ]
            steps.append(PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"))
            return Plan(
                objective=user_request,
                steps=steps,
                rationale="用户请求包含 CMAQ 订正或预报员经验修正意图，直接使用 CMAQ 预报订正工具。",
                context_variables=context_variables,
            )
        llm_plan = self._create_plan_with_llm(user_request, state)
        if not llm_plan.steps:
            raise RuntimeError("Planner 未生成可执行步骤，无法继续。")

        steps = [
            PlanStep(title=step.title, tool_hint=step.tool_hint, skill_hint=step.skill_hint)
            for step in llm_plan.steps
        ]
        steps = _apply_context_to_steps(steps, context_variables)
        steps.append(PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"))
        return Plan(objective=llm_plan.objective or user_request, steps=steps, rationale=llm_plan.rationale, context_variables=context_variables)

    def replan(self, plan: Plan, result: ToolResult) -> Plan:
        updated_steps: list[PlanStep] = []
        inserted = False
        for step in plan.steps:
            if step.tool_hint == result.tool and step.status == TodoStatus.in_progress:
                step.status = TodoStatus.completed if result.ok else TodoStatus.blocked
            updated_steps.append(step)
            if not result.ok and not inserted:
                updated_steps.append(
                    PlanStep(
                        title=f"处理 {result.tool} 的失败信息，并决定是否重试、改用其它工具或直接总结当前已知结果",
                        tool_hint="reasoning",
                        status=TodoStatus.pending,
                    )
                )
                inserted = True
        return Plan(objective=plan.objective, steps=updated_steps, rationale=plan.rationale, context_variables=plan.context_variables)

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
                "你是成都污染分析智能体的 Planner。\n"
                "你的职责是把用户当前问题拆成一组真正可执行、尽量不重复、尽量少走弯路的步骤。\n"
                "只输出结构化计划，不要输出最终答案。"
            ),
        )

    def _create_plan_with_llm(self, user_request: str, state: SessionState | None) -> PlannerOutput:
        if self.agent is None:
            raise RuntimeError("Planner 缺少可用的 DeepSeek LLM，请先配置 DEEPSEEK_API_KEY。")

        context = _planner_context(user_request, state, self.config)
        try:
            result = self.agent.invoke({"messages": [{"role": "user", "content": context}]})
        except Exception as exc:
            raise RuntimeError(f"Planner 调用 LLM 失败：{exc}") from exc

        structured = result.get("structured_response")
        if isinstance(structured, PlannerOutput):
            return structured
        if isinstance(structured, dict):
            return PlannerOutput.model_validate(structured)
        raise RuntimeError("Planner 没有返回合法的结构化计划。")

def _apply_context_to_steps(steps: list[PlanStep], context_variables: dict) -> list[PlanStep]:
    time_text = context_variables.get("requested_time_text")
    if not time_text:
        return steps
    for step in steps:
        if step.tool_hint not in {"cmaq_forecast_qa", "cmaq_plot_data"}:
            continue
        if str(time_text) in step.title or "时间范围" in step.title:
            continue
        step.title = f"{step.title}（时间范围：{time_text}）"
    return steps


def _create_deterministic_plan(user_request: str, context_variables: dict) -> Plan | None:
    if _is_qualitative_cmaq_bias_question(user_request):
        steps = [
            PlanStep(title="定性解释CMAQ在成都本地可能存在的系统性误差来源和诊断边界", tool_hint="reasoning"),
            PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"),
        ]
        return Plan(
            objective=user_request,
            steps=steps,
            rationale="用户未提供CMAQ结果路径、评估时段或同期观测数据，只能做定性问答，不调用CMAQ数据工具。",
            context_variables=context_variables,
        )

    if _should_use_cmaq_correction(user_request) and not _should_use_end_to_end_report(user_request):
        steps = [
            PlanStep(
                title="融合 Windy/EC 气象、CMAQ 和观测执行预报员经验订正，并生成研判报告和图件",
                tool_hint="cmaq_forecast_correction",
                skill_hint="chengdu-cmaq-forecast-correction",
            ),
            PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"),
        ]
        return Plan(
            objective=user_request,
            steps=steps,
            rationale="用户请求包含 CMAQ 订正或预报员经验修正意图，直接使用CMAQ预报订正工具。",
            context_variables=context_variables,
        )

    if _should_use_report_guidance(user_request):
        steps = [
            PlanStep(
                title="读取成都污染过程报告生成 skill，归纳报告应覆盖的分析内容",
                tool_hint="read_skill",
                skill_hint="chengdu-pollution-report",
            ),
            PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"),
        ]
        return Plan(
            objective=user_request,
            steps=steps,
            rationale="用户询问污染过程报告的内容框架，只需读取报告生成skill并归纳，不运行完整数据链。",
            context_variables=context_variables,
        )

    if _should_use_end_to_end_report(user_request):
        steps = [
            PlanStep(
                title="读取成都端到端污染报告生成 skill，明确报告结构、证据规则和自检要求",
                tool_hint="read_skill",
                skill_hint="chengdu-pollution-report",
            ),
            PlanStep(
                title="提取 CMAQ 关键污染过程和高值特征",
                tool_hint="cmaq_forecast_qa",
                skill_hint="chengdu-pollution-report,cmaq-forecast-qa",
            ),
            PlanStep(
                title="执行模式结果订正并生成研判图表",
                tool_hint="cmaq_forecast_correction",
                skill_hint="chengdu-pollution-report,chengdu-cmaq-forecast-correction",
            ),
        ]
        if True:
            steps.append(
                PlanStep(
                    title="结合预报日AQI和主污染物开展污染预警研判",
                    tool_hint="pollution_warning",
                    skill_hint="chengdu-pollution-report,chengdu-pollution-alerming",
                )
            )
        steps.append(PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"))
        return Plan(
            objective=user_request,
            steps=_apply_context_to_steps(steps, context_variables),
            rationale="用户请求端到端报告，按数据分析、模式订正、预警研判和最终报告组织执行。",
            context_variables=context_variables,
        )

    if _should_use_pollution_warning(user_request):
        steps = [
            PlanStep(
                title="计算AQI并判断成都市重污染天气预警级别及响应措施",
                tool_hint="pollution_warning",
                skill_hint="chengdu-pollution-alerming",
            ),
            PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"),
        ]
        return Plan(
            objective=user_request,
            steps=steps,
            rationale="用户提供AQI/污染物/预警判断信息，直接调用污染预警研判工具。",
            context_variables=context_variables,
        )

    if _should_use_basic_knowledge(user_request):
        steps = [
            PlanStep(title="基于已有知识解释生态环境业务概念", tool_hint="reasoning"),
            PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"),
        ]
        return Plan(
            objective=user_request,
            steps=steps,
            rationale="用户请求基础知识问答，不需要调用数据工具。",
            context_variables=context_variables,
        )

    if _should_use_cmaq_plot(user_request):
        steps: list[PlanStep] = []
        if _asks_for_analysis(user_request):
            steps.append(
                PlanStep(
                    title="提取并分析 CMAQ 预报数值特征",
                    tool_hint="cmaq_forecast_qa",
                    skill_hint="cmaq-forecast-qa",
                )
            )
        steps.append(
            PlanStep(
                title="生成 CMAQ 结果图表",
                tool_hint="cmaq_plot_data",
                skill_hint="cmaq-plot-data",
            )
        )
        steps.append(PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"))
        return Plan(
            objective=user_request,
            steps=_apply_context_to_steps(steps, context_variables),
            rationale="用户请求CMAQ图表或空间/时序可视化，直接调用绘图工具。",
            context_variables=context_variables,
        )

    if _should_use_cmaq_qa(user_request):
        steps = [
            PlanStep(
                title="读取并分析 CMAQ 预报结果",
                tool_hint="cmaq_forecast_qa",
                skill_hint="cmaq-forecast-qa",
            )
        ]
        if _should_add_supporting_cmaq_plot(user_request):
            steps.append(
                PlanStep(
                    title="生成与CMAQ分析对应的时序或空间图件",
                    tool_hint="cmaq_plot_data",
                    skill_hint="cmaq-plot-data",
                )
            )
        steps.append(PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"))
        return Plan(
            objective=user_request,
            steps=_apply_context_to_steps(steps, context_variables),
            rationale="用户请求CMAQ结果提取与数值分析，直接调用CMAQ问答工具。",
            context_variables=context_variables,
        )

    if _should_use_rsm_reduction(user_request):
        steps = [
            PlanStep(
                title="运行或解析 DeepRSM 减排情景并返回PM2.5改善量",
                tool_hint="rsm_reduction",
                skill_hint="run-rsm-reduction",
            ),
            PlanStep(title="汇总本轮执行结果并输出最终回答", tool_hint="final"),
        ]
        return Plan(
            objective=user_request,
            steps=steps,
            rationale="用户请求减排情景或PM2.5改善量，直接调用RSM减排工具。",
            context_variables=context_variables,
        )

    return None


def _planner_context(user_request: str, state: SessionState | None, config: AgentConfig) -> str:
    context_variables = state.context_variables if state is not None else extract_dialog_context(user_request)
    context_text = format_context_variables(context_variables)
    if state is None:
        history = "无历史对话。"
        tool_context = "无历史工具结果。"
        memory_context = "无用户偏好记忆。"
    else:
        history_lines = [f"{message.role}: {message.content}" for message in state.messages[-6:]]
        history = "\n".join(history_lines) or "无历史对话。"

        tool_lines = [f"{result.tool} | ok={result.ok} | {result.summary}" for result in state.tool_results[-6:]]
        tool_context = "\n".join(tool_lines) or "无历史工具结果。"

        memory_context = "\n".join(f"- {note}" for note in state.memory_notes[-6:]) or "无用户偏好记忆。"

    tool_lines = "\n".join(
        [
            "- web_search: 联网搜索政策、背景资料、新闻与外部知识。",
            "- cmaq_forecast_qa: 读取并分析 CMAQ 预报数据，输出结构化摘要。",
            "- cmaq_plot_data: 生成 CMAQ 时序图或空间分布图。",
            "- cmaq_forecast_correction: 融合 Windy/EC 气象、CMAQ 和观测，对成都 PM2.5/O3 预报进行预报员经验订正，输出研判报告和图件。",
            "- pollution_warning: 调用 chengdu-pollution-alerming，计算 AQI 并判断成都重污染天气预警级别和响应措施。",
            "- rsm_reduction: 运行本地 DeepRSM 减排情景，写入控制矩阵 case，读取 Dpm25 并返回 12 个区域 PM2.5 改善量。",
            "- memory: 记录用户习惯或偏好。",
            "- shell: 仅在确有必要时执行受控 PowerShell 命令。",
            "- read_skill: 读取某个 skill 文档的完整说明。",
            "- read_file: 读取项目内文件内容。",
            "- current_time: 获取当前时间。",
            "- reasoning: 直接基于上下文推理，不调用工具。",
        ]
    )
    planner_skill = load_skill_context(config, ["planner-core"], include_inventory=True, max_chars_per_skill=3600)

    return (
        "请为当前回合生成计划。\n\n"
        "规划技能说明：\n"
        f"{planner_skill}\n\n"
        f"当前用户问题：{user_request}\n\n"
        "最近对话：\n"
        f"{history}\n\n"
        "最近工具结果：\n"
        f"{tool_context}\n\n"
        "用户偏好记忆：\n"
        f"{memory_context}\n\n"
        "对话变量（必须在相关步骤中保留）：\n"
        f"{context_text}\n\n"
        "可用 tool_hint：\n"
        f"{tool_lines}\n\n"
        "要求：\n"
        "1. 步骤要短、可执行、避免重复。\n"
        "2. 只有在真的需要外部资料时才安排 web_search。\n"
        "3. 只有在需要读取本地文件时才安排 read_file。\n"
        "4. 只有在涉及时间判断时才安排 current_time。\n"
        "5. 如果某一步明显需要遵循某个业务 skill，请在 skill_hint 中写 skill 名，多个用逗号分隔。\n"
        "6. 不要输出 final 步骤，系统会自动补上。"
    )


def _should_use_cmaq_correction(user_request: str) -> bool:
    text = user_request.lower()
    if _is_qualitative_cmaq_bias_question(user_request):
        return False
    correction_keywords = (
        "订正",
        "修正",
        "校正",
        "预报员",
        "高估",
        "低估",
        "偏高",
        "偏低",
        "误差",
        "系统性误差",
        "结合观测",
        "观测结果",
        "更靠近观测",
        "correct",
        "correction",
        "bias",
    )
    cmaq_keywords = ("cmaq", "模式", "预报")
    return any(keyword in text for keyword in correction_keywords) and any(keyword in text for keyword in cmaq_keywords)


def _is_qualitative_cmaq_bias_question(user_request: str) -> bool:
    text = user_request.lower()
    if "cmaq" not in text or "系统性误差" not in user_request:
        return False
    data_intent = (
        "路径",
        ":\\",
        "：\\",
        "未来",
        "5月",
        "订正",
        "结合观测",
        "观测结果",
        "偏高",
        "偏低",
        "高估",
        "低估",
    )
    return not any(token in user_request or token in text for token in data_intent)


def _should_use_pollution_warning(user_request: str) -> bool:
    text = user_request.lower()
    warning_keywords = (
        "预警",
        "响应",
        "启动",
        "会商",
        "重污染",
        "黄色",
        "橙色",
        "红色",
        "应急措施",
        "管控措施",
    )
    pollutant_keywords = ("pm2.5", "pm25", "o3", "臭氧", "污染", "首要污染物", "主污染物")
    forecast_aqi_intent = "aqi" in text and any(keyword in text for keyword in ("未来", "预报", "分别", "日aqi", "是否", "应不应该"))
    return (any(keyword in text for keyword in warning_keywords) or forecast_aqi_intent) and any(
        keyword in text for keyword in pollutant_keywords
    )


def _should_use_cmaq_plot(user_request: str) -> bool:
    text = user_request.lower()
    cmaq_keywords = ("cmaq", "模式", "预报")
    plot_keywords = ("画图", "绘图", "图表", "时序", "时间序列", "空间", "分布图", "热点图", "map", "plot")
    return any(keyword in text for keyword in cmaq_keywords) and any(keyword in text for keyword in plot_keywords)


def _should_use_cmaq_qa(user_request: str) -> bool:
    text = user_request.lower()
    cmaq_keywords = ("cmaq", "模式结果", "预报结果")
    analysis_keywords = ("提取", "分析", "趋势", "高值", "峰值", "热点", "均值", "超标", "结果")
    return any(keyword in text for keyword in cmaq_keywords) and any(keyword in text for keyword in analysis_keywords)


def _should_use_rsm_reduction(user_request: str) -> bool:
    text = user_request.lower()
    return any(keyword in text for keyword in ("rsm", "deeprsm", "减排", "改善量", "控制矩阵"))


def _should_use_end_to_end_report(user_request: str) -> bool:
    text = user_request.lower()
    if "chengdu-pollution-report" in text:
        return True
    report_keywords = ("端到端", "完整报告", "研判报告", "污染过程报告", "污染过程简报", "简报", "日报", "专报", "生成报告", "报告生成")
    domain_keywords = ("cmaq", "模式", "预报", "污染", "预警", "订正")
    return any(keyword in text for keyword in report_keywords) and any(keyword in text for keyword in domain_keywords)


def _should_use_basic_knowledge(user_request: str) -> bool:
    text = user_request.lower()
    # Explicit CMAQ result extraction/analysis must take precedence over the
    # generic knowledge keywords below.  Questions about meteorological
    # conditions often contain both kinds of wording; treating those as basic
    # knowledge prevents the CMAQ tools from running at all.
    if _should_use_cmaq_qa(user_request) or _should_use_cmaq_plot(user_request):
        return False
    if "cmaq" in text and any(keyword in text for keyword in ("结果路径", "基于 cmaq", "基于cmaq", "模拟结果", "未来")):
        return False
    question_keywords = ("是什么", "解释", "区别", "关系", "为什么", "如何理解", "含义", "概念", "有哪些", "主要来源", "贡献因素", "主要组分", "气象条件")
    domain_keywords = ("aqi", "pm2.5", "pm25", "o3", "臭氧", "cmaq", "空气质量", "大气污染", "污染", "重污染", "预警", "nox", "vocs")
    return any(keyword in text for keyword in question_keywords) and any(keyword in text for keyword in domain_keywords)


def _should_use_report_guidance(user_request: str) -> bool:
    text = user_request.lower()
    return "报告" in text and any(keyword in text for keyword in ("应当分析哪些内容", "应该分析哪些内容", "包含哪些内容", "哪些方面"))


def _asks_for_analysis(user_request: str) -> bool:
    text = user_request.lower()
    return any(keyword in text for keyword in ("分析", "趋势", "高值", "峰值", "热点", "同时", "并"))


def _should_add_supporting_cmaq_plot(user_request: str) -> bool:
    text = user_request.lower()
    return any(keyword in text for keyword in ("趋势", "高值", "峰值", "区域", "滑动平均", "气象条件", "浓度"))
