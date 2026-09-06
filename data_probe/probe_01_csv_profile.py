r"""探查脚本 01：CSV 数据源体量、字段类型、取值分布与空值情况。

只读；不修改 backend 下任何文件。运行方式：
    backend\.venv\Scripts\python.exe data_probe\probe_01_csv_profile.py
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "backend" / "data" / "databases" / "askdata_mock"
OUT = Path(__file__).resolve().parent / "out_01_csv_profile.json"


def is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def profile_csv(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = list(reader)

    report = {
        "file": path.name,
        "row_count": len(rows),
        "column_count": len(columns),
        "columns": {},
        "head_3": rows[:3],
    }
    for column in columns:
        values = [row.get(column, "") for row in rows]
        non_null = [v for v in values if v not in ("", None)]
        distinct = Counter(non_null)
        numeric = all(is_number(v) for v in non_null) and bool(non_null)
        entry = {
            "null_count": len(values) - len(non_null),
            "null_ratio": round((len(values) - len(non_null)) / max(1, len(values)), 4),
            "distinct_count": len(distinct),
            "inferred_kind": "numeric" if numeric else "text",
            "samples": [v for v, _ in distinct.most_common(5)],
        }
        if numeric:
            nums = [float(v) for v in non_null]
            entry.update({
                "min": min(nums),
                "max": max(nums),
                "sum": round(sum(nums), 2),
                "avg": round(sum(nums) / len(nums), 2),
                "zero_count": sum(1 for n in nums if n == 0),
            })
        if len(distinct) <= 12:
            entry["value_counts"] = dict(distinct.most_common())
        report["columns"][column] = entry
    return report


def main() -> None:
    reports = [profile_csv(p) for p in sorted(DB_DIR.glob("*.csv"))]
    OUT.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    for report in reports:
        print(f"\n=== {report['file']}  rows={report['row_count']} cols={report['column_count']} ===")
        for name, info in report["columns"].items():
            extra = ""
            if info["inferred_kind"] == "numeric":
                extra = f" min={info['min']} max={info['max']} sum={info['sum']} zeros={info['zero_count']}"
            vc = info.get("value_counts")
            vc_text = f" values={vc}" if vc and len(vc) <= 8 else ""
            print(
                f"  {name:16s} kind={info['inferred_kind']:7s} "
                f"distinct={info['distinct_count']:5d} null={info['null_count']}{extra}{vc_text}"
            )
    print(f"\n完整结果写入 {OUT}")


if __name__ == "__main__":
    main()
