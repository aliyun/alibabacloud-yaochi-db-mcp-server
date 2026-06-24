"""
瑶池数据库 AI Native MCP Server

提供十个工具：
- search_database:      按关键词搜索 DMS 中的数据库
- execute_sql:          对指定数据库执行 SQL（通过 DMS）
- execute_instance_sql: 通过实例 ID 直接执行 SQL（自动开公网 + 配置白名单 + 临时账号）
- execute_mysql:        直连 MySQL/PolarDB MySQL 实例执行 SQL
- execute_redis:        直连 Tair/Redis 实例执行命令
- execute_mongo:        直连 MongoDB 实例执行命令
- create_instance:      创建数据库实例 (RDS MySQL / PolarDB MySQL / MongoDB / Tair)
- list_instances:       列出已有数据库实例
- register_to_dms:     将实例注册到 DMS
- ask_yaochi_agent:    瑶池 Agent 大模型问答（知识问答、性能诊断等）

启动方式：
  yaochi-db-mcp-server          # console_scripts 入口
  python -m yaochi_db_mcp  # __main__ 入口
  uvx alibabacloud-yaochi-db-mcp-server  # uvx 免安装运行
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from yaochi_db_mcp.auth import Credentials, load_credentials
from yaochi_db_mcp.safety import check_sql_safety, check_redis_safety, check_mongo_safety
from yaochi_db_mcp.api import dms, instances

logger = logging.getLogger(__name__)

# ── MCP Server 实例 ──────────────────────────────────────────

mcp = FastMCP(
    "yaochi-db",
    instructions=(
        "瑶池数据库 AI Native MCP Server。\n"
        "提供阿里云数据库的创建实例、搜索数据库、执行 SQL/Redis 命令等能力。\n"
        "支持 RDS MySQL、PolarDB MySQL、MongoDB、Tair 四种引擎。\n"
        "推荐使用 execute_instance_sql 工具（临时账号模式）完成创建实例后的 SQL 执行验证。"
    ),
)

# ── 凭证懒加载 ───────────────────────────────────────────────

_creds: Credentials | None = None


def _get_creds() -> Credentials:
    """懒加载凭证（首次调用时初始化）。"""
    global _creds
    if _creds is None:
        _creds = load_credentials()
    return _creds


def _json_result(data: Any) -> str:
    """将结果转换为 JSON 字符串，供 AI 解析。"""
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ── 工具定义 ─────────────────────────────────────────────────


@mcp.tool()
def search_database(keyword: str, region: str = "") -> str:
    """按关键词搜索 DMS 中注册的数据库，获取 database_id 用于后续 execute_sql。

    在执行 SQL 之前，需要先用此工具搜索目标数据库，获取其 database_id。

    Args:
        keyword: 搜索关键词（数据库名、schema 名、host 等）
        region: 地域 ID（如 cn-hangzhou），不传则使用默认地域
    """
    try:
        creds = _get_creds()
        results = dms.search_database(
            creds, keyword, region=region or None
        )

        if not results:
            return f"未找到包含关键词 '{keyword}' 的数据库。请确认数据库已在 DMS 中注册。"

        return _json_result({
            "total": len(results),
            "databases": results,
            "hint": "使用 database_id 调用 execute_sql 执行 SQL 查询",
        })
    except Exception as e:
        return f"搜索数据库失败: {e}"


@mcp.tool()
def execute_sql(
    database_id: int,
    sql: str,
    force: bool = False,
    logic: bool = False,
    region: str = "",
) -> str:
    """对指定数据库执行 SQL 查询或写入操作。

    使用前需先通过 search_database 获取 database_id。

    安全规则：
    - SELECT/SHOW/DESC 等只读操作：直接执行
    - INSERT/UPDATE/DELETE 等写操作：需设置 force=true 确认后执行
    - DROP/TRUNCATE/ALTER/RENAME 等危险 DDL：拒绝执行，请到 DMS 控制台操作

    Args:
        database_id: 数据库 ID（从 search_database 结果中获取）
        sql: 要执行的 SQL 语句
        force: 写操作确认标志，执行 INSERT/UPDATE/DELETE 时需设为 true
        logic: 是否使用逻辑库模式（默认 false）
        region: 地域 ID，不传则使用默认地域
    """
    try:
        # 安全检查
        allowed, message = check_sql_safety(sql)
        if not allowed:
            return message

        # 写操作需要 force 确认
        if message and not force:
            return (
                f"{message}\n\n"
                "如需执行，请将 force 参数设为 true 再次调用。"
            )

        creds = _get_creds()
        result = dms.execute_script(
            creds, database_id, sql, logic=logic, region=region or None
        )
        return _json_result(result)
    except Exception as e:
        return f"执行 SQL 失败: {e}"


@mcp.tool()
def execute_instance_sql(
    instance_id: str,
    sql: str,
    database: str = "",
    engine: str = "rds-mysql",
    region: str = "",
    force: bool = False,
) -> str:
    """通过实例 ID 直接执行 SQL（自动开通公网 + 配置白名单 + 临时账号模式）。

    自动流程：
    1. 通过 OpenAPI 确保目标数据库存在
    2. 尝试 TCP 直连（优先 VPC 内网，其次公网）
    3. TCP 不通时自动开通公网地址 + 探测 IP 配置白名单，然后重试

    安全规则：
    - SELECT/SHOW/DESC 等只读操作：直接执行
    - INSERT/UPDATE/DELETE 等写操作：需设置 force=true（受环境变量 YAOCHI_ENABLE_WRITE_SQL 控制）
    - CREATE TABLE 等 DDL：需设置 force=true（受环境变量 YAOCHI_ENABLE_DDL_SQL 控制）
    - DROP/TRUNCATE/ALTER/RENAME：拒绝执行

    Args:
        instance_id: 实例 ID（从 create_instance 或 list_instances 获取）
        sql: 要执行的 SQL 语句
        database: 目标数据库名（可选，不传则不指定默认库）
        engine: 引擎类型（rds-mysql / polardb-mysql）
        region: 地域 ID，不传使用默认地域
        force: 写操作确认标志，执行 INSERT/UPDATE/DELETE/CREATE 时需设为 true
    """
    try:
        # 安全检查
        allowed, message = check_sql_safety(sql)
        if not allowed:
            return message
        if message and not force:
            return (
                f"{message}\n\n"
                "如需执行，请将 force 参数设为 true 再次调用。"
            )

        creds = _get_creds()
        region_id = region or creds.region_id
        engine_lower = engine.lower().strip()

        from yaochi_db_mcp.api.db_service import RDSDBService, PolarDBDBService

        # 策略：先尝试 TCP 直连
        try:
            if engine_lower == "polardb-mysql":
                with PolarDBDBService(
                    creds, region_id, instance_id, database
                ) as svc:
                    result = svc.execute_sql(sql)
            else:
                with RDSDBService(
                    creds, region_id, instance_id, database
                ) as svc:
                    result = svc.execute_sql(sql)
            return _json_result(result)
        except RuntimeError as e:
            if "均不可达" not in str(e) and "无法连接" not in str(e):
                raise  # 非连接问题，直接报错
            logger.info("TCP 直连不可达，自动开通公网访问: %s", e)

        # TCP 不通：自动开通公网地址 + 配置白名单
        from yaochi_db_mcp.api.common import detect_public_ip
        my_ip = detect_public_ip()
        if not my_ip:
            return (
                f"执行 SQL 失败: 实例 {instance_id} TCP 不可达，"
                f"且无法探测本机公网 IP（自动开通公网需要先获取 IP）。\n"
                f"请检查网络连通性，或手动在 RDS 控制台开通公网地址。"
            )

        public_addr = instances.ensure_public_access(
            creds, instance_id, engine_lower, region_id
        )
        if not public_addr:
            return (
                f"执行 SQL 失败: 实例 {instance_id} TCP 不可达，"
                f"已探测到 IP({my_ip}) 但开通公网地址失败。\n"
                f"请检查：1) 实例已就绪(Running) 2) RAM 权限包含 AllocateInstancePublicConnection"
            )

        # 公网已开通，等待端点生效后重试 TCP 直连
        import time
        logger.info("公网已开通(%s)，等待 3s 后重试连接...", public_addr)
        time.sleep(3)

        if engine_lower == "polardb-mysql":
            with PolarDBDBService(
                creds, region_id, instance_id, database
            ) as svc:
                result = svc.execute_sql(sql)
        else:
            with RDSDBService(
                creds, region_id, instance_id, database
            ) as svc:
                result = svc.execute_sql(sql)

        result["note"] = f"已自动开通公网地址({public_addr})并配置白名单"
        return _json_result(result)
    except Exception as e:
        return f"执行 SQL 失败: {e}"


@mcp.tool()
def execute_mysql(
    host: str,
    sql: str,
    user: str = "root",
    password: str = "",
    database: str = "",
    port: int = 3306,
    force: bool = False,
) -> str:
    """直连 MySQL/PolarDB MySQL 实例执行 SQL（需提供账号密码）。

    💡 推荐使用 execute_instance_sql — 基于实例ID自动管理临时账号，无需密码。
    本工具适用于已有账号密码的场景。

    安全规则：
    - SELECT/SHOW/DESC 等只读操作：直接执行
    - INSERT/UPDATE/DELETE 等写操作：需设置 force=true 确认后执行
    - DROP/TRUNCATE/ALTER/RENAME 等危险 DDL：拒绝执行

    Args:
        host: MySQL 连接地址（如 pc-xxx.rwlb.rds.aliyuncs.com）
        sql: 要执行的 SQL 语句
        user: 数据库账号（默认 root）
        password: 数据库密码
        database: 数据库名（可选）
        port: 端口（默认 3306）
        force: 写操作确认标志，执行 INSERT/UPDATE/DELETE 时需设为 true
    """
    try:
        # 安全检查
        allowed, message = check_sql_safety(sql)
        if not allowed:
            return message

        # 写操作需要 force 确认
        if message and not force:
            return (
                f"{message}\n\n"
                "如需执行，请将 force 参数设为 true 再次调用。"
            )

        import pymysql

        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database or None,
            connect_timeout=10,
            read_timeout=30,
            charset="utf8mb4",
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                # 判断是否有结果集
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    result = {
                        "columns": columns,
                        "rows": [list(row) for row in rows],
                        "row_count": len(rows),
                    }
                else:
                    conn.commit()
                    result = {
                        "affected_rows": cursor.rowcount,
                        "message": "SQL 执行成功",
                    }
        finally:
            conn.close()

        return _json_result(result)
    except Exception as e:
        return f"执行 MySQL SQL 失败: {e}"


@mcp.tool()
def execute_redis(
    host: str,
    command: str,
    password: str = "",
    port: int = 6379,
    db: int = 0,
) -> str:
    """对指定 Tair/Redis 实例直接执行 Redis 命令。

    直连 Tair/Redis 实例执行命令，无需通过 DMS。
    连接地址可从 list_instances 结果中获取。

    安全规则：
    - GET/SET/HGET/KEYS/INFO 等常规命令：直接执行
    - FLUSHALL/FLUSHDB/SHUTDOWN 等危险命令：拒绝执行

    Args:
        host: Redis 连接地址（如 r-bp15f6006905b3e4.redis.rds.aliyuncs.com）
        command: Redis 命令（如 "SET key value"、"GET key"、"HGETALL hash"）
        password: 实例密码
        port: 端口，默认 6379
        db: 数据库索引，默认 0
    """
    try:
        # 安全检查
        allowed, message = check_redis_safety(command)
        if not allowed:
            return message

        import redis as redis_lib
        import shlex

        client = redis_lib.Redis(
            host=host,
            port=port,
            password=password or None,
            db=db,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=10,
            protocol=2,  # RESP2 兼容 Tair/Redis 5.0+
        )

        # 解析命令
        parts = shlex.split(command)
        result = client.execute_command(*parts)
        client.close()

        return _json_result({"result": result})
    except Exception as e:
        return f"执行 Redis 命令失败: {e}"


@mcp.tool()
def execute_mongo(
    host: str,
    command: str,
    database: str = "test",
    password: str = "",
    port: int = 3717,
) -> str:
    """对指定 MongoDB 实例直接执行命令。

    直连 MongoDB 实例执行命令，无需通过 DMS。
    连接地址可从 list_instances 结果中获取。

    command 为 JSON 格式字符串，支持的操作：
    - 插入: {"insert": "collection", "documents": [{...}]}
    - 查询: {"find": "collection", "filter": {...}}
    - 更新: {"update": "collection", "updates": [{"q": {...}, "u": {...}}]}
    - 删除: {"delete": "collection", "deletes": [{"q": {...}, "limit": 0}]}
    - 统计: {"count": "collection", "query": {...}}

    安全规则：
    - insert/find/update/delete/count 等常规操作：直接执行
    - drop/dropDatabase/shutdown 等危险操作：拒绝执行

    Args:
        host: MongoDB 连接地址（如 dds-bp1xxx.mongodb.rds.aliyuncs.com）
        command: MongoDB 命令（JSON 格式字符串）
        database: 数据库名（默认 test）
        password: root 密码
        port: 端口（默认 3717）
    """
    try:
        # 安全检查
        allowed, message = check_mongo_safety(command)
        if not allowed:
            return message

        import pymongo
        from urllib.parse import quote_plus

        # 构建连接 URI（密码需 URL 编码）
        if password:
            uri = f"mongodb://root:{quote_plus(password)}@{host}:{port}/admin"
        else:
            uri = f"mongodb://{host}:{port}/"
        client = pymongo.MongoClient(
            uri,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=10000,
            directConnection=True,
        )

        db = client[database]
        cmd = json.loads(command)
        result = db.command(cmd)
        client.close()

        # 简化输出
        if isinstance(result, dict):
            result.pop("$clusterTime", None)
            result.pop("operationTime", None)
            result.pop("electionId", None)

        return _json_result({"result": result})
    except Exception as e:
        return f"执行 MongoDB 命令失败: {e}"


@mcp.tool()
def register_to_dms(
    host: str,
    port: int,
    engine: str,
    instance_alias: str,
    database_user: str = "",
    database_password: str = "",
    region: str = "",
    env_type: str = "dev",
) -> str:
    """将数据库实例注册到 DMS，注册后即可通过 search_database 找到并执行 SQL/Redis 命令。

    创建实例后必须注册到 DMS 才能使用 execute_sql / execute_redis。

    Args:
        host: 实例连接地址（如 rm-xxx.mysql.rds.aliyuncs.com 或 r-xxx.redis.rds.aliyuncs.com）
        port: 连接端口（MySQL: 3306, Redis: 6379）
        engine: 引擎类型（rds-mysql / polardb-mysql / mongodb / tair）
        instance_alias: 实例别名（在 DMS 中显示的名称）
        database_user: 数据库账号（可选，默认 default）
        database_password: 数据库密码（可选，注册时可跳过连通性测试）
        region: 地域 ID，不传则使用默认地域
        env_type: 环境类型（dev / test / product，默认 dev）
    """
    try:
        creds = _get_creds()
        result = dms.register_instance(
            creds,
            host=host,
            port=port,
            engine=engine,
            instance_alias=instance_alias,
            database_user=database_user,
            database_password=database_password,
            region=region or None,
            env_type=env_type,
        )
        return _json_result(result)
    except Exception as e:
        return f"DMS 注册失败: {e}"


@mcp.tool()
def create_instance(
    engine: str,
    region: str = "",
    instance_name: str = "",
    vpc_id: str = "",
    vswitch_id: str = "",
    database_name: str = "testdb",
) -> str:
    """创建数据库实例。

    支持的引擎：
    - mongodb: MongoDB 副本集（默认 7.0, 2C4G, 20GB, 按量付费）
    - rds-mysql: RDS MySQL 基础版（默认 8.0, 2C4G, 20GB ESSD, 按量付费）
    - polardb-mysql: PolarDB MySQL 集群（默认 8.0, 2C8G, 按量付费）
    - tair: Tair 内存型（默认 Redis 7.0, 主从架构, 按量付费）

    VPC 和 VSwitch 不传时会自动探测区域内第一个可用的。
    实例就绪后首次执行 SQL 时将自动开通公网地址并配置白名单。

    Args:
        engine: 数据库引擎（mongodb / rds-mysql / polardb-mysql / tair）
        region: 地域 ID（如 cn-hangzhou），不传则使用默认地域
        instance_name: 实例名称（可选）
        vpc_id: VPC ID（可选，自动探测）
        vswitch_id: VSwitch ID（可选，自动探测）
        database_name: 初始数据库名（RDS/PolarDB 有效，默认 testdb）
    """
    try:
        creds = _get_creds()
        result = instances.create_instance(
            creds,
            engine=engine,
            region=region or None,
            instance_name=instance_name,
            vpc_id=vpc_id,
            vswitch_id=vswitch_id,
            database_name=database_name,
        )
        # 返回时提示用户公网连接将自动配置
        result["public_access"] = "实例就绪后首次执行 SQL 时将自动开通公网地址 + 配置白名单(当前机器 IP)"
        return _json_result(result)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"创建实例失败: {e}"


@mcp.tool()
def list_instances(engine: str = "", region: str = "") -> str:
    """列出已有的数据库实例。

    可以按引擎类型筛选，也可以查看所有支持产品的实例。

    Args:
        engine: 筛选引擎类型（可选：mongodb / rds-mysql / polardb-mysql / tair，留空查所有）
        region: 地域 ID（如 cn-hangzhou），不传则使用默认地域
    """
    try:
        creds = _get_creds()
        result = instances.list_instances(
            creds, engine=engine, region=region or None
        )

        if not result:
            return "当前区域下未找到数据库实例。"

        return _json_result({
            "total": len(result),
            "instances": result,
        })
    except Exception as e:
        return f"查询实例列表失败: {e}"


# ── 入口 ─────────────────────────────────────────────


@mcp.tool()
def ask_yaochi_agent(
    query: str,
    session_id: str = "",
    source: str = "yaochi",
    region: str = "",
) -> str:
    """瑶池 Agent 大模型能力接口 — 数据库知识问答、性能诊断、最佳实践建议。

    通过自然语言与瑶池 Agent 对话，可以：
    - 咨询数据库使用问题（如"如何优化慢查询"、"PolarDB 分区表怎么设计"）
    - 实例性能诊断（如"我的实例 rm-xxx 有没有异常"）
    - 获取云数据库最佳实践建议
    - 多轮对话（保持同一个 session_id）

    Args:
        query: 自然语言问题
        session_id: 会话 ID（UUID 格式），不传则创建新会话，续问时传入上次返回的 session_id
        source: 云产品来源（yaochi / tair / polardb / mongodb / polardb-ai / lindorm）
        region: 地域 ID，不传使用默认地域
    """
    try:
        creds = _get_creds()
        from yaochi_db_mcp.api.das import ask_yaochi_agent as _ask_agent

        result = _ask_agent(
            creds,
            query=query,
            session_id=session_id,
            source=source,
            region=region or None,
        )
        return _json_result(result)
    except Exception as e:
        return f"瑶池 Agent 调用失败: {e}"


# ── 入口 ─────────────────────────────────────────────────────


def main() -> None:
    """MCP Server 入口函数。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    mcp.run()


if __name__ == "__main__":
    main()
