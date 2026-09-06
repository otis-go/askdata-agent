"""探查脚本 04：物理列类型 + 截断行为的精确验证。

DuckDbEngine._validate_sql 只放行 SCHEMA 白名单中的 5 张表，
information_schema 无法通过 execute() 访问，因此这里直接用 engine.connect()
（引擎自身的公开只读上下文管理器）读取元数据。

只读；不修改 backend 下任何文件。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.querying.duckdb_engine import DuckDbEngine  # noqa: E402
from app.database import SCHEMA  # noqa: E402

OUT = Path(__file__).resolve().parent / "out_04_dtype_and_truncation.json"

# 静态 Schema 里的中文类型 -> 便于和 DuckDB 推断出的物理类型对照
STATIC_TYPES = {
    f"{table['id']}.{field['name']}": field["type"]
    for table in SCHEMA
    for field in table["fields"]
}


def main() -> None:
    engine = DuckDbEngine()
    output: dict = {"physical_vs_static_types": [], "truncation": {}, "metadata_reachability": {}}

    with engine.connect("askdata_mock") as connection:
        rows = connection.execute(
            "SELECT table_name, column_name, data_type, is_nullable "
            "FROM information_schema.columns ORDER BY table_name, ordinal_position"
        ).fetchall()
        print("=== 物理类型 vs 静态 Schema 类型 ===")
        for table_name, column_name, data_type, nullable in rows:
            key = f"{table_name}.{column_name}"
            static = STATIC_TYPES.get(key, "<静态Schema中不存在>")
            entry = {
                "column": key,
                "duckdb_physical_type": data_type,
                "static_schema_type": static,
                "is_nullable": nullable,
            }
            output["physical_vs_static_types"].append(entry)
            print(f"  {key:34s} 物理={data_type:12s} 静态={static}")

        # 截断行为：引擎 fetchmany(201) 后取 [:200]，第 201 行被读出但丢弃
        cursor = connection.execute(
            "SELECT order_id, region, paid_amount FROM orders_current ORDER BY order_id"
        )
        fetched = cursor.fetchmany(201)
        total = connection.execute("SELECT COUNT(*) FROM orders_current").fetchone()[0]
        output["truncation"] = {
            "table_total_rows": total,
            "engine_fetchmany_size": 201,
            "rows_actually_fetched": len(fetched),
            "rows_returned_to_caller": min(200, len(fetched)),
            "engine_knows_more_rows_exist": len(fetched) > 200,
            "flag_exposed_in_SqlExecution": False,
            "note": "duckdb_engine.py:43-48 取 fetchmany(201) 后切片 [:200]，"
                    "第 201 行只用于判断是否还有更多数据，但该信息未写入任何返回字段。",
        }
        print("\n=== 截断行为 ===")
        print(f"  表内总行数={total}  fetchmany(201)实取={len(fetched)}  "
              f"返回上层={min(200, len(fetched))}  引擎其实知道被截断={len(fetched) > 200}  "
              f"但 SqlExecution 无任何截断字段")

    # 元数据可达性：走 execute() 时白名单会拦掉 information_schema
    probe = engine.execute("askdata_mock", "SELECT column_name FROM information_schema.columns")
    output["metadata_reachability"] = {
        "information_schema_via_execute": probe.success,
        "error": probe.error,
        "note": "SQL 白名单只允许 SCHEMA 中登记的 5 张业务表，元数据表不可达。",
    }
    print(f"\n=== 元数据可达性 ===\n  execute(information_schema) success={probe.success} error={probe.error}")

    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果写入 {OUT}")


if __name__ == "__main__":
    main()
