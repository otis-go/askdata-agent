from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..querying.result_contract import ResultContract


class DateTimeResult(BaseModel):
    date: str = Field(description="当前日期，格式为YYYY-MM-DD")
    datetime: str = Field(description="包含时区的当前时间")
    timezone: str = Field(description="返回结果使用的时区")


class DateRangeResult(BaseModel):
    expression: str = Field(description="输入的相对时间表达式")
    start_date: str = Field(description="起始日期，格式为YYYY-MM-DD")
    end_date: str = Field(description="结束日期，格式为YYYY-MM-DD，包含当天")
    timezone: str = Field(description="计算日期范围时使用的时区")


class DatabaseQueryResult(BaseModel):
    database: str = Field(description="执行查询的数据库名称")
    sql: str = Field(description="实际执行或尝试执行的SQL")
    success: bool = Field(description="SQL是否执行成功")
    columns: list[str] = Field(default_factory=list, description="结果字段")
    rows: list[dict[str, Any]] = Field(default_factory=list, description="查询结果，最多200行")
    row_count: int = Field(default=0, description="返回结果行数")
    error: str | None = Field(default=None, description="执行失败时的错误信息")
    result_contract: ResultContract | None = Field(default=None, description="查询执行结果的语义契约")
    result_id: str | None = Field(default=None, description="同一次SQL执行的标识")
