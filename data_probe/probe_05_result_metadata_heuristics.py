"""探查脚本 05：端到端 QueryResult 真实结构 + metric/dimension 与单位格式两套启发式规则的对照。

覆盖三件事：
  1. 用真实 SqlExecution 走 ResultBuilder.completed，导出完整 QueryResult JSON。
  2. 复刻 result_builder.py:95-99 的后端"业务角色"判定规则，检验其准确性。
  3. 复刻 ResultTableCard.vue formatCell 的前端"单位/格式"判定规则，检验两者是否一致。

只读；不修改 backend 下任何文件。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.querying.duckdb_engine import DuckDbEngine  # noqa: E402
from app.workflows.result_builder import ResultBuilder  # noqa: E402

OUT = Path(__file__).resolve().parent / "out_05_result_metadata.json"

# --- 后端规则：result_builder.py:95-99 ---
BACKEND_METRIC_TERMS = ("额", "数", "率", "平均", "目标")


def backend_role(column: str) -> str:
    return "metric" if any(term in column for term in BACKEND_METRIC_TERMS) else "dimension"


# --- 前端规则：frontend/src/components/ResultTableCard.vue formatCell ---
def frontend_format(column: str) -> str:
    if re.search(r"金额|销售额|客单价|收入", column):
        return "currency(CNY, 0位小数)"
    if re.search(r"率|占比", column):
        return "percent(值×100)"
    return "number(2位小数)"


# 真实出现过的列名 + 典型业务列名
COLUMNS_UNDER_TEST = [
    "地区", "销售地区", "销售额", "订单数", "客单价", "目标完成率",
    "完成率百分比", "月份", "客户等级", "产品类别", "销售目标",
    "环比百分比", "占比百分比", "区域负责人", "订单编号", "毛利",
]

SQL = """
    SELECT o.region AS 销售地区,
           ROUND(SUM(o.paid_amount), 2) AS 销售额,
           COUNT(o.order_id) AS 订单数,
           ROUND(SUM(o.paid_amount) / COUNT(o.order_id), 2) AS 客单价,
           MAX(t.target_amount) AS 销售目标,
           ROUND(100.0 * SUM(o.paid_amount) / MAX(t.target_amount), 2) AS 目标完成率
    FROM orders_current o
    JOIN sales_targets t ON o.region = t.region AND t.target_month = '2026-08'
    WHERE o.status = '已支付'
    GROUP BY o.region ORDER BY 销售额 DESC
"""


def main() -> None:
    engine = DuckDbEngine()
    execution = engine.execute("askdata_mock", SQL)

    state = {
        "task_id": "probe-task-0001",
        "schema_graph": {
            "tables": [
                {"id": "orders_current", "label": "当前订单明细", "description": "", "domain": "", "database": "askdata_mock"},
                {"id": "sales_targets", "label": "地区销售目标", "description": "", "domain": "", "database": "askdata_mock"},
            ],
            "fields": [],
            "joins": [],
            "graph_version": "probe000000",
        },
        "extraction": {"time_expressions": ["本月"]},
        "intent": {"reason": "问数"},
        "retrieval": {},
        "workflow_mode": "single_database_agent",
    }
    final = {"valid": True, "reason": "结果检查通过", "title": "本月各地区销售额与目标完成率", "analysis": "示例说明"}
    result = ResultBuilder.completed(state, [execution], execution, final, [], [])
    payload = result.model_dump(mode="json")

    print("=== 端到端 QueryResult 顶层字段 ===")
    print(sorted(payload.keys()))
    print("\n=== 与数据结果直接相关的字段 ===")
    for key in ("columns", "rows", "sql", "interpretation", "result_title"):
        value = payload[key]
        shown = value if key != "rows" else value[:2]
        print(f"  {key} = {json.dumps(shown, ensure_ascii=False)[:400]}")

    print("\n=== 每一列到底携带了什么元信息 ===")
    print("  columns 只是 list[str]；rows 是 list[dict]，键=列名，值=裸标量。")
    print("  逐列可得到的元信息如下（全部靠列名字符串推断，非来自 Schema）：")
    print(f"  {'列名':<14}{'后端role(启发式)':<20}{'前端格式(启发式)':<24}{'Python类型':<10}{'原始Schema字段'}")
    rows_first = execution.rows[0] if execution.rows else {}
    comparison = []
    for column in execution.columns:
        entry = {
            "column": column,
            "backend_role_heuristic": backend_role(column),
            "frontend_format_heuristic": frontend_format(column),
            "python_type": type(rows_first.get(column)).__name__,
            "traceable_to_schema_field": False,
            "declared_unit": None,
            "declared_precision": None,
        }
        comparison.append(entry)
        print(f"  {column:<14}{entry['backend_role_heuristic']:<20}"
              f"{entry['frontend_format_heuristic']:<24}{entry['python_type']:<10}无（不可追溯）")

    print("\n=== 两套启发式规则在更广列名上的分歧 ===")
    disagreements = []
    for column in COLUMNS_UNDER_TEST:
        role = backend_role(column)
        fmt = frontend_format(column)
        # 前端认为是货币/百分比 => 业务上应当是 metric
        frontend_implies_metric = fmt != "number(2位小数)"
        conflict = frontend_implies_metric and role == "dimension"
        record = {
            "column": column,
            "backend_role": role,
            "frontend_format": fmt,
            "conflict": conflict,
        }
        comparison.append(record) if False else None
        disagreements.append(record)
        flag = "  <== 冲突" if conflict else ""
        print(f"  {column:<14}后端={role:<10}前端={fmt:<24}{flag}")

    # 已验证：SQL 返回的 目标完成率 已经是百分数(如 344.18)，前端还会再 ×100
    percent_columns = [c for c in execution.columns if re.search(r"率|占比", c)]
    percent_demo = []
    for column in percent_columns:
        raw = rows_first.get(column)
        percent_demo.append({
            "column": column,
            "sql_returned_value": raw,
            "frontend_rendered": f"{raw * 100:.1f}%" if isinstance(raw, (int, float)) else None,
            "note": "SQL 已经乘过 100，前端 formatCell 会再乘一次，渲染值被放大 100 倍。",
        })
        print(f"\n=== 单位/精度无契约的实证：列「{column}」 ===")
        print(f"  SQL 返回值 = {raw}")
        print(f"  前端 formatCell 渲染 = {raw * 100:.1f}%   （真实含义应为 {raw:.2f}%）")

    output = {
        "queryresult_top_level_keys": sorted(payload.keys()),
        "queryresult_full_sample": payload,
        "sqlexecution_columns": execution.columns,
        "per_column_metadata_available": comparison,
        "heuristic_disagreements": disagreements,
        "percent_unit_demo": percent_demo,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果写入 {OUT}")


if __name__ == "__main__":
    main()
