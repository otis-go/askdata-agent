r"""探查脚本 03：验证常见业务信号（排名/占比/合计/完成率/环比/同比）在现有数据上是否算得出来。

只读；不修改 backend 下任何文件。运行方式：
    set PYTHONPATH=backend\.venv\Lib\site-packages
    backend\.python311\python.exe -X utf8 data_probe\probe_03_signal_feasibility.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.querying.duckdb_engine import DuckDbEngine  # noqa: E402

OUT = Path(__file__).resolve().parent / "out_03_signal_feasibility.json"

CHECKS: dict[str, str] = {
    # 1. 时间覆盖：两张订单表分别覆盖哪些月份
    "月份覆盖_orders_history": """
        SELECT strftime(order_date, '%Y-%m') AS 月份, COUNT(*) AS 行数,
               MIN(order_date) AS 最早, MAX(order_date) AS 最晚
        FROM orders_history GROUP BY 1 ORDER BY 1
    """,
    "月份覆盖_orders_current": """
        SELECT strftime(order_date, '%Y-%m') AS 月份, COUNT(*) AS 行数,
               MIN(order_date) AS 最早, MAX(order_date) AS 最晚
        FROM orders_current GROUP BY 1 ORDER BY 1
    """,
    "目标月份覆盖": "SELECT target_month, COUNT(*) AS 地区数, SUM(target_amount) AS 目标合计 FROM sales_targets GROUP BY 1 ORDER BY 1",

    # 2. 合计 / 排名 / 占比：单表可算
    "合计_排名_占比": """
        SELECT region AS 地区, SUM(paid_amount) AS 销售额,
               ROUND(100.0 * SUM(paid_amount) / SUM(SUM(paid_amount)) OVER (), 2) AS 占比百分比,
               RANK() OVER (ORDER BY SUM(paid_amount) DESC) AS 排名
        FROM orders_current WHERE status = '已支付' GROUP BY region ORDER BY 排名
    """,

    # 3. 完成率：需要 orders_current 与 sales_targets 按 (region, 月份) 对齐
    "完成率_正确对齐": """
        WITH actual AS (
            SELECT region, strftime(order_date, '%Y-%m') AS ym, SUM(paid_amount) AS amt
            FROM orders_current WHERE status = '已支付' GROUP BY 1, 2
        )
        SELECT a.region AS 地区, a.ym AS 月份, ROUND(a.amt, 2) AS 实际销售额,
               t.target_amount AS 销售目标,
               ROUND(100.0 * a.amt / t.target_amount, 2) AS 完成率百分比
        FROM actual a JOIN sales_targets t ON a.region = t.region AND a.ym = t.target_month
        ORDER BY 完成率百分比 DESC
    """,

    # 4. 完成率的陷阱：只按 region 关联而不对齐月份 -> 目标行翻倍
    "完成率_只按region关联的错误结果": """
        SELECT o.region AS 地区, SUM(o.paid_amount) AS 实际销售额_被放大,
               SUM(t.target_amount) AS 目标_被重复累加, COUNT(*) AS 关联后行数
        FROM orders_current o JOIN sales_targets t ON o.region = t.region
        WHERE o.status = '已支付' GROUP BY o.region ORDER BY 1
    """,

    # 5. 环比：需要跨 orders_history + orders_current 做 UNION
    "环比_需跨表UNION": """
        WITH monthly AS (
            SELECT strftime(order_date, '%Y-%m') AS ym, SUM(paid_amount) AS amt
            FROM orders_history WHERE status = '已支付' GROUP BY 1
            UNION ALL
            SELECT strftime(order_date, '%Y-%m'), SUM(paid_amount)
            FROM orders_current WHERE status = '已支付' GROUP BY 1
        )
        SELECT ym AS 月份, ROUND(amt, 2) AS 销售额,
               ROUND(amt - LAG(amt) OVER (ORDER BY ym), 2) AS 环比增量,
               ROUND(100.0 * (amt / LAG(amt) OVER (ORDER BY ym) - 1), 2) AS 环比百分比
        FROM monthly ORDER BY ym
    """,

    # 6. 同比：需要去年同月数据
    "同比_是否有去年同月数据": """
        SELECT MIN(strftime(order_date, '%Y-%m')) AS 全局最早月, MAX(strftime(order_date, '%Y-%m')) AS 全局最晚月,
               COUNT(DISTINCT strftime(order_date, '%Y')) AS 覆盖年份数
        FROM (SELECT order_date FROM orders_history UNION ALL SELECT order_date FROM orders_current)
    """,

    # 7. 上期值 / 预算值 是否作为列直接存在
    "是否存在上期值列": """
        SELECT column_name, table_name, data_type
        FROM information_schema.columns
        WHERE lower(column_name) LIKE '%prev%' OR lower(column_name) LIKE '%last%'
           OR lower(column_name) LIKE '%budget%' OR lower(column_name) LIKE '%yoy%'
           OR lower(column_name) LIKE '%mom%' OR lower(column_name) LIKE '%target%'
    """,

    # 8. 全部列的物理类型（DuckDB 推断）——对比静态 Schema 的中文类型
    "物理列类型": """
        SELECT table_name AS 表, column_name AS 列, data_type AS 物理类型, is_nullable AS 可空
        FROM information_schema.columns ORDER BY table_name, ordinal_position
    """,

    # 9. 口径歧义：order_amount vs paid_amount，含/不含已取消已退款的差异
    "口径歧义_销售额四种算法": """
        SELECT
            ROUND(SUM(order_amount), 2) AS A_订单金额全量,
            ROUND(SUM(paid_amount), 2) AS B_实付金额全量,
            ROUND(SUM(CASE WHEN status = '已支付' THEN order_amount ELSE 0 END), 2) AS C_订单金额仅已支付,
            ROUND(SUM(CASE WHEN status = '已支付' THEN paid_amount ELSE 0 END), 2) AS D_实付金额仅已支付
        FROM orders_current
    """,

    # 10. 维度一致性：订单表冗余的 region/category 是否与主数据表一致
    "维度一致性_region": """
        SELECT COUNT(*) AS 订单表region与客户表region不一致的行数
        FROM orders_current o JOIN customers c ON o.customer_id = c.customer_id
        WHERE o.region <> c.region
    """,
    "维度一致性_category": """
        SELECT COUNT(*) AS 订单表category与产品表category不一致的行数
        FROM orders_current o JOIN products p ON o.product_id = p.product_id
        WHERE o.category <> p.category
    """,
}


def main() -> None:
    engine = DuckDbEngine()
    output = {}
    for name, sql in CHECKS.items():
        execution = engine.execute("askdata_mock", sql)
        output[name] = {
            "success": execution.success,
            "error": execution.error,
            "columns": execution.columns,
            "rows": execution.rows,
        }
        print(f"\n=== {name} ===")
        if not execution.success:
            print("  FAILED:", execution.error)
            continue
        print("  columns:", execution.columns)
        for row in execution.rows[:14]:
            print("   ", json.dumps(row, ensure_ascii=False))
        if len(execution.rows) > 14:
            print(f"    ... 共 {len(execution.rows)} 行")

    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果写入 {OUT}")


if __name__ == "__main__":
    main()
