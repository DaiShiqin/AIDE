from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fnum, mae, read_csv, read_json, safe_float_text


def city_metrics(city_rows: list[dict]) -> dict:
    raw_pairs = [(fnum(r.get("raw_cmaq_mean")), fnum(r.get("observed_mean"))) for r in city_rows]
    corr_pairs = [(fnum(r.get("corrected_mean")), fnum(r.get("observed_mean"))) for r in city_rows]
    raw_mae = mae(raw_pairs)
    corr_mae = mae(corr_pairs)
    return {
        "raw_mae": raw_mae,
        "corrected_mae": corr_mae,
        "mae_delta": None if raw_mae is None or corr_mae is None else corr_mae - raw_mae,
        "improved": raw_mae is not None and corr_mae is not None and corr_mae < raw_mae,
    }


def top_station_changes(station_rows: list[dict]) -> list[dict]:
    rows = []
    for r in station_rows:
        raw = fnum(r.get("raw_mae"))
        corr = fnum(r.get("corrected_mae"))
        if raw is None or corr is None:
            continue
        rows.append({**r, "mae_delta": corr - raw})
    return sorted(rows, key=lambda r: r["mae_delta"])[:5]


def generate(diagnosis, explanations, city_rows, station_rows, figures) -> str:
    metrics = city_metrics(city_rows)
    path = diagnosis.get("path", "unknown")
    obs_count = explanations.get("observation_count", 0) if isinstance(explanations, dict) else 0
    spatial_action = "保留 CMAQ 空间结构" if path in {"anchor_trend", "time_only"} else "先进行空间系数订正"
    if path == "anchor_trend" and obs_count:
        time_action = "使用观测锚定 CMAQ 趋势"
    elif path == "anchor_trend":
        time_action = "无观测锚点时使用 CMAQ 趋势和气象先验订正"
    else:
        time_action = "对站点所在网格进行时间系数订正"
    lines = [
        "# 融合多源数据的空气质量模型诊断与订正研判",
        "",
        "## 多源资料诊断",
        "",
        f"- 订正路径: `{path}`。",
        f"- 空间诊断: {'相对吻合' if diagnosis.get('spatial_match') else '不吻合'}。{diagnosis.get('spatial_reason','')}",
        f"- 时间诊断: {'相对吻合' if diagnosis.get('temporal_match') else '不吻合'}。{diagnosis.get('temporal_reason','')}",
        f"- CMAQ 趋势: {diagnosis.get('cmaq_trend')}；CMAQ 峰值时间: {diagnosis.get('cmaq_peak_time')}；峰值: {safe_float_text(diagnosis.get('cmaq_peak_value'), 2)}；改善时间: {diagnosis.get('cmaq_improvement_time') or '未识别'}。",
        f"- 可用观测记录数: {obs_count}；{'已启用观测约束' if obs_count else '无观测或观测不足，采用气象+CMAQ+专家经验兜底订正'}。",
        "",
        "## 订正研判",
        "",
        f"- 订正了哪里: {spatial_action}；{time_action}；所有站点结果最终进行时间平滑。",
        "- 订正了多少: 见 `space_factor.csv`、`station_corrected.csv` 和关键站点图。报告中保留 raw CMAQ、空间订正、时间订正、观测约束融合、最终平滑结果。",
        "- 订正原因: 订正系数来自 Windy Chengdu 气象先验、成都预报员专家经验和站点观测约束，包括 PM2.5 常规偏高、O3 常规偏低、传输、降水清除、扩散改善、PM2.5 改善节点延后、早高峰后峰值、二次生成突增、O3 副高/高脊青高分型、短临 NO2/VOCs/风云辐射信号和 00/12 时次突变保守跟踪。",
        "- 观测约束: 当同一时刻存在站点观测时，最终平滑前采用模型订正值 35% 与观测值 65% 的融合；未来无观测时该项自动不生效。",
        "",
        "## 聚合结果",
        "",
        f"- 城市均值订正前 MAE: {safe_float_text(metrics['raw_mae'], 3)}。",
        f"- 城市均值订正后 MAE: {safe_float_text(metrics['corrected_mae'], 3)}。",
        f"- MAE 变化: {safe_float_text(metrics['mae_delta'], 3)}；是否更靠近观测: {'是' if metrics['improved'] else '否或观测不足'}。",
        "",
        "## 关键站点变化",
        "",
    ]
    for s in top_station_changes(station_rows):
        lines.append(
            f"- {s.get('station_code')} {s.get('station_name')}: raw MAE {s.get('raw_mae')}, corrected MAE {s.get('corrected_mae')}, delta {s['mae_delta']:.3f}。"
        )
    lines.extend(["", "## 图件输出", ""])
    for row in figures:
        fig = row.get("figure")
        if fig:
            lines.append(f"- {fig}")
    lines.extend(
        [
            "",
            "## 人工复核事项",
            "",
            "- 若 `met_prior.json` 来自手工 Windy 研判或模板，应复核风向风速、降水和云量判断。",
            "- 若仅使用 PM2.5 快速 CSV 而非原始站点网格 CMAQ，站点空间图为站点代理图，不代表完整网格订正图。",
            "- 订正结果用于模型诊断与预报辅助，不替代正式会商和发布流程。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate correction assessment report.")
    parser.add_argument("--diagnosis", required=True)
    parser.add_argument("--explanations", required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--station-summary", required=True)
    parser.add_argument("--figures", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    text = generate(
        read_json(args.diagnosis),
        read_json(args.explanations, default={}),
        read_csv(args.city),
        read_csv(args.station_summary),
        read_csv(args.figures),
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"Wrote assessment: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
