from __future__ import annotations

import json
import os
import csv
import importlib.util
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from agent.config import AgentConfig, redact_secrets
from agent.models import Artifact, ToolResult


def _task_dir(config: AgentConfig, session_id: str, group: str) -> Path:
    out_dir = config.output_dir / group / session_id / uuid4().hex[:8]
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _run_python(script: Path, args: list[str], cwd: Path, timeout_seconds: int = 600) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
    )
    return completed.returncode, redact_secrets(completed.stdout), redact_secrets(completed.stderr)


def _parse_last_json(stdout: str) -> dict:
    text = stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
    return {}


def _artifact_from_path(path: str | None, kind: str, label: str) -> Artifact | None:
    if not path:
        return None
    return Artifact(kind=kind, path=str(Path(path).resolve()), label=label)


def cmaq_forecast_qa(
    question: str,
    config: AgentConfig,
    session_id: str,
    metric: str | None = None,
    period_days: int = 14,
    threshold: float | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> ToolResult:
    script = config.skills_dir / "cmaq-forecast-qa" / "scripts" / "analyze_cmaq_question.py"
    out_dir = _task_dir(config, session_id, "cmaq_qa")
    args = [
        "--data-dir",
        str(config.data_dir),
        "--question",
        question,
        "--period-days",
        str(period_days),
        "--out-dir",
        str(out_dir),
    ]
    if metric:
        args.extend(["--metric", metric])
    if threshold is not None:
        args.extend(["--threshold", str(threshold)])
    if start_time:
        args.extend(["--start-time", start_time])
    if end_time:
        args.extend(["--end-time", end_time])

    code, stdout, stderr = _run_python(script, args, script.parent)
    data = _parse_last_json(stdout)
    outputs = data.get("outputs", {}) if isinstance(data, dict) else {}
    artifacts = [
        item
        for item in [
            _artifact_from_path(outputs.get("hourly_domain_csv"), "csv", "小时域统计"),
            _artifact_from_path(outputs.get("daily_domain_csv"), "csv", "日统计"),
            _artifact_from_path(outputs.get("hotspots_csv"), "csv", "热点网格"),
            _artifact_from_path(outputs.get("summary_json"), "json", "问答摘要"),
        ]
        if item is not None
    ]
    summary = _summarize_cmaq_qa(data) if data else (stderr.strip() or stdout.strip())
    if code == 0 and _needs_meteorology_context(question):
        met = _build_meteorology_context(config, out_dir, outputs.get("hourly_domain_csv"), period_days)
        if met:
            artifacts.extend(met["artifacts"])
            summary = f"{summary} {met['summary']}"
            if isinstance(data, dict):
                data["meteorology_context"] = met["data"]
    return ToolResult(
        tool="cmaq_forecast_qa",
        ok=code == 0,
        summary=summary,
        data={"stdout": stdout, "stderr": stderr, "summary": data, "out_dir": str(out_dir.resolve())},
        artifacts=artifacts,
    )


def cmaq_plot_data(
    metric: str,
    plot: str,
    config: AgentConfig,
    session_id: str,
    time: str | None = None,
    time_index: int | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> ToolResult:
    script = config.skills_dir / "cmaq-plot-data" / "scripts" / "plot_cmaq.py"
    out_dir = _task_dir(config, session_id, "cmaq_plots")
    args = [
        "--data-dir",
        str(config.data_dir),
        "--metric",
        metric,
        "--plot",
        plot,
        "--out-dir",
        str(out_dir),
    ]
    if time:
        args.extend(["--time", time])
    if time_index is not None:
        args.extend(["--time-index", str(time_index)])
    if start_time:
        args.extend(["--start-time", start_time])
    if end_time:
        args.extend(["--end-time", end_time])

    code, stdout, stderr = _run_python(script, args, script.parent)
    data = _parse_last_json(stdout)
    artifacts: list[Artifact] = []
    for output in data.get("outputs", []) if isinstance(data, dict) else []:
        png = _artifact_from_path(output.get("png"), "image", f"{output.get('plot', 'plot')} 图")
        csv = _artifact_from_path(output.get("csv"), "csv", "时序 CSV")
        summary_json = _artifact_from_path(output.get("summary_json"), "json", "绘图摘要")
        artifacts.extend(item for item in [png, csv, summary_json] if item is not None)
    summary = _summarize_cmaq_plot(data) if data else (stderr.strip() or stdout.strip())
    return ToolResult(
        tool="cmaq_plot_data",
        ok=code == 0,
        summary=summary,
        data={"stdout": stdout, "stderr": stderr, "summary": data, "out_dir": str(out_dir.resolve())},
        artifacts=artifacts,
    )


def cmaq_forecast_correction(
    config: AgentConfig,
    session_id: str,
    pollutant: str = "PM2.5",
    met_prior: str | None = None,
    use_observations: bool = True,
    observation_hours: int | None = None,
    observation_end_time: str | None = None,
) -> ToolResult:
    script = config.skills_dir / "chengdu-cmaq-forecast-correction" / "scripts" / "run_correction.py"
    out_dir = _task_dir(config, session_id, "cmaq_correction")
    prepared = _prepare_correction_inputs(config, out_dir, pollutant)
    args = [
        "--cmaq-dir",
        str(config.data_dir),
        "--pollutant",
        pollutant,
        "--out",
        str(out_dir),
    ]
    if use_observations:
        if observation_hours:
            obs_dir = _prepare_limited_observations(config, out_dir, pollutant, observation_hours, prepared.get("cmaq_file"))
        elif observation_end_time:
            obs_dir = _prepare_observations_until(config, out_dir, observation_end_time)
        else:
            obs_dir = config.data_dir / "observations_matched"
        args.extend(["--obs-dir", str(obs_dir)])
    if prepared.get("cmaq_file"):
        args.extend(["--cmaq-file", prepared["cmaq_file"]])
    if prepared.get("hotspots_file"):
        args.extend(["--hotspots-file", prepared["hotspots_file"]])
    if met_prior:
        args.extend(["--met-prior", met_prior])

    code, stdout, stderr = _run_python(script, args, config.project_root, timeout_seconds=900)
    artifacts = _correction_artifacts(out_dir)
    summary = _summarize_cmaq_correction(out_dir, stdout, stderr)
    if observation_end_time:
        summary = (
            f"{summary} 观测约束仅使用至 {observation_end_time}；之后预报期的 observed 字段为空。"
            "订正前/后MAE只反映有观测覆盖的历史约束期，不能据此断言未来三天原始预报已被实测证明偏高或偏低；"
            "未来期只能表述为基于历史偏差先验和订正规则的偏差风险/调整方向。"
        )
    return ToolResult(
        tool="cmaq_forecast_correction",
        ok=code == 0,
        summary=summary,
        data={
            "stdout": stdout,
            "stderr": stderr,
            "out_dir": str(out_dir.resolve()),
            "observation_end_time": observation_end_time,
        },
        artifacts=artifacts,
    )


def _prepare_correction_inputs(config: AgentConfig, out_dir: Path, pollutant: str) -> dict[str, str]:
    normalized = pollutant.upper().replace(".", "").replace(" ", "")
    if normalized != "O3":
        return {}

    existing = _find_latest(config.data_dir / "output", "*o3*hourly*domain*.csv")
    if existing is not None:
        hotspots = _find_latest(config.data_dir / "output", "*o3*hotspots*.csv")
        result = {"cmaq_file": str(existing)}
        if hotspots is not None:
            result["hotspots_file"] = str(hotspots)
        return result

    qa_script = config.skills_dir / "cmaq-forecast-qa" / "scripts" / "analyze_cmaq_question.py"
    derived_dir = out_dir / "derived_cmaq"
    derived_dir.mkdir(parents=True, exist_ok=True)
    code, stdout, stderr = _run_python(
        qa_script,
        [
            "--data-dir",
            str(config.data_dir),
            "--question",
            "O3 high value and trend for correction",
            "--metric",
            "O3",
            "--analysis",
            "trend_high_value",
            "--period-days",
            "14",
            "--out-dir",
            str(derived_dir),
        ],
        qa_script.parent,
        timeout_seconds=600,
    )
    data = _parse_last_json(stdout)
    outputs = data.get("outputs", {}) if isinstance(data, dict) else {}
    if code != 0 or not outputs.get("hourly_domain_csv"):
        details = stderr.strip() or stdout.strip() or "unknown error"
        raise RuntimeError(f"无法为O3订正生成CMAQ hourly-domain CSV：{details}")
    result = {"cmaq_file": outputs["hourly_domain_csv"]}
    if outputs.get("hotspots_csv"):
        result["hotspots_file"] = outputs["hotspots_csv"]
    return result


def _prepare_limited_observations(config: AgentConfig, out_dir: Path, pollutant: str, hours: int | None, cmaq_file: str | None = None) -> Path:
    if not hours or hours <= 0:
        return config.data_dir / "observations_matched"
    source_dir = config.data_dir / "observations_matched"
    limited_dir = out_dir / f"observations_first_{hours}h"
    limited_dir.mkdir(parents=True, exist_ok=True)

    station_src = source_dir / "chengdu_stations.csv"
    station_dst = limited_dir / "chengdu_stations.csv"
    if station_src.exists():
        shutil.copyfile(station_src, station_dst)

    obs_src = _find_latest(source_dir, "chengdu_observations_site_hourly_*.csv")
    if obs_src is None:
        return limited_dir

    start_dt = _cmaq_start_datetime(config, pollutant, cmaq_file)
    end_dt = start_dt + timedelta(hours=hours - 1)
    obs_dst = limited_dir / obs_src.name
    with obs_src.open("r", encoding="utf-8-sig", newline="") as src, obs_dst.open("w", encoding="utf-8-sig", newline="") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            dt = _parse_datetime(row.get("datetime"))
            if dt is None:
                continue
            if start_dt <= dt <= end_dt:
                writer.writerow(row)
    return limited_dir


def _prepare_observations_until(config: AgentConfig, out_dir: Path, end_time: str) -> Path:
    end_dt = _parse_datetime(end_time)
    if end_dt is None:
        return config.data_dir / "observations_matched"
    source_dir = config.data_dir / "observations_matched"
    limited_dir = out_dir / f"observations_until_{end_dt.strftime('%Y%m%d%H%M%S')}"
    limited_dir.mkdir(parents=True, exist_ok=True)

    station_src = source_dir / "chengdu_stations.csv"
    station_dst = limited_dir / "chengdu_stations.csv"
    if station_src.exists():
        shutil.copyfile(station_src, station_dst)

    obs_src = _find_latest(source_dir, "chengdu_observations_site_hourly_*.csv")
    if obs_src is None:
        return limited_dir

    obs_dst = limited_dir / obs_src.name
    with obs_src.open("r", encoding="utf-8-sig", newline="") as src, obs_dst.open("w", encoding="utf-8-sig", newline="") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            dt = _parse_datetime(row.get("datetime"))
            if dt is None:
                continue
            if dt <= end_dt:
                writer.writerow(row)
    return limited_dir


def _cmaq_start_datetime(config: AgentConfig, pollutant: str, cmaq_file: str | None) -> datetime:
    path = Path(cmaq_file) if cmaq_file else _default_cmaq_hourly_file(config, pollutant)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            dt = _parse_datetime(row.get("datetime"))
            if dt is not None:
                return dt
    raise RuntimeError(f"无法从CMAQ小时文件识别起始时间：{path}")


def _default_cmaq_hourly_file(config: AgentConfig, pollutant: str) -> Path:
    normalized = pollutant.upper().replace(".", "").replace(" ", "")
    metric = "o3" if normalized == "O3" else "pm25"
    output_dir = config.data_dir / "output"
    for name in (f"{metric}_trend_hourly_domain.csv", f"{metric}_summary_hourly_domain.csv"):
        path = output_dir / name
        if path.exists():
            return path
    found = _find_latest(output_dir, f"*{metric}*hourly*domain*.csv")
    if found is None:
        raise FileNotFoundError(f"未找到 {pollutant} CMAQ hourly-domain CSV")
    return found


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y%m%d%H"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _find_latest(path: Path, pattern: str) -> Path | None:
    if not path.exists():
        return None
    matches = sorted(path.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _needs_meteorology_context(question: str) -> bool:
    lowered = (question or "").lower()
    return any(
        token in (question or "") or token in lowered
        for token in ("气象", "天气", "风速", "风向", "湿度", "温度", "边界层", "辐射", "降水", "meteorolog", "weather")
    )


def _build_meteorology_context(config: AgentConfig, out_dir: Path, hourly_csv: str | None, period_days: int) -> dict | None:
    if not hourly_csv:
        return None
    hourly_path = Path(hourly_csv)
    if not hourly_path.exists():
        return None
    top_hours = _top_pollution_hours(hourly_path)
    if not top_hours:
        return None

    utils = _load_cmaq_utils(config)
    if utils is None:
        return None
    main_path, _extra_path = utils.find_cmaq_files(config.data_dir)
    if not main_path:
        return None
    available = set(utils.variable_names(main_path))
    fields = [
        ("TEMP2", "2m_temperature_c"),
        ("RH", "relative_humidity_pct"),
        ("WSPD10", "wind_speed_10m_ms"),
        ("WDIR10", "wind_direction_10m_deg"),
        ("PBLH", "boundary_layer_height_m"),
        ("SR", "solar_radiation"),
        ("RT", "precipitation"),
        ("CFRAC", "cloud_fraction"),
    ]
    fields = [(field, label) for field, label in fields if field in available]
    if not fields:
        return None

    rows = [
        {"datetime": item["datetime"].strftime("%Y-%m-%d %H:%M:%S"), "pm25_domain_mean": item["domain_mean"]}
        for item in top_hours
    ]
    for field, label in fields:
        try:
            data, times, attrs = utils.read_field(main_path, field, period_days=period_days)
        except Exception:
            continue
        index_by_time = {dt.strftime("%Y-%m-%d %H:%M:%S"): idx for idx, dt in enumerate(times)}
        for row in rows:
            idx = index_by_time.get(row["datetime"])
            if idx is None:
                continue
            value = float(utils.np.nanmean(data[idx]))
            if field == "TEMP2" and value > 150:
                value -= 273.15
            row[label] = round(value, 4)
            unit = attrs.get("units") or ""
            if unit:
                row[f"{label}_unit"] = str(unit).strip()

    csv_path = out_dir / "meteorology_context_high_pm25_hours.csv"
    json_path = out_dir / "meteorology_context_summary.json"
    fieldnames = list(dict.fromkeys(key for row in rows for key in row.keys()))
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    aggregates = {}
    for key in fieldnames:
        if key == "datetime" or key.endswith("_unit"):
            continue
        vals = []
        for row in rows:
            try:
                vals.append(float(row[key]))
            except (KeyError, TypeError, ValueError):
                pass
        if vals:
            aggregates[key] = {
                "mean": sum(vals) / len(vals),
                "min": min(vals),
                "max": max(vals),
            }
    interpretation = _meteorology_interpretation(aggregates)
    payload = {
        "source_file": str(main_path),
        "high_hours_selected": len(rows),
        "selection": "top domain-mean PM2.5 hours from the requested CMAQ analysis window",
        "fields": [label for _field, label in fields],
        "aggregates": aggregates,
        "interpretation": interpretation,
        "csv": str(csv_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_bits = [
        f"已从CMAQ同步提取高值时段气象条件：选取 {len(rows)} 个PM2.5高值小时",
    ]
    for key, label in [
        ("relative_humidity_pct", "平均相对湿度"),
        ("wind_speed_10m_ms", "平均10m风速"),
        ("boundary_layer_height_m", "平均边界层高度"),
        ("2m_temperature_c", "平均2m气温"),
    ]:
        if key in aggregates:
            summary_bits.append(f"{label}约 {_fmt(aggregates[key]['mean'])}")
    if interpretation:
        summary_bits.append(interpretation)
    return {
        "summary": "；".join(summary_bits) + "。",
        "data": payload,
        "artifacts": [
            Artifact(kind="csv", path=str(csv_path.resolve()), label="高值气象条件"),
            Artifact(kind="json", path=str(json_path.resolve()), label="气象条件摘要"),
        ],
    }


def _top_pollution_hours(hourly_path: Path, limit: int = 8) -> list[dict]:
    rows = []
    with hourly_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            dt = _parse_datetime(row.get("datetime"))
            if dt is None:
                continue
            try:
                domain_mean = float(row.get("domain_mean") or "nan")
            except ValueError:
                continue
            if domain_mean != domain_mean:
                continue
            rows.append({"datetime": dt, "domain_mean": domain_mean})
    rows.sort(key=lambda item: item["domain_mean"], reverse=True)
    return rows[: max(1, limit)]


def _load_cmaq_utils(config: AgentConfig):
    module_path = config.skills_dir / "cmaq-forecast-qa" / "scripts" / "cmaq_utils.py"
    if not module_path.exists():
        return None
    module_name = f"cmaq_utils_runtime_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _meteorology_interpretation(aggregates: dict) -> str:
    notes: list[str] = []
    wind = aggregates.get("wind_speed_10m_ms", {}).get("mean")
    rh = aggregates.get("relative_humidity_pct", {}).get("mean")
    pblh = aggregates.get("boundary_layer_height_m", {}).get("mean")
    precip = aggregates.get("precipitation", {}).get("mean")
    cloud = aggregates.get("cloud_fraction", {}).get("mean")
    if wind is not None and wind < 2:
        notes.append("低风速不利于水平扩散")
    if rh is not None and rh >= 70:
        notes.append("较高湿度有利于颗粒物吸湿增长和二次转化")
    if pblh is not None and pblh < 500:
        notes.append("边界层偏低会压缩垂直扩散空间")
    if precip is not None and precip <= 0.1:
        notes.append("降水清除作用弱")
    if cloud is not None and cloud >= 0.7:
        notes.append("云量偏多可能削弱辐射并维持静稳湿环境")
    return "、".join(notes)


def _summarize_cmaq_qa(data: dict) -> str:
    metric = data.get("metric")
    field = data.get("field")
    unit = data.get("unit") or ""
    period = data.get("period", {})
    trend = data.get("trend", {})
    high = data.get("high_value", {})
    peak = data.get("peak", {})
    parts = [f"{metric}({field}) 分析完成，时间范围 {period.get('start')} 至 {period.get('end')}。"]
    if trend:
        label = _trend_label_zh(trend.get("label"))
        slope = _fmt(trend.get("slope_per_day"))
        delta = _fmt(trend.get("delta"))
        first_mean = _fmt(trend.get("first_window_mean"))
        last_mean = _fmt(trend.get("last_window_mean"))
        parts.append(
            f"趋势：{label}，前段均值约 {first_mean}{unit}，后段均值约 {last_mean}{unit}，"
            f"累计变化约 {delta}{unit}，斜率约 {slope}{unit}/日。"
        )
    if high:
        parts.append(
            f"高值：阈值 {high.get('threshold')}{unit}，超过阈值小时数 {high.get('exceed_hour_count')}，"
            f"涉及天数 {high.get('exceed_day_count')}。"
        )
    if peak:
        parts.append(f"网格峰值出现在 {peak.get('datetime')}，值 {_fmt(peak.get('value'))}{unit}。")
    return " ".join(parts)


def _summarize_cmaq_plot(data: dict) -> str:
    variable = data.get("variable")
    outputs = data.get("outputs", [])
    names = ", ".join(item.get("plot", "plot") for item in outputs)
    return f"{variable} 绘图完成：{names}。"


def _correction_artifacts(out_dir: Path) -> list[Artifact]:
    items: list[Artifact] = []
    for path, kind, label in [
        (out_dir / "assessment.md", "text", "CMAQ订正研判报告"),
        (out_dir / "city_aggregate.csv", "csv", "城市均值订正结果"),
        (out_dir / "station_corrected.csv", "csv", "站点订正结果"),
        (out_dir / "space_factor.csv", "csv", "空间订正系数"),
        (out_dir / "diagnosis.json", "json", "CMAQ诊断结果"),
        (out_dir / "explanations.json", "json", "专家规则解释"),
    ]:
        artifact = _artifact_from_path(str(path), kind, label) if path.exists() else None
        if artifact is not None:
            items.append(artifact)

    fig_dir = out_dir / "figures"
    if fig_dir.exists():
        for fig, label in _select_core_correction_figures(fig_dir):
            artifact = _artifact_from_path(str(fig), "image", label)
            if artifact is not None:
                items.append(artifact)
    return items


def _select_core_correction_figures(fig_dir: Path, limit: int = 3) -> list[tuple[Path, str]]:
    """Select the smallest set of figures that supports the main assessment story.

    The correction workflow produces diagnostics, per-station plots and vector/raster
    duplicates. Returning all of them overwhelms the final answer. Prefer one city
    trend, one corrected peak map and one correction-impact map; keep the complete
    diagnostic set on disk for expert follow-up.
    """
    preferred = [
        ("city_mean_timeseries", "成都市均值变化与订正趋势"),
        ("corrected_spatial_peak", "订正后污染高值空间分布"),
        ("correction_difference_spatial", "订正影响空间分布"),
    ]
    available: dict[str, Path] = {}
    for suffix in (".svg", ".png"):
        for path in sorted(fig_dir.glob(f"*{suffix}")):
            # PNG is preferred when both formats exist because it renders more
            # consistently in the WebUI. The loop order intentionally lets it win.
            available[path.stem] = path

    selected: list[tuple[Path, str]] = []
    used: set[str] = set()
    for stem, label in preferred:
        path = available.get(stem)
        if path is not None:
            selected.append((path, label))
            used.add(stem)
            if len(selected) >= limit:
                return selected

    fallback_stems = sorted(
        (stem for stem in available if stem not in used),
        key=lambda stem: (
            stem.startswith("station_"),
            stem.startswith("raw_"),
            "spatial_factor" in stem,
            stem,
        ),
    )
    for stem in fallback_stems:
        selected.append((available[stem], stem.replace("_", " ")))
        if len(selected) >= limit:
            break
    return selected


def _summarize_cmaq_correction(out_dir: Path, stdout: str, stderr: str) -> str:
    assessment = out_dir / "assessment.md"
    if assessment.exists():
        text = assessment.read_text(encoding="utf-8", errors="ignore")
        lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
        useful = []
        for line in lines:
            if any(key in line for key in ("订正路径", "城市均值订正前", "城市均值订正后", "MAE 变化", "是否更靠近观测")):
                useful.append(line.lstrip("- "))
            if len(useful) >= 4:
                break
        if useful:
            return "CMAQ订正完成。" + " ".join(useful)
    fallback = stderr.strip() or stdout.strip()
    return fallback or "CMAQ订正流程已完成。"


def _trend_label_zh(label: str | None) -> str:
    return {
        "increasing": "上升",
        "decreasing": "下降",
        "flat": "基本持平",
        "stable": "基本持平",
    }.get(label or "", label or "未判定")


def _fmt(value) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return str(value)
