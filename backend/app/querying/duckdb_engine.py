from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from math import copysign, isfinite
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from ..config import BASE_DIR
from ..database import SCHEMA
from ..security import AccessScope
from .models import SqlExecution
from .result_contract import (
    ColumnMetadata,
    ExecutionData,
    ExecutionProvenance,
    RepresentationStatus,
    ResultContract,
    ValueEncoding,
)


DATABASE_ROOT = BASE_DIR / "data" / "databases"


class DuckDbEngine:
    """将 CSV 目录映射为只读 DuckDB 数据库。

    CSV 文件名作为 SQL 表名使用。
    """

    def __init__(self, database_root: Path | None = None) -> None:
        self.database_root = database_root or DATABASE_ROOT

    def execute(
        self,
        database: str,
        sql: str,
        access_scope: AccessScope | None = None,
    ) -> SqlExecution:
        column_metadata = None
        contract_rows = None
        fetched_rows = None
        provenance = ExecutionProvenance(
            engine="duckdb", source_kind="csv_views", sql_submitted=False,
        )
        try:
            safe_sql = self._validate_sql(database, sql, access_scope)
            with self.connect(database) as connection:
                provenance.sql_submitted = True
                provenance.submitted_sql = safe_sql
                cursor = connection.execute(safe_sql)
                description = cursor.description
                if description is not None:
                    column_metadata = [
                        ColumnMetadata(
                            id=f"column_{ordinal}",
                            ordinal=ordinal,
                            name=item[0],
                            dtype=str(item[1]) if item[1] is not None else None,
                        )
                        for ordinal, item in enumerate(description)
                    ]
                raw_rows = cursor.fetchmany(201)
                fetched_rows = len(raw_rows)
                if column_metadata is not None:
                    contract_rows = self._contract_rows(column_metadata, raw_rows[:200])
                # Keep the original dict representation and normalization unchanged.
                columns = [item[0] for item in description or []]
                rows = [
                    {column: self._json_value(value) for column, value in zip(columns, row)}
                    for row in raw_rows[:200]
                ]
            execution = SqlExecution(safe_sql, True, columns, rows)
        except (ValueError, ParseError, duckdb.Error, OSError) as exc:
            execution = SqlExecution(sql, False, error=str(exc))

        # A short fetch exhausts this DuckDB result. A full 201-row fetch only
        # proves that the 200-row response omits data, not the total output size.
        truncated = fetched_rows > 200 if fetched_rows is not None else None
        completeness = None
        if execution.success and contract_rows is not None:
            completeness = "partial_query_output" if truncated else "complete_query_output"
        provenance.captured_at = datetime.now(timezone.utc).isoformat()
        result_id = str(uuid4())
        contract = ResultContract(
            result_id=result_id,
            execution=ExecutionData(
                database=database,
                sql=execution.sql,
                success=execution.success,
                error=execution.error,
                columns=column_metadata,
                rows=contract_rows,
                returned_rows=min(fetched_rows, 200) if fetched_rows is not None else None,
                total_rows=fetched_rows if truncated is False else None,
                truncated=truncated,
                completeness=completeness,
                provenance=provenance,
            ),
        )
        return SqlExecution(
            execution.sql, execution.success, execution.columns, execution.rows,
            execution.error, result_contract=contract, result_id=result_id,
        )

    @classmethod
    def _contract_rows(
        cls, columns: list[ColumnMetadata], raw_rows: list[tuple[Any, ...]],
    ) -> list[list[Any]] | None:
        """Encode by ordinal before duplicate names or legacy coercions lose data.

        The scalar-only contract cannot represent every DuckDB type. In that
        case retain column metadata/counts but withhold the contract row payload;
        never replace unsupported values with fake SQL NULLs or fail the old API.
        """
        encoded_rows = [list(row) for row in raw_rows]
        supported = True
        for column in columns:
            encodings: set[ValueEncoding] = set()
            statuses: set[RepresentationStatus | None] = set()
            unsupported = False
            column.value_encoding = None
            column.representation_status = None
            for row in encoded_rows:
                value = row[column.ordinal]
                if value is None:
                    continue
                try:
                    encoded, encoding = cls._contract_value(value)
                    if not cls._approved_codec(value, encoding, column.dtype):
                        raise TypeError("no approved codec for this dtype/value pair")
                    row[column.ordinal] = encoded
                    encodings.add(encoding)
                    statuses.add(cls._representation_status(value, encoded, encoding, column.dtype))
                except TypeError:
                    unsupported = True
            if unsupported or len(encodings) > 1:
                column.representation_status = "unsupported"
                supported = False
            elif encodings:
                column.value_encoding = next(iter(encodings))
                # A known loss dominates uncertainty; uncertainty prevents an
                # all-values-preserved claim. NULL contributes no evidence.
                if "lossy" in statuses:
                    column.representation_status = "lossy"
                elif None not in statuses:
                    column.representation_status = "preserved"
        return encoded_rows if supported else None

    @staticmethod
    def _approved_codec(value: Any, encoding: ValueEncoding, dtype: str | None) -> bool:
        """Approve physical-type/codec pairs, not arbitrary serializable objects.

        Unknown dtype may retain an existing Python codec, but cannot establish
        physical fidelity. Known unreviewed types have no approved mapping.
        """
        if dtype is None:
            return True
        if encoding == "decimal_text":
            return isinstance(value, Decimal) and re.fullmatch(r"DECIMAL\([0-9]+,\s*[0-9]+\)", dtype) is not None
        if encoding == "iso_datetime":
            return isinstance(value, datetime) and dtype in {
                "TIMESTAMP", "TIMESTAMP_S", "TIMESTAMP_MS", "TIMESTAMP_NS",
                "TIMESTAMP WITH TIME ZONE",
            }
        if encoding == "iso_date":
            return type(value) is date and dtype == "DATE"
        if encoding == "native_json":
            return dtype in {
                str: {"VARCHAR"},
                bool: {"BOOLEAN"},
                int: {
                    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
                    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
                },
                float: {"FLOAT", "DOUBLE"},
            }.get(type(value), set())
        return False

    @staticmethod
    def _representation_status(
        value: Any, encoded: Any, encoding: ValueEncoding, dtype: str | None,
    ) -> RepresentationStatus | None:
        """Prove codec fidelity where possible without inspecting/re-running SQL.

        A successful round trip proves only the fetched Python value survived.
        dtype-specific driver ambiguities must still prevent ``preserved``.
        """
        if value is None:
            return None
        try:
            if encoding == "decimal_text" and type(encoded) is str:
                restored = Decimal(encoded)
                # Include decimal scale/sign as well as numerical equality.
                same = restored.is_finite() and restored.as_tuple() == value.as_tuple()
            elif encoding == "iso_datetime" and type(encoded) is str:
                restored = datetime.fromisoformat(encoded)
                same = (
                    restored.replace(tzinfo=None) == value.replace(tzinfo=None)
                    and restored.utcoffset() == value.utcoffset()
                )
            elif encoding == "iso_date" and type(encoded) is str:
                same = date.fromisoformat(encoded) == value
            elif encoding == "native_json":
                same = type(encoded) is type(value) and encoded == value
                if same and type(value) is float:
                    same = isfinite(encoded) and (
                        value != 0 or copysign(1, encoded) == copysign(1, value)
                    )
            else:
                return None
        except (ValueError, ArithmeticError, TypeError, AttributeError):
            # No successful reverse codec: do not fabricate a fidelity claim.
            return None
        if not same:
            return "lossy"
        if dtype is None:
            return None
        if isinstance(value, datetime):
            # Nanoseconds may already be gone before Python receives datetime;
            # aligned and unaligned source values cannot be distinguished here.
            if dtype == "TIMESTAMP_NS":
                return None
            # DuckDB infinity can collide with finite Python extrema. Keep the
            # boundary dates conservative, including timezone-aware sentinels.
            if value.date() in (date.min, date.max):
                return None
        elif isinstance(value, date) and value in (date.min, date.max):
            return None
        return "preserved"

    @staticmethod
    def _contract_value(value: Any) -> tuple[Any, ValueEncoding]:
        if isinstance(value, datetime):
            return value.isoformat(), "iso_datetime"
        if isinstance(value, date):
            return value.isoformat(), "iso_date"
        if isinstance(value, Decimal) and value.is_finite():
            return str(value), "decimal_text"
        if type(value) in (str, int, bool):
            return value, "native_json"
        if type(value) is float and isfinite(value):
            return value, "native_json"
        raise TypeError("value is not supported by the scalar result contract")

    @contextmanager
    def connect(self, database: str) -> Iterator[duckdb.DuckDBPyConnection]:
        """创建内存连接并将 CSV 文件注册为只读视图。"""
        folder = self._database_folder(database)
        connection = duckdb.connect(":memory:")
        try:
            csv_files = sorted(folder.glob("*.csv"))
            if not csv_files:
                raise ValueError(f"数据库文件夹没有CSV表：{folder}")
            for csv_path in csv_files:
                table = csv_path.stem
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                    raise ValueError(f"CSV文件名不能作为安全表名：{csv_path.name}")
                path = csv_path.resolve().as_posix().replace("'", "''")
                connection.execute(
                    f'CREATE VIEW "{table}" AS '
                    f"SELECT * FROM read_csv_auto('{path}', header=true, sample_size=-1)"
                )
            yield connection
        finally:
            connection.close()

    def _validate_sql(
        self,
        database: str,
        sql: str,
        access_scope: AccessScope | None = None,
    ) -> str:
        cleaned = self.clean_sql(sql).rstrip(";").strip()
        statements = [item for item in sqlglot.parse(cleaned, read="duckdb") if item]
        if len(statements) != 1:
            raise ValueError("一次只允许执行一条SQL")
        statement = statements[0]
        if not isinstance(statement, exp.Query):
            raise ValueError("只允许执行SELECT/WITH只读查询")
        forbidden_nodes = {
            "insert", "update", "delete", "merge", "create", "drop", "alter",
            "copy", "attach", "detach", "command", "transaction", "grant", "revoke",
        }
        if any(node.key in forbidden_nodes for node in statement.walk()):
            raise ValueError("SQL包含禁止的写入或管理操作")

        # 查询必须显式列出返回字段。
        for select in statement.find_all(exp.Select):
            if any(
                isinstance(projection, exp.Star)
                or isinstance(projection, exp.Column) and projection.is_star
                for projection in select.expressions
            ):
                raise ValueError("不允许使用SELECT *，必须明确列出查询字段")

        if access_scope and not access_scope.allows_database(database):
            raise ValueError("当前用户无权访问该数据库")

        allowed = {
            table["id"] for table in SCHEMA if table.get("database", "askdata_mock") == database
        }
        cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
        referenced = {
            table.name
            for table in statement.find_all(exp.Table)
            if table.name not in cte_names
        }
        unknown = {name for name in referenced if name not in allowed}
        if unknown:
            raise ValueError(f"SQL引用了未知数据表：{', '.join(sorted(unknown))}")
        if access_scope:
            denied = {
                table
                for table in referenced
                if not access_scope.allows_table(database, table)
            }
            if denied:
                raise ValueError("SQL引用了当前用户无权访问的数据表")
        return cleaned

    def _database_folder(self, database: str) -> Path:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database):
            raise ValueError("数据库名称不合法")
        folder = (self.database_root / database).resolve()
        root = self.database_root.resolve()
        if root not in folder.parents or not folder.is_dir():
            raise ValueError(f"本地CSV数据库不存在：{database}")
        return folder

    @staticmethod
    def clean_sql(text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:sql)?\s*|\s*```$", "", cleaned, flags=re.I)
        return cleaned.strip()

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        return value
