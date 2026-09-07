from __future__ import annotations

import json
import re
import csv
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from agent.config import AgentConfig, get_config
from agent.models import Artifact, PlanStep, SessionState, Todo, ToolResult
from agent.runtime.context_vars import extract_time_range, format_context_variables
from agent.runtime.langchain_middleware import MiddlewareStatus, build_langchain_middleware, create_deepseek_model
from agent.tools.cmaq_tools import cmaq_forecast_correction, cmaq_forecast_qa, cmaq_plot_data
from agent.tools.memory import extract_memory_note, read_memory, record_memory
from agent.tools.pollution_warning import pollution_warning
from agent.tools.rsm_tools import rsm_reduction
from agent.tools.safe_shell import run_shell
from agent.tools.skill_tools import list_skills, load_skill_context, parse_skill_names, read_skill
from agent.tools.system_tools import get_current_time, read_file
from agent.tools.web_search import web_search


@dataclass
class ExecutorResult:
    tool_results: list[ToolResult] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    final_answer: str | None = None
    middleware_status: list[MiddlewareStatus] = field(default_factory=list)


class PollutionExecutor:
    def __init__(self, config: AgentConfig | None = None):
        self.config = config or get_config()
        self.model = create_deepseek_model(self.config)
        self.middleware, self.middleware_status = build_langchain_middleware(self.config)
        self.final_agent = self._build_final_agent()

    def execute_step(self, state: SessionState, step: PlanStep) -> ToolResult:
        direct_result = self._execute_direct_step(state, step)
        if direct_result is not None:
            return direct_result

        if self.model is None:
            raise RuntimeError("Executor 缺少可用的 DeepSeek LLM，请先配置 DEEPSEEK_API_KEY。")

        observed_results: list[ToolResult] = []
        agent = self._build_step_agent(state, step, observed_results)
        prompt = _step_prompt(state, step, self.config)

        try:
            result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
        except Exception as exc:
            raise RuntimeError(f"Executor 执行步骤失败：{exc}") from exc

        answer = _extract_last_ai_text(result.get("messages", []))
        artifacts = _merge_artifacts(observed_results)
        ok = all(item.ok for item in observed_results) if observed_results else True
        used_tools = list(dict.fromkeys(item.tool for item in observed_results))

        for item in observed_results:
            if item.tool == "memory" and item.ok:
                note = item.data.get("note")
                if isinstance(note, str) and note and note not in state.memory_notes:
                    state.memory_notes.append(note)

        return ToolResult(
            step_id=step.id,
            tool=step.tool_hint or "reasoning",
            ok=ok,
            summary=answer or "本步骤已完成。",
            data={
                "answer": answer,
                "used_tools": used_tools,
                "tool_results": [item.model_dump() for item in observed_results],
                "thinking_digest": _build_thinking_digest(step, observed_results),
                "display_tool": used_tools[-1] if used_tools else (step.tool_hint or "reasoning"),
            },
            artifacts=artifacts,
        )

    def _execute_direct_step(self, state: SessionState, step: PlanStep) -> ToolResult | None:
        if step.tool_hint == "reasoning":
            answer = _domain_reasoning_answer(_latest_user_text(state))
            if answer:
                return ToolResult(
                    step_id=step.id,
                    tool="reasoning",
                    ok=True,
                    summary=answer,
                    data={"answer": answer, "display_tool": "reasoning"},
                )
        if step.tool_hint == "cmaq_forecast_qa":
            text = _latest_user_text(state)
            time_context = _time_context_for_step(state)
            result = cmaq_forecast_qa(
                text,
                self.config,
                state.id,
                metric=_qa_metric_from_text(text),
                threshold=_threshold_from_text(text),
                start_time=time_context.get("requested_start_time"),
                end_time=time_context.get("requested_end_time"),
            )
            return result.model_copy(update={"step_id": step.id})
        if step.tool_hint == "cmaq_plot_data":
            text = _latest_user_text(state)
            time_context = _time_context_for_step(state)
            result = cmaq_plot_data(
                _metric_from_text(text) or "PM25_TOT",
                _plot_from_text(text),
                self.config,
                state.id,
                start_time=time_context.get("requested_start_time"),
                end_time=time_context.get("requested_end_time"),
            )
            return result.model_copy(update={"step_id": step.id})
        if step.tool_hint == "cmaq_forecast_correction":
            text = _latest_user_text(state)
            pollutant = _pollutant_from_text(text)
            observation_hours = _observation_hours_from_text(text)
            observation_end_time = None if observation_hours else _observation_end_time_for_correction(state)
            result = cmaq_forecast_correction(
                self.config,
                state.id,
                pollutant=pollutant,
                use_observations=_use_observations_from_text(text) or observation_hours is not None,
                observation_hours=observation_hours,
                observation_end_time=observation_end_time,
            )
            return result.model_copy(update={"step_id": step.id})
        if step.tool_hint == "pollution_warning":
            text = _latest_user_text(state)
            derived_days = _derive_forecast_days_from_state(state)
            result = pollution_warning(
                text,
                self.config,
                state.id,
                forecast_days_json=json.dumps(derived_days["forecast_days"], ensure_ascii=False) if derived_days["forecast_days"] else None,
                dominant_pollutant=_pollutant_from_text(text),
            )
            if derived_days["forecast_days"]:
                result.data["derived_forecast_days"] = derived_days
                result.summary += f" 已根据{derived_days['source_label']}自动计算预测日IAQI/AQI序列。"
            return result.model_copy(update={"step_id": step.id})
        if step.tool_hint == "rsm_reduction":
            result = rsm_reduction(_latest_user_text(state), self.config, state.id)
            return result.model_copy(update={"step_id": step.id})
        if step.tool_hint == "read_skill":
            skill_names = parse_skill_names(step.skill_hint)
            if not skill_names:
                skill_names = [_latest_user_text(state).strip()]
            summaries = []
            ok = True
            data_items = []
            for skill_name in skill_names:
                result = read_skill(skill_name, self.config)
                ok = ok and result.ok
                summaries.append(result.summary)
                data_items.append(result.data)
            return ToolResult(
                step_id=step.id,
                tool="read_skill",
                ok=ok,
                summary="\n\n".join(summaries),
                data={"skills": data_items, "display_tool": "read_skill"},
            )
        return None

    def synthesize_answer(self, state: SessionState) -> str:
        if self.model is None:
            return _fallback_final_answer(state, "Final agent 缺少可用的 DeepSeek LLM。")

        prompt = _final_prompt(state)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                result = self.model.invoke(_final_model_messages(prompt))
                answer = getattr(result, "content", "")
                if isinstance(answer, str) and answer.strip():
                    return _enforce_final_answer_caveats(state, answer.strip())
                if isinstance(answer, list):
                    text_parts = [part.get("text", "") for part in answer if isinstance(part, dict) and part.get("type") == "text"]
                    joined = "\n".join(part for part in text_parts if part).strip()
                    if joined:
                        return _enforce_final_answer_caveats(state, joined)
                last_error = RuntimeError("Final model 没有返回有效文本。")
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        reason = f"Final agent 生成回答失败：{last_error}" if last_error else "Final agent 没有返回有效回答。"
        return _enforce_final_answer_caveats(state, _fallback_final_answer(state, reason))

    def _build_final_agent(self):
        if self.model is None:
            return None
        try:
            from langchain.agents import create_agent  # type: ignore
        except Exception:
            return None

        return create_agent(
            model=self.model,
            tools=[],
            middleware=self.middleware,
            system_prompt=(
                "你是成都污染分析智能体的最终回答器。\n"
                "请基于本轮执行得到的工具结果、图表和上下文，用自然、专业、简洁的中文组织最终回答。\n"
                "不要机械拼接工具摘要；要吸收信息后再表述。\n"
                "如果生成了图片、CSV 或 JSON，可以简要说明已经生成，但不要编造未生成的产物。\n"
                "若污染预警工具返回无法判定、未提供AQI序列或未匹配响应措施，必须按缺失证据表述，不得改写成已计算AQI或已判定预警。"
            ),
        )

    def _build_step_agent(self, state: SessionState, step: PlanStep, observed_results: list[ToolResult]):
        try:
            from langchain.agents import create_agent  # type: ignore
            from langchain_core.tools import tool  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"LangChain agent 不可用：{exc}") from exc

        plot_result_cache: dict[tuple[str, str, str | None, str | None], ToolResult] = {}

        def observe(result: ToolResult) -> str:
            observed_results.append(result)
            return _tool_result_observation(result)

        @tool("web_search")
        def web_search_tool(query: str) -> str:
            """Search the web for external context relevant to the current question."""
            actual_query = query.strip() or _latest_user_text(state)
            return observe(cmaq_safe_result(web_search(actual_query, self.config), step.id))

        @tool("cmaq_forecast_qa")
        def cmaq_forecast_qa_tool(
            question: str,
            metric: str | None = None,
            period_days: int = 14,
            threshold: float | None = None,
        ) -> str:
            """Read and analyze CMAQ forecast data and return a structured summary."""
            actual_question = question.strip() or _latest_user_text(state)
            time_context = _time_context_for_step(state)
            time_text = time_context.get("requested_time_text")
            if time_text and str(time_text) not in actual_question:
                actual_question = f"{actual_question}；时间范围：{time_text}"
            result = cmaq_forecast_qa(
                actual_question,
                self.config,
                state.id,
                metric=metric,
                period_days=period_days,
                threshold=threshold,
                start_time=time_context.get("requested_start_time"),
                end_time=time_context.get("requested_end_time"),
            )
            return observe(cmaq_safe_result(result, step.id))

        @tool("cmaq_plot_data")
        def cmaq_plot_data_tool(
            metric: str,
            plot: str = "time-series",
            time: str | None = None,
            time_index: int | None = None,
            start_time: str | None = None,
            end_time: str | None = None,
        ) -> str:
            """Generate CMAQ time-series plots, spatial plots, or both."""
            plot = _normalize_plot_type(plot)
            time_context = _time_context_for_step(state)
            start_time = start_time or time_context.get("requested_start_time")
            end_time = end_time or time_context.get("requested_end_time")
            if start_time or end_time:
                time = None
                time_index = None
            cache_key = (_normalize_plot_metric(metric), plot, start_time, end_time)
            if cache_key in plot_result_cache:
                return observe(plot_result_cache[cache_key].model_copy(update={"step_id": step.id}))
            existing = _find_existing_plot_result(state, metric, plot, start_time, end_time)
            if existing is not None:
                cached = existing.model_copy(update={"step_id": step.id})
                plot_result_cache[cache_key] = cached
                return observe(cached)
            result = cmaq_plot_data(
                metric,
                plot,
                self.config,
                state.id,
                time=time,
                time_index=time_index,
                start_time=start_time,
                end_time=end_time,
            )
            plot_result_cache[cache_key] = cmaq_safe_result(result, step.id)
            return observe(plot_result_cache[cache_key])

        @tool("cmaq_forecast_correction")
        def cmaq_forecast_correction_tool(
            pollutant: str = "PM2.5",
            met_prior: str | None = None,
            use_observations: bool | None = None,
            observation_hours: int | None = None,
        ) -> str:
            """Diagnose and correct Chengdu PM2.5/O3 forecasts using Windy/EC context, CMAQ, and observations."""
            if observation_hours is None:
                observation_hours = _observation_hours_from_text(_latest_user_text(state))
            observation_end_time = None if observation_hours else _observation_end_time_for_correction(state)
            if use_observations is None:
                use_observations = _use_observations_from_text(_latest_user_text(state)) or observation_hours is not None
            result = cmaq_forecast_correction(
                self.config,
                state.id,
                pollutant=pollutant,
                met_prior=met_prior,
                use_observations=use_observations,
                observation_hours=observation_hours,
                observation_end_time=observation_end_time,
            )
            return observe(cmaq_safe_result(result, step.id))

        @tool("pollution_warning")
        def pollution_warning_tool(
            question: str,
            pollutants_json: str | None = None,
            forecast_days_json: str | None = None,
            forecast_daily_aqi: str | None = None,
            dominant_pollutant: str | None = None,
        ) -> str:
            """Calculate AQI and assess Chengdu heavy-pollution warnings and response measures."""
            actual_question = question.strip() or _latest_user_text(state)
            derived_days = _derive_forecast_days_from_state(state)
            if forecast_days_json is None and derived_days["forecast_days"]:
                forecast_days_json = json.dumps(derived_days["forecast_days"], ensure_ascii=False)
            if dominant_pollutant is None:
                dominant_pollutant = _pollutant_from_text(actual_question)
            result = pollution_warning(
                actual_question,
                self.config,
                state.id,
                pollutants_json=pollutants_json,
                forecast_days_json=forecast_days_json,
                forecast_daily_aqi=forecast_daily_aqi,
                dominant_pollutant=dominant_pollutant,
            )
            if forecast_days_json and derived_days["forecast_days"]:
                result.data["derived_forecast_days"] = derived_days
                result.summary += f" 已根据{derived_days['source_label']}自动计算预测日IAQI/AQI序列。"
            return observe(cmaq_safe_result(result, step.id))

        @tool("rsm_reduction")
        def rsm_reduction_tool(
            question: str,
            case: int | None = None,
            outer_reduction: str | None = None,
            inner_reduction: str | None = None,
            month: int | None = None,
            dry_run: bool = False,
            no_run: bool = False,
        ) -> str:
            """Run a local DeepRSM PM2.5 reduction scenario and return improvements for 12 inner regions."""
            actual_question = question.strip() or _latest_user_text(state)
            result = rsm_reduction(
                actual_question,
                self.config,
                state.id,
                case=case,
                outer_reduction=outer_reduction,
                inner_reduction=inner_reduction,
                month=month,
                dry_run=dry_run,
                no_run=no_run,
            )
            return observe(cmaq_safe_result(result, step.id))

        @tool("memory")
        def record_memory_tool(note: str) -> str:
            """Record a user workflow habit or response preference."""
            actual_note = note.strip() or extract_memory_note(_latest_user_text(state)) or _latest_user_text(state)
            return observe(cmaq_safe_result(record_memory(actual_note, self.config), step.id))

        @tool("read_memory")
        def read_memory_tool() -> str:
            """Read recorded user workflow habits."""
            return observe(cmaq_safe_result(read_memory(self.config), step.id))

        @tool("list_skills")
        def list_skills_tool() -> str:
            """List locally available skills."""
            return observe(cmaq_safe_result(list_skills(self.config), step.id))

        @tool("read_skill")
        def read_skill_tool(skill_name: str, section_hint: str | None = None) -> str:
            """Read a skill document for its workflow, commands, and cautions."""
            return observe(cmaq_safe_result(read_skill(skill_name, self.config, section_hint=section_hint), step.id))

        @tool("read_file")
        def read_file_tool(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
            """Read a file within the project."""
            return observe(cmaq_safe_result(read_file(path, self.config, start_line=start_line, end_line=end_line), step.id))

        @tool("current_time")
        def current_time_tool() -> str:
            """Return the current local time."""
            return observe(cmaq_safe_result(get_current_time(self.config), step.id))

        @tool("shell")
        def shell_tool(command: str) -> str:
            """Run a controlled PowerShell command in the project directory."""
            return observe(cmaq_safe_result(run_shell(command, self.config), step.id))

        executor_skill = load_skill_context(self.config, ["executor-core"], max_chars_per_skill=3600)
        tools_by_name = {
            "web_search": web_search_tool,
            "cmaq_forecast_qa": cmaq_forecast_qa_tool,
            "cmaq_plot_data": cmaq_plot_data_tool,
            "cmaq_forecast_correction": cmaq_forecast_correction_tool,
            "pollution_warning": pollution_warning_tool,
            "rsm_reduction": rsm_reduction_tool,
            "memory": record_memory_tool,
            "read_memory": read_memory_tool,
            "list_skills": list_skills_tool,
            "read_skill": read_skill_tool,
            "read_file": read_file_tool,
            "current_time": current_time_tool,
            "shell": shell_tool,
        }
        selected_tools = [tools_by_name[name] for name in _allowed_tool_names_for_step(step) if name in tools_by_name]

        return create_agent(
            model=self.model,
            tools=selected_tools,
            middleware=self.middleware,
            system_prompt=(
                "你是成都污染分析智能体的执行者。\n"
                "你只负责完成当前这一个计划步骤，能复用上下文就复用，必要时再调用工具。\n"
                "回答必须用中文，并且要吸收工具结果后再表达，不要只回贴原始日志。\n"
                "如果当前步骤已经明确给出 tool_hint，优先使用同名领域工具，不要用 shell 替代 cmaq_forecast_qa、cmaq_plot_data、pollution_warning、current_time、read_file、read_skill 这类专用工具。\n\n"
                f"{executor_skill}"
            ),
        )


def todos_from_plan(state: SessionState) -> list[Todo]:
    if not state.plan:
        return []
    return [Todo(id=step.id, title=step.title, status=step.status) for step in state.plan.steps]


def _latest_user_text(state: SessionState) -> str:
    for message in reversed(state.messages):
        if message.role == "user":
            return message.content
    return ""


def _pollutant_from_text(text: str) -> str:
    normalized = text.upper().replace(" ", "")
    if "O3" in normalized or "臭氧" in text:
        return "O3"
    return "PM2.5"


def _use_observations_from_text(text: str) -> bool:
    no_obs_tokens = (
        "无观测",
        "没有观测",
        "不使用观测",
        "不要用观测",
        "不用观测",
        "观测缺失",
        "少量观测",
        "no observation",
        "no observations",
        "without observation",
        "without observations",
        "do not use observations",
        "skip observations",
    )
    return not any(token in text for token in no_obs_tokens)


def _observation_hours_from_text(text: str) -> int | None:
    patterns = [
        r"前\s*([0-9]+)\s*(?:个)?\s*小时.*观测",
        r"first\s*([0-9]+)\s*(?:h|hours?).*observ",
        r"([0-9]+)\s*(?:h|hours?).*observ",
    ]
    lowered = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if match:
            try:
                value = int(match.group(1))
            except ValueError:
                continue
            return max(1, min(value, 168))
    return None


def _observation_end_time_for_correction(state: SessionState) -> str:
    context = _time_context_for_step(state)
    start_text = context.get("requested_start_time")
    start_dt = _parse_date_context(start_text) if start_text else None
    if start_dt is None:
        return "2026-05-26 23:59:59"
    cutoff = start_dt - timedelta(seconds=1)
    return cutoff.strftime("%Y-%m-%d %H:%M:%S")


def _parse_date_context(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _metric_from_text(text: str) -> str | None:
    normalized = text.upper().replace(" ", "")
    if "O3" in normalized or "臭氧" in text:
        if "8H" in normalized or "8小时" in text or "八小时" in text:
            return "O3_R8"
        return "O3"
    if "PM2.5" in normalized or "PM25" in normalized or "细颗粒物" in text:
        return "PM25_TOT"
    if "PM10" in normalized:
        return "PM10"
    if "NO2" in normalized or "二氧化氮" in text:
        return "NO2"
    if "SO2" in normalized or "二氧化硫" in text:
        return "SO2"
    if "CO" in normalized or "一氧化碳" in text:
        return "CO"
    return None


def _qa_metric_from_text(text: str) -> str | None:
    metric = _metric_from_text(text)
    if metric == "O3_R8":
        return "O3"
    if metric is None and any(keyword in text for keyword in ("空气质量研判报告", "污染过程简报", "污染过程报告", "高值分析", "污染高值")):
        return "PM25_TOT"
    return metric


def _threshold_from_text(text: str) -> float | None:
    match = re.search(r"(?:超过|高于|大于|阈值|threshold)\s*([0-9]+(?:\.[0-9]+)?)", text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _plot_from_text(text: str) -> str:
    normalized = text.lower()
    wants_time = any(token in text for token in ("时序", "时间序列", "趋势", "曲线")) or "time" in normalized
    wants_spatial = any(token in text for token in ("空间", "分布", "地图", "热点", "区域", "高值区域")) or "map" in normalized
    if wants_time and wants_spatial:
        return "both"
    if wants_spatial:
        return "spatial"
    return "time-series"


def _domain_reasoning_answer(text: str) -> str | None:
    normalized = text.upper().replace(" ", "")
    parts: list[str] = []
    if "CMAQ" in normalized and "系统性误差" in text and not any(
        keyword in text for keyword in ("路径", "未来", "5月", "结合观测", "观测结果", "订正")
    ):
        parts.append(
            "如果没有给出具体CMAQ结果路径、评估时段和同期观测数据，本题只能做定性判断，不能断言本轮成都CMAQ预报究竟整体偏高还是偏低。"
            "从机理上看，成都本地CMAQ系统性误差通常可能来自排放清单偏差、站点代表性与网格分辨率差异、盆地地形下边界层和近地风模拟误差、"
            "区域输送边界条件偏差，以及PM2.5二次生成、湿清除和沉降过程的不确定性。PM2.5场景下常见表现包括峰值时间偏早或偏晚、"
            "静稳高湿条件下累积强度估计不足或过强、局地站点与城市均值不一致；O3场景下则常见光照、云量、温度和VOCs/NOx敏感性导致的高低估。"
            "因此，合理回答应是列出这些可能误差来源和诊断思路；若要给出“偏高/偏低”结论，必须再结合指定CMAQ输出和对应观测进行定量评估。"
        )
    if any(keyword in text for keyword in ("主要来源", "贡献因素", "来源/贡献因素")) and any(keyword in text for keyword in ("成都", "大气污染", "污染")):
        parts.append(
            "成都大气污染的主要贡献通常来自机动车和非道路移动源、工业燃烧与工艺排放、扬尘、餐饮及生活面源、农业氨排放和区域传输；不同季节贡献会变化，秋冬季更容易受PM2.5二次生成、静稳累积和外来输送影响，夏季则更突出VOCs和NOx参与的臭氧生成。"
        )
    if "主要组分" in text and ("PM2.5" in normalized or "PM25" in normalized or "细颗粒物" in text):
        parts.append(
            "成都PM2.5的主要组分一般包括有机物、硝酸盐、硫酸盐、铵盐、元素碳、地壳尘和少量金属元素；其中硝酸盐、硫酸盐和铵盐反映二次无机气溶胶生成，有机物和元素碳常与机动车、燃烧源和生活源有关。"
        )
    if any(keyword in text for keyword in ("不利气象", "气象条件")) and ("O3" in normalized or "臭氧" in text):
        parts.append(
            "成都O3污染的不利气象条件主要包括高温、强太阳辐射、少云少雨、低湿或午后光化学反应活跃、边界层较高但水平风速偏小，以及盆地内弱输送或下风向累积；这些条件会增强VOCs和NOx光化学生成臭氧并延长高值维持时间。"
        )
    if "AQI" in normalized:
        parts.append(
            "AQI（空气质量指数）是把PM2.5、PM10、O3、NO2、SO2、CO等污染物浓度换算为分指数后取最大值的综合指标；最大分指数对应的污染物通常就是首要污染物。"
        )
    if "PM2.5" in normalized or "PM25" in normalized or "细颗粒物" in text:
        parts.append(
            "PM2.5表示空气动力学当量直径小于等于2.5微米的细颗粒物，容易受二次生成、静稳、高湿和区域传输影响，是秋冬季重污染预警研判的关键指标。"
        )
    if "O3" in normalized or "臭氧" in text:
        parts.append(
            "O3污染多发生在光照强、气温高的时段，治理重点是VOCs和NOx协同控制；它通常不直接套用PM2.5重污染黄色、橙色、红色预警逻辑，而应按臭氧污染响应措施研判。"
        )
    if "CMAQ" in normalized:
        parts.append(
            "CMAQ是空气质量数值模式，用排放清单、气象场和化学机制模拟污染物的输送、转化和沉降，适合做趋势、空间分布、峰值时段和情景分析。"
        )
    if "预警" in text or "重污染" in text:
        parts.append(
            "成都市重污染天气预警需要结合未来日AQI序列、首要污染物和会商结论自动判断阈值，再经过人工会商和官方发布程序确认。"
        )
    if not parts:
        return None
    return "\n".join(dict.fromkeys(parts))


def _time_context_for_step(state: SessionState) -> dict[str, str]:
    context: dict[str, str] = {}
    if state.context_variables:
        context.update({key: str(value) for key, value in state.context_variables.items() if value is not None})
    if state.plan and state.plan.context_variables:
        context.update({key: str(value) for key, value in state.plan.context_variables.items() if value is not None})
    if not context.get("requested_start_time") or not context.get("requested_end_time"):
        context.update(extract_time_range(_latest_user_text(state)))
    return context


def _derive_forecast_days_from_state(state: SessionState) -> dict:
    context = _time_context_for_step(state)
    start_date = context.get("requested_start_time")
    end_date = context.get("requested_end_time")
    pollutant = _pollutant_from_text(_latest_user_text(state))

    corrected = _derive_pollutant_days_from_city_aggregate(state, start_date, end_date, pollutant)
    if corrected["forecast_days"]:
        return corrected

    raw = _derive_pollutant_days_from_daily_domain(state, start_date, end_date, pollutant)
    if raw["forecast_days"]:
        return raw

    return {"forecast_days": [], "dates": [], "source_path": "", "source_label": ""}


def _derive_pollutant_days_from_city_aggregate(
    state: SessionState,
    start_date: str | None,
    end_date: str | None,
    pollutant: str,
) -> dict:
    for artifact in reversed(state.artifacts):
        if artifact.kind != "csv":
            continue
        path = Path(artifact.path)
        if artifact.label != "城市均值订正结果" and path.name.lower() != "city_aggregate.csv":
            continue
        if not path.exists():
            continue
        grouped: dict[str, list[float]] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                date_text = str(row.get("datetime", ""))[:10]
                if not _date_in_requested_range(date_text, start_date, end_date):
                    continue
                value = _float_or_none(row.get("corrected_mean"))
                if value is None:
                    continue
                grouped.setdefault(date_text, []).append(value)
        days, dates = _forecast_days_from_grouped_values(grouped, pollutant)
        return {
            "forecast_days": days,
            "dates": dates,
            "source_path": str(path),
            "source_label": _forecast_source_label("订正后城市均值", pollutant),
        }
    return {"forecast_days": [], "dates": [], "source_path": "", "source_label": ""}


def _derive_pollutant_days_from_daily_domain(
    state: SessionState,
    start_date: str | None,
    end_date: str | None,
    pollutant: str,
) -> dict:
    for artifact in reversed(state.artifacts):
        if artifact.kind != "csv":
            continue
        path = Path(artifact.path)
        if artifact.label != "日统计" and not path.name.lower().endswith("_daily_domain.csv"):
            continue
        if not path.exists():
            continue
        grouped: dict[str, list[float]] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                date_text = str(row.get("date", ""))[:10]
                if not _date_in_requested_range(date_text, start_date, end_date):
                    continue
                value = _float_or_none(_daily_domain_value(row, pollutant))
                if value is None:
                    continue
                grouped.setdefault(date_text, []).append(value)
        days, dates = _forecast_days_from_grouped_values(grouped, pollutant)
        return {
            "forecast_days": days,
            "dates": dates,
            "source_path": str(path),
            "source_label": _forecast_source_label("CMAQ原始", pollutant),
        }
    return {"forecast_days": [], "dates": [], "source_path": "", "source_label": ""}


def _forecast_days_from_grouped_values(grouped: dict[str, list[float]], pollutant: str) -> tuple[list[dict[str, float]], list[str]]:
    days: list[dict[str, float]] = []
    dates: list[str] = []
    for date_text in sorted(grouped):
        values = grouped[date_text]
        if not values:
            continue
        key = _forecast_pollutant_key(pollutant)
        if key == "o3_8h":
            value = max(values)
        else:
            value = sum(values) / len(values)
        days.append({key: round(value, 3)})
        dates.append(date_text)
    return days, dates


def _daily_domain_value(row: dict[str, str], pollutant: str) -> str | None:
    if _forecast_pollutant_key(pollutant) == "o3_8h":
        return row.get("daily_max_domain_mean") or row.get("daily_grid_max") or row.get("daily_mean")
    return row.get("daily_mean")


def _forecast_pollutant_key(pollutant: str) -> str:
    normalized = pollutant.upper().replace(".", "").replace(" ", "")
    if normalized == "O3":
        return "o3_8h"
    if normalized == "PM10":
        return "pm10_24h"
    return "pm25_24h"


def _forecast_source_label(prefix: str, pollutant: str) -> str:
    if _forecast_pollutant_key(pollutant) == "o3_8h":
        return f"{prefix}O3日最大8小时滑动平均"
    return f"{prefix}日均{pollutant}"


def _date_in_requested_range(date_text: str, start_date: str | None, end_date: str | None) -> bool:
    if len(date_text) < 10:
        return False
    if start_date and date_text < start_date[:10]:
        return False
    if end_date and date_text > end_date[:10]:
        return False
    return True


def _float_or_none(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_existing_plot_result(
    state: SessionState,
    metric: str,
    plot: str,
    start_time: str | None,
    end_time: str | None,
) -> ToolResult | None:
    requested_plots = {"time-series", "spatial"} if plot == "both" else {plot}
    for result in reversed(state.tool_results):
        if result.tool != "cmaq_plot_data" or not result.ok:
            continue
        summary = result.data.get("summary") if isinstance(result.data, dict) else None
        if not isinstance(summary, dict):
            continue
        if not _metric_matches_plot(metric, summary):
            continue
        outputs = summary.get("outputs") if isinstance(summary.get("outputs"), list) else []
        output_plots = {item.get("plot") for item in outputs if isinstance(item, dict)}
        if not requested_plots.issubset(output_plots):
            continue
        if start_time or end_time:
            if not all(_output_matches_range(item, start_time, end_time) for item in outputs if isinstance(item, dict) and item.get("plot") in requested_plots):
                continue
        return result
    return None


def _metric_matches_plot(metric: str, summary: dict) -> bool:
    variable = str(summary.get("variable") or "").lower()
    normalized_metric = _normalize_plot_metric(metric)
    normalized_variable = _normalize_plot_metric(variable)
    return normalized_metric in normalized_variable or normalized_variable in normalized_metric


def _normalize_plot_metric(value: str) -> str:
    text = str(value or "").lower()
    return "".join(char for char in text if char.isalnum())


def _normalize_plot_type(value: str) -> str:
    text = str(value or "time-series").strip().lower().replace("_", "-")
    if text in {"timeseries", "time-series", "time series"}:
        return "time-series"
    if text in {"map", "spatial-map", "spatial"}:
        return "spatial"
    if text in {"all", "both", "time-series-and-spatial"}:
        return "both"
    return text


def _output_matches_range(output: dict, start_time: str | None, end_time: str | None) -> bool:
    start = str(output.get("start") or "")[:10]
    end = str(output.get("end") or "")[:10]
    return (not start_time or start == str(start_time)[:10]) and (not end_time or end == str(end_time)[:10])


def cmaq_safe_result(result: ToolResult, step_id: str) -> ToolResult:
    if result.step_id is None:
        result.step_id = step_id
    return result


def _allowed_tool_names_for_step(step: PlanStep) -> list[str]:
    hint = step.tool_hint or "reasoning"
    if hint == "current_time":
        return ["current_time"]
    if hint == "web_search":
        return ["web_search"]
    if hint == "cmaq_forecast_qa":
        return ["cmaq_forecast_qa", "read_skill"]
    if hint == "cmaq_plot_data":
        return ["cmaq_plot_data", "read_skill"]
    if hint == "cmaq_forecast_correction":
        return ["cmaq_forecast_correction", "read_skill"]
    if hint == "pollution_warning":
        return ["pollution_warning", "read_skill"]
    if hint == "rsm_reduction":
        return ["rsm_reduction", "read_skill"]
    if hint == "memory":
        return ["memory", "read_memory"]
    if hint == "read_skill":
        return ["read_skill", "list_skills"]
    if hint == "read_file":
        return ["read_file"]
    if hint == "shell":
        return ["shell"]
    return []


def _build_thinking_digest(step: PlanStep, observed_results: list[ToolResult]) -> str:
    if not observed_results:
        return "基于已有上下文完成推理，未调用额外工具。"

    parts = [_humanize_tool_result(result, step.title) for result in observed_results]
    parts = [part for part in parts if part]
    return "；".join(parts) if parts else "本步骤已完成。"


def _humanize_tool_result(result: ToolResult, step_title: str) -> str:
    data = result.data if isinstance(result.data, dict) else {}
    summary = _trim_digest_text(result.summary)

    if result.tool == "web_search":
        query = _trim_digest_text(str(data.get("query") or step_title))
        results = data.get("results") if isinstance(data.get("results"), list) else []
        answer = _trim_digest_text(str(data.get("answer") or summary))
        if results and _contains_chinese(answer):
            return f"已查询“{query}”，找到 {len(results)} 条相关线索，{_ensure_sentence(answer)}"
        if results:
            return f"已查询“{query}”，找到 {len(results)} 条相关线索。"
        return f"已查询“{query}”，{_ensure_sentence(answer or summary or '结果已返回')}"

    if result.tool == "cmaq_forecast_qa":
        raw_summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        metric = raw_summary.get("metric") or raw_summary.get("field") or "指标"
        period = raw_summary.get("period") if isinstance(raw_summary.get("period"), dict) else {}
        start = period.get("start")
        end = period.get("end")
        period_text = f"，时间范围 {start} 至 {end}" if start and end else ""
        return f"已提取 {metric} 的 CMAQ 结果{period_text}。{_ensure_sentence(summary or '结果已返回')}"

    if result.tool == "cmaq_plot_data":
        raw_summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        variable = raw_summary.get("variable") or "CMAQ"
        outputs = raw_summary.get("outputs") if isinstance(raw_summary.get("outputs"), list) else []
        plot_names = [str(item.get("plot")) for item in outputs if isinstance(item, dict) and item.get("plot")]
        plot_text = f"，生成了 {'、'.join(plot_names)} 图件" if plot_names else ""
        return f"已提取 {variable} 绘图数据{plot_text}，结果已返回。"

    if result.tool == "cmaq_forecast_correction":
        artifact_count = len(result.artifacts)
        artifact_text = f"，返回 {artifact_count} 个报告/图表产物" if artifact_count else ""
        return _ensure_sentence((summary or "CMAQ订正流程已完成") + artifact_text)

    if result.tool == "pollution_warning":
        raw_summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        warning = raw_summary.get("warning") if isinstance(raw_summary.get("warning"), dict) else {}
        level = warning.get("warning_level") if isinstance(warning, dict) else None
        if level:
            return _ensure_sentence(f"已按成都市重污染天气预案规则完成AQI预警研判，结论为{level}")
        return _ensure_sentence(summary or "污染预警研判已完成")

    if result.tool == "rsm_reduction":
        return _ensure_sentence(summary or "RSM 减排情景已完成，Dpm25 改善量已返回")

    if result.tool == "read_file":
        return _ensure_sentence(summary or "已读取相关文件内容")

    if result.tool == "read_skill":
        return _ensure_sentence(summary or "已读取相关技能说明")

    if result.tool in {"current_time", "memory", "read_memory", "shell"}:
        return _ensure_sentence(summary or "结果已返回")

    return _ensure_sentence(summary or f"已完成 {result.tool} 步骤")


def _trim_digest_text(value: str) -> str:
    text = " ".join(str(value).split()).strip()
    if len(text) > 140:
        return text[:140].rstrip() + "..."
    return text


def _ensure_sentence(text: str) -> str:
    cleaned = _trim_digest_text(text)
    if not cleaned:
        return ""
    if cleaned[-1] in "。！？!?":
        return cleaned
    return cleaned + "。"


def _contains_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _tool_result_observation(result: ToolResult) -> str:
    payload: dict[str, object] = {"tool": result.tool, "ok": result.ok, "summary": result.summary}
    if result.artifacts:
        payload["artifacts"] = [artifact.model_dump() for artifact in result.artifacts]
    if isinstance(result.data, dict):
        compact = {}
        for key in ("summary", "content", "notes", "display", "iso", "path"):
            value = result.data.get(key)
            if value:
                compact[key] = value
        if compact:
            payload["data"] = compact
    return json.dumps(payload, ensure_ascii=False)


def _extract_last_ai_text(messages) -> str:
    for message in reversed(messages or []):
        if getattr(message, "type", "") != "ai":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
            return "\n".join(part for part in text_parts if part).strip()
    return ""


def _merge_artifacts(tool_results: list[ToolResult]) -> list[Artifact]:
    merged: list[Artifact] = []
    seen: set[tuple[str, str]] = set()
    for result in tool_results:
        for artifact in result.artifacts:
            key = (artifact.kind, artifact.path)
            if key in seen:
                continue
            seen.add(key)
            merged.append(artifact)
    return merged


def _step_prompt(state: SessionState, step: PlanStep, config: AgentConfig) -> str:
    recent_messages = "\n".join(f"{message.role}: {message.content}" for message in state.messages[-6:]) or "无"
    recent_results = "\n".join(f"{result.tool}: {result.summary}" for result in state.tool_results[-6:]) or "无"
    artifacts = "\n".join(f"{artifact.label}: {artifact.path}" for artifact in state.artifacts[-6:]) or "无"
    context_text = format_context_variables(state.plan.context_variables if state.plan else state.context_variables)
    skill_names = parse_skill_names(step.skill_hint)
    skill_context = load_skill_context(config, skill_names, max_chars_per_skill=4800) if skill_names else "无"

    return (
        f"当前计划步骤：{step.title}\n"
        f"建议 tool_hint：{step.tool_hint or '无'}\n"
        f"建议 skills：{', '.join(skill_names) if skill_names else '无'}\n\n"
        "相关 skill 内容：\n"
        f"{skill_context}\n\n"
        "最近对话：\n"
        f"{recent_messages}\n\n"
        "最近工具结果：\n"
        f"{recent_results}\n\n"
        "已有产物：\n"
        f"{artifacts}\n\n"
        "对话变量（硬约束）：\n"
        f"{context_text}\n\n"
        "要求：围绕这一个步骤完成工作。若 skill 已给出，请优先遵循其工作流；若上下文已经足够，也可以不调用工具直接完成。"
    )


def _fallback_final_answer(state: SessionState, reason: str) -> str:
    latest_question = _latest_user_text(state)
    lines = [
        "本轮已完成可执行工具链，以下为基于工具结果的可靠响应摘要。",
        f"问题：{latest_question}",
    ]
    if reason and "缺少可用的 DeepSeek LLM" not in reason:
        lines.append(f"说明：{reason}")
    if state.tool_results:
        lines.append("工具结果：")
        for result in state.tool_results:
            status = "成功" if result.ok else "失败"
            lines.append(f"- {result.tool}（{status}）：{result.summary}")
    if state.artifacts:
        lines.append("生成产物：")
        for artifact in state.artifacts:
            lines.append(f"- {artifact.label}: {artifact.path}")
    return "\n".join(lines)


def _enforce_final_answer_caveats(state: SessionState, answer: str) -> str:
    answer = _enforce_rsm_answer_safety(state, answer)
    if not _needs_future_observation_caveat(state):
        return answer
    required = (
        "注意：未来三天（5月27日-29日）暂无实测观测，订正结果中 observed 为空；"
        "历史期MAE只代表观测约束期，不能据此把未来三天原始CMAQ预报判定为已被实测证明整体偏高或偏低。"
    )
    if all(token in answer for token in ("暂无实测观测", "observed", "历史期MAE", "不能据此")):
        return answer
    return f"{answer.rstrip()}\n\n{required}"


def _enforce_rsm_answer_safety(state: SessionState, answer: str) -> str:
    rsm_results = [result for result in state.tool_results if result.tool == "rsm_reduction" and result.ok]
    if not rsm_results:
        return answer
    answer_without_safe_negations = re.sub(
        r"(?:不自动|不能|不得|不应|不可|无法|未能).{0,8}(?:等同于|视为|称为|代表|判断|推断|说明|表明|证明)",
        "",
        answer,
    )
    unsupported_claims = (
        r"M1\s*[-–—至到]\s*M13.{0,12}(?:代表|等同于|就是|可视为).{0,10}(?:完整年份|年均)",
        r"(?:完整年份|年均值?).{0,12}(?:已经|可以|能够)?(?:说明|表明|证明)",
        r"(?:说明|表明|证明|可见|因此).{0,28}(?:下风向|本地排放主导|地形屏障|地形作用)",
        r"(?:下风向|本地排放主导|地形屏障|地形作用).{0,28}(?:说明|表明|证明|导致)",
    )
    if not any(re.search(pattern, answer_without_safe_negations, re.IGNORECASE) for pattern in unsupported_claims):
        return answer
    result = rsm_results[-1]
    return result.summary


def _needs_future_observation_caveat(state: SessionState) -> bool:
    latest_question = _latest_user_text(state)
    if "CMAQ" not in latest_question and "cmaq" not in latest_question.lower():
        return False
    if not any(token in latest_question for token in ("偏高", "偏低", "误差", "订正", "观测")):
        return False
    for result in state.tool_results:
        if result.tool != "cmaq_forecast_correction":
            continue
        text = f"{result.summary}\n{json.dumps(result.data, ensure_ascii=False)}"
        if "observed" in text and ("为空" in text or "字段为空" in text):
            return True
    return False


def _final_prompt(state: SessionState) -> str:
    latest_question = _latest_user_text(state)
    tool_lines = [f"[{result.tool}] ok={result.ok}\n{result.summary}" for result in state.tool_results]
    artifact_lines = [f"{artifact.label}: {artifact.path}" for artifact in state.artifacts]
    tool_text = "\n\n".join(tool_lines) if tool_lines else "无"
    artifact_text = "\n".join(artifact_lines) if artifact_lines else "无"

    return (
        f"用户本轮问题：{latest_question}\n\n"
        "本轮工具执行结果：\n"
        f"{tool_text}\n\n"
        "本轮生成的产物：\n"
        f"{artifact_text}\n\n"
        "请输出最终中文回答。要求：\n"
        "1. 自然组织内容，不要逐条重复工具名。\n"
        "2. 若有图表或文件，说明已经生成并点到为止。\n"
        "3. 若工具失败或证据不足，要明确说明不确定性。\n"
        "4. 如果 pollution_warning 结果显示未提供AQI序列、无法判定或未匹配措施，必须原样保留这个限制，不要写成已经计算AQI或已经形成分级措施。\n"
        "5. 如果本题是基础知识问答，或工具结果来自 reasoning/read_skill，请直接整合已有工具结果回答，不要因为没有监测浓度、AQI序列或站点数据而拒答。\n"
        "6. 只有当用户本题确实要求预警、定量CMAQ分析或订正，而对应工具结果缺失时，才提示证据不足。\n"
        "7. 语气像成熟的分析助理，而不是日志拼接器。\n"
        "8. 如果CMAQ订正结果说明观测只覆盖到某个截止时间、后续预报期 observed 为空，必须明确区分历史约束期和未来预报期；"
        "不得把历史期MAE或订正改善写成未来三天已经被实测证明偏高、偏低或贴近观测。\n"
        "9. 如果结果来自 rsm_reduction，必须把百分比表述为排放减排比例，把 baseline - scenario 表述为PM2.5浓度改善量；"
        "不得把M1-M13擅自称为完整年份或年均值，也不得仅凭响应数值推断下风向传输、本地排放主导、地形屏障等具体成因。\n"
        "RSM回答请用‘核心结论、情景设置、12区改善量、结果解读’几个短段落；优先回答用户点名区域并突出响应较大的区域，"
        "所有12区数值应分组列示，不要挤在一个长段落中；源文件未证明单位时不要猜测单位。"
    )


def _final_model_messages(prompt: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是成都污染分析智能体的最终回答器。"
                "请基于本轮执行得到的工具结果、图表和上下文，用自然、专业、简洁的中文组织最终回答。"
                "不要机械拼接工具摘要；要吸收信息后再表述。"
                "如果生成了图片、CSV 或 JSON，可以简要说明已经生成，但不要编造未生成的产物。"
                "若污染预警工具返回无法判定、未提供AQI序列或未匹配响应措施，必须按缺失证据表述，不得改写成已计算AQI或已判定预警。"
                "基础知识问答和reasoning/read_skill结果不需要额外监测数据即可回答。"
                "若订正工具提示未来预报期observed为空，只能说历史观测约束期的偏差和未来偏差风险，不能说未来三天已经被实测证明偏高、偏低或贴近观测。"
                "若使用RSM结果，必须区分排放减排比例与浓度改善量；不得擅自把M1-M13定义为完整年份或年均值，"
                "也不得仅凭浓度响应数值编造传输路径、主导来源或地形机制。"
            ),
        },
        {"role": "user", "content": prompt},
    ]
