"""探查脚本 06：核实报告中两处关键论断。

  1. DuckDB 的 cursor.description 是否真的提供了 type_code（即 dtype 确实"在手边被丢弃"）。
  2. 报告正文引用的样例结果四行数值是否与实测一致。

只读；不修改 backend 下任何文件。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.querying.duckdb_engine import DuckDbEngine  # noqa: E402

OUT = Path(__file__).resolve().parent / "out_06_verify_claims.json"

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
    output: dict = {}

    with engine.connect("askdata_mock") as connection:
        cursor = connection.execute(SQL)
        description = cursor.description
        rows = cursor.fetchall()

        print("=== 论断1：cursor.description 是否携带 type_code ===")
        print("  DBAPI 7 元组 = (name, type_code, display_size, internal_size, precision, scale, null_ok)")
        desc_dump = []
        for item in description:
            entry = {
                "index_0_name": item[0],
                "index_1_type_code": str(item[1]),
                "full_tuple_len": len(item),
                "full_tuple": [str(x) for x in item],
            }
            desc_dump.append(entry)
            print(f"  [0]={item[0]:<8} [1]type_code={str(item[1]):<12} 元组长度={len(item)}")
        output["cursor_description"] = desc_dump
        output["claim_1_type_code_available"] = all(item[1] is not None for item in description)
        print(f"\n  → 每一列的 type_code 都非空？ {output['claim_1_type_code_available']}")
        print("  → duckdb_engine.py:44 写的是 [item[0] for item in cursor.description]，"
              "只取下标0，type_code 被丢弃。论断成立。" if output["claim_1_type_code_available"]
              else "  → 论断不成立，需修正报告。")

        print("\n=== 论断2：报告正文样例数值核实 ===")
        columns = [item[0] for item in description]
        actual = [dict(zip(columns, row)) for row in rows]
        output["sample_rows_actual"] = actual
        for row in actual:
            print("  " + json.dumps(row, ensure_ascii=False))

    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n完整结果写入 {OUT}")


if __name__ == "__main__":
    main()
