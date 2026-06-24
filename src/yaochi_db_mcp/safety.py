"""  
SQL / Redis / MongoDB 命令安全分级模块 (v2)

策略调整（借鉴 RDS OpenAPI MCP Server）：
- 直接拒绝包含注释（--, #, /*）的 SQL — 比剥离注释更安全
- 正则检测危险关键词（防止子查询中藏 DDL）
- SQL 长度上限 10000
- 写操作受环境变量开关控制

Redis 分级：
- safe:      GET / SET / HGET / KEYS / INFO 等常规读写 — 直接执行
- dangerous: FLUSHALL / FLUSHDB / SHUTDOWN / DEBUG / CONFIG SET — 拒绝执行
"""

from __future__ import annotations

import os
import re


# ── 环境变量控制写操作 ────────────────────────────────

ENABLE_WRITE_SQL = os.environ.get(
    "YAOCHI_ENABLE_WRITE_SQL", "true"
).lower() in ("true", "1", "yes")

ENABLE_DDL_SQL = os.environ.get(
    "YAOCHI_ENABLE_DDL_SQL", "false"
).lower() in ("true", "1", "yes")


# ── SQL 安全校验 ──────────────────────────────────────

MAX_SQL_LENGTH = 10000

_LEADING_KEYWORD_PATTERN = re.compile(r"^\s*([A-Za-z]+)")

_DANGEROUS_KEYWORD_PATTERN = re.compile(
    r"\b(drop|truncate|alter|rename|grant|revoke|kill|shutdown)\b",
    re.IGNORECASE,
)

_READONLY_KEYWORDS = frozenset(
    {"select", "show", "desc", "describe", "explain", "use"}
)
_WRITE_KEYWORDS = frozenset(
    {"insert", "update", "delete", "replace", "merge"}
)
_DDL_KEYWORDS = frozenset({"create"})
_DANGEROUS_KEYWORDS = frozenset({"drop", "truncate", "alter", "rename"})


def check_sql_safety(sql: str) -> tuple[bool, str]:
    """检查 SQL 安全性（v2 — 借鉴 RDS MCP 的严格模式）。

    Returns:
        (allowed, message):
        - allowed=True, message="" — 安全，可直接执行
        - allowed=True, message=非空 — 需 force 确认
        - allowed=False — 拒绝执行
    """
    if not isinstance(sql, str) or not sql.strip():
        return False, "SQL 不能为空。"

    stripped = sql.strip()

    # 1. 长度检查
    if len(stripped) > MAX_SQL_LENGTH:
        return False, f"SQL 超出最大长度限制（{MAX_SQL_LENGTH} 字符）。"

    # 2. 拒绝注释 — 防止注释绕过
    if "--" in stripped or "#" in stripped or "/*" in stripped:
        return False, (
            "🚫 SQL 中不允许包含注释（--, #, /*）。\n"
            "请去除注释后重新提交。"
        )

    # 3. 拒绝多语句（分号 — 允许末尾分号）
    if ";" in stripped[:-1]:
        return False, "🚫 不支持多语句 SQL。请每次只提交一条 SQL。"

    # 4. 提取首个关键词
    match = _LEADING_KEYWORD_PATTERN.match(stripped)
    if not match:
        return False, "无法识别的 SQL 语句。"
    leading = match.group(1).lower()

    # 5. 分级判断
    if leading in _READONLY_KEYWORDS:
        # 即使是 SELECT，也检查是否藏了危险操作
        if _DANGEROUS_KEYWORD_PATTERN.search(stripped):
            return False, "🚫 只读 SQL 中检测到危险关键词，拒绝执行。"
        return True, ""

    if leading in _DANGEROUS_KEYWORDS:
        return False, (
            "🚫 危险 DDL 操作（DROP / TRUNCATE / ALTER / RENAME）不允许通过此工具执行。\n"
            "请前往 DMS 控制台操作: https://dms.aliyun.com"
        )

    if leading in _DDL_KEYWORDS:
        if not ENABLE_DDL_SQL:
            return False, (
                "🚫 DDL 操作（CREATE）当前未启用。\n"
                "请设置环境变量 YAOCHI_ENABLE_DDL_SQL=true 开启。"
            )
        return True, "⚠️ DDL 操作，请确认后执行。"

    if leading in _WRITE_KEYWORDS:
        if not ENABLE_WRITE_SQL:
            return False, (
                "🚫 写操作（INSERT/UPDATE/DELETE）当前未启用。\n"
                "请设置环境变量 YAOCHI_ENABLE_WRITE_SQL=true 开启。"
            )
        return True, (
            f"⚠️ 检测到写操作，请确认后执行。\n"
            f"SQL: {stripped[:200]}{'...' if len(stripped) > 200 else ''}"
        )

    # unknown — 默认允许但提示
    return True, f"⚠️ 未识别的 SQL 类型，请确认后执行: {stripped[:100]}"


# ── Redis 命令安全检查 ───────────────────────────────

_DANGEROUS_REDIS_COMMANDS = (
    "FLUSHALL", "FLUSHDB", "SHUTDOWN", "DEBUG",
    "CONFIG SET", "CONFIG REWRITE", "CONFIG RESETSTAT",
    "SLAVEOF", "REPLICAOF", "CLUSTER RESET",
    "BGREWRITEAOF", "BGSAVE", "SAVE",
    "MODULE LOAD", "MODULE UNLOAD",
    "ACL SETUSER", "ACL DELUSER",
)


def check_redis_safety(command: str) -> tuple[bool, str]:
    """检查 Redis 命令是否允许执行。

    Returns:
        (allowed, message):
        - allowed=True 表示可以执行
        - allowed=False 表示必须拒绝（危险命令）
    """
    cmd_upper = command.strip().upper()

    for dangerous in _DANGEROUS_REDIS_COMMANDS:
        if cmd_upper.startswith(dangerous):
            return False, (
                f"🚫 危险 Redis 命令（{dangerous}）不允许通过此工具执行。\n"
                f"请前往 DMS 控制台操作: https://dms.aliyun.com"
            )

    return True, ""


# ── MongoDB 命令安全检查 ───────────────────────

_DANGEROUS_MONGO_OPERATIONS = (
    "drop", "dropDatabase", "dropIndexes",
    "shutdown", "replSetReconfig",
    "renameCollection",
)


def check_mongo_safety(operation: str) -> tuple[bool, str]:
    """检查 MongoDB 操作是否允许执行。

    Returns:
        (allowed, message):
        - allowed=True 表示可以执行
        - allowed=False 表示必须拒绝（危险操作）
    """
    for dangerous in _DANGEROUS_MONGO_OPERATIONS:
        if dangerous in operation:
            return False, (
                f"🚫 危险 MongoDB 操作（{dangerous}）不允许通过此工具执行。\n"
                f"请前往 DMS 控制台操作: https://dms.aliyun.com"
            )

    return True, ""
