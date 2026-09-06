r"""探查脚本 02：走真实 DuckDbEngine，抓取 SqlExecution / DatabaseQueryResult 的真实结构。

只读；不修改 backend 下任何文件。运行方式：
    backend\.python311\python.exe data_probe\probe_02_execution_shape.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import importlib.util  # noqa: E402

from app.querying.duckdb_engine import DuckDbEngine  # noqa: E402

# app.mcp_runtime.__init__ 会拉起 mcp -> pywintypes（本机缺失），
# 这里直接按文件加载 schemas.py，只取 Pydantic 模型定义。
_spec = importlib.util.spec_from_file_location(
    "_probe_mcp_schemas", ROOT / "backend" / "app" / "mcp_runtime" / "schemas.py"
)
_schemas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_schemas)
DatabaseQueryResult = _schemas.DatabaseQueryResult
DatabaseQueryResult.model_rebuild(_types_namespace={"Any": __import__("typing").Any})

OUT = Path(__file__).resolve().parent / "out_02_execution_shape.json"

QUERIES = {
    "Q1_region_sales": """
        SELECT region, SUM(paid_amount) AS 销售额, COUNT(order_id) AS 订单数
        FROM orders_current WHERE status = '已支付' GROUP BY region ORDER BY 销售额 DESC
    """,
    "Q2_target_vs_actual": """
        SELECT o.region,
               SUM(o.paid_amount) AS 实际销售额,
               MAX(t.target_amount) AS 销售目标
        FROM orders_current o
        JOIN sales_targets t ON o.region = t.region AND t.target_month = '2026-08'
        WHERE o.status = '已支付'
        GROUP BY o.region ORDER BY 实际销售额 DESC
    """,
    "Q3_raw_detail": """
        SELECT order_id, region, category, order_amount, paid_amount, status, order_date
        FROM orders_current ORDER BY order_id
    """,
    "Q4_month_coverage": """
        SELECT strftime(order_date, '%Y-%m') AS 月份, COUNT(order_id) AS 订单数,
               SUM(paid_amount) AS 销售额
        FROM orders_history GROUP BY 1
        UNION ALL
        SELECT strftime(order_date, '%Y-%m'), COUNT(order_id), SUM(paid_amount)
        FROM orders_current GROUP BY 1 ORDER BY 1
    """,
    "Q5_bad_sql": "SELECT * FROM orders_current",
}


def main() -> None:
    engine = DuckDbEngine()
    output = {}
    for name, sql in QUERIES.items():
        execution = engine.execute("askdata_mock", sql)
        payload = asdict(execution)
        wrapped = DatabaseQueryResult(
            database="askdata_mock",
            sql=execution.sql,
            success=execution.success,
            columns=execution.columns,
            rows=execution.rows,
            row_count=len(execution.rows),
            error=execution.error,
        )
        output[name] = {
            "SqlExecution_fields": sorted(payload.keys()),
            "success": execution.success,
            "error": execution.error,
            "columns": execution.columns,
            "returned_row_count": len(execution.rows),
            "first_2_rows": execution.rows[:2],
            "python_types_of_first_row": {
                k: type(v).__name__ for k, v in (execution.rows[0].items() if execution.rows else [])
            },
            "DatabaseQueryResult_json_keys": sorted(wrapped.model_dump().keys()),
        }
        print(f"\n=== {name} success={execution.success} rows={len(execution.rows)} ===")
        print("columns:", execution.columns)
        if execution.rows:
            print("row[0]:", json.dumps(execution.rows[0], ensure_ascii=False))
            print("types :", {k: type(v).__name__ for k, v in execution.rows[0].items()})
        if execution.error:
            print("error :", execution.error)

    # 截断行为验证：Q3 明细共 240 行，引擎最多返回 200 行。
    detail = engine.execute("askdata_mock", QUERIES["Q3_raw_detail"])
    output["truncation_check"] = {
        "actual_table_rows": 240,
        "rows_returned": len(detail.rows),
        "any_truncation_flag_in_result": [
            k for k in asdict(detail) if "trunc" in k or "limit" in k or "total" in k
        ],
    }
    print(f"\n=== 截断检查：表内 240 行，返回 {len(detail.rows)} 行；"
          f"SqlExecution 字段 = {sorted(asdict(detail).keys())} ===")

    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果写入 {OUT}")


if __name__ == "__main__":
    main()
