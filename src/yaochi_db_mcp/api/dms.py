"""
DMS (数据管理服务) API 封装

提供：
- get_tenant_id: 获取租户 ID（所有 DMS API 的前置依赖）
- search_database: 按关键词搜索数据库
- execute_script: 对指定数据库执行 SQL
"""

from __future__ import annotations

import json
import logging
from typing import Any

from alibabacloud_dms_enterprise20181101.client import Client as DmsClient
from alibabacloud_dms_enterprise20181101 import models as dms_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

from yaochi_db_mcp.auth import Credentials

logger = logging.getLogger(__name__)

# 缓存 tenant_id，避免每次调用都请求
_tid_cache: dict[str, int] = {}


def _create_client(creds: Credentials, region: str | None = None) -> DmsClient:
    """创建 DMS Enterprise 客户端。"""
    region_id = region or creds.region_id
    config = open_api_models.Config(
        access_key_id=creds.access_key_id,
        access_key_secret=creds.access_key_secret,
        security_token=creds.security_token,
        region_id=region_id,
        endpoint=f"dms-enterprise.{region_id}.aliyuncs.com",
        user_agent=creds.user_agent,
    )
    return DmsClient(config)


def _runtime() -> util_models.RuntimeOptions:
    return util_models.RuntimeOptions(
        read_timeout=15000,
        connect_timeout=10000,
    )


def get_tenant_id(creds: Credentials, region: str | None = None) -> int:
    """获取当前用户的 DMS 租户 ID (Tid)。

    结果会被缓存，同一 AK 不会重复请求。
    """
    cache_key = creds.access_key_id
    if cache_key in _tid_cache:
        return _tid_cache[cache_key]

    client = _create_client(creds, region)
    request = dms_models.GetUserActiveTenantRequest()
    response = client.get_user_active_tenant_with_options(request, _runtime())

    body = response.body
    if not body.success:
        raise RuntimeError(f"获取 DMS 租户 ID 失败: {body.error_message}")

    tid = body.tenant.tid
    _tid_cache[cache_key] = tid
    logger.info("DMS 租户 ID: %s", tid)
    return tid


def search_database(
    creds: Credentials,
    keyword: str,
    region: str | None = None,
) -> list[dict[str, Any]]:
    """按关键词搜索 DMS 中注册的数据库。

    Args:
        creds: 凭证
        keyword: 搜索关键词（数据库名、schema 名等）
        region: 地域，不传则使用凭证默认地域

    Returns:
        数据库信息列表，每项包含 database_id, schema_name, db_type, host, port 等
    """
    tid = get_tenant_id(creds, region)
    client = _create_client(creds, region)

    request = dms_models.SearchDatabaseRequest(tid=tid, search_key=keyword)
    response = client.search_database_with_options(request, _runtime())

    body = response.body
    if not body.success:
        raise RuntimeError(f"搜索数据库失败: {body.error_message}")

    db_list = body.search_database_list
    if not db_list or not db_list.search_database:
        return []

    results = []
    for db in db_list.search_database:
        results.append({
            "database_id": db.database_id,
            "schema_name": db.schema_name,
            "db_type": db.db_type,
            "host": db.host,
            "port": db.port,
            "env_type": db.env_type,
            "encoding": db.encoding,
        })
    return results


def execute_script(
    creds: Credentials,
    database_id: int,
    sql: str,
    logic: bool = False,
    region: str | None = None,
) -> dict[str, Any]:
    """对指定数据库执行 SQL 脚本。

    Args:
        creds: 凭证
        database_id: 数据库 ID（从 search_database 获取）
        sql: SQL 语句
        logic: 是否使用逻辑库模式
        region: 地域

    Returns:
        执行结果字典，包含 columns（列名列表）和 rows（行数据列表）
    """
    tid = get_tenant_id(creds, region)
    client = _create_client(creds, region)

    request = dms_models.ExecuteScriptRequest(
        tid=tid,
        db_id=database_id,
        script=sql,
        logic=logic,
    )
    response = client.execute_script_with_options(request, _runtime())

    body = response.body
    if not body.success:
        raise RuntimeError(f"执行 SQL 失败: {body.error_message}")

    return _format_results(body.results)


def _format_results(results: Any) -> dict[str, Any]:
    """将 DMS ExecuteScript 结果格式化为可读格式。"""
    # results 可能是 list 或带 .results 属性的对象
    if not results:
        return {"message": "执行成功，无返回结果", "result_sets": []}

    items = results if isinstance(results, list) else getattr(results, 'results', None)
    if not items:
        return {"message": "执行成功，无返回结果", "result_sets": []}

    result_sets = []
    for result in items:
        rs: dict[str, Any] = {}

        if not result.success:
            rs["error"] = result.message or "执行失败"
            result_sets.append(rs)
            continue

        # 列名
        columns = list(result.column_names) if result.column_names else []
        rs["columns"] = columns
        rs["row_count"] = result.row_count or 0

        # 行数据 — rows 可能是 list 或带 .row 属性的对象
        rows = []
        raw_rows = result.rows
        if raw_rows:
            row_list = raw_rows if isinstance(raw_rows, list) else getattr(raw_rows, 'row', None) or []
            for row in row_list:
                if isinstance(row, dict):
                    rows.append(row)
                elif isinstance(row, list):
                    if columns:
                        rows.append(dict(zip(columns, row)))
                    else:
                        rows.append(row)
                elif hasattr(row, 'row_value'):
                    row_values = list(row.row_value) if row.row_value else []
                    if columns:
                        rows.append(dict(zip(columns, row_values)))
                    else:
                        rows.append(row_values)
                else:
                    rows.append(str(row))
        rs["rows"] = rows
        result_sets.append(rs)

    return {"result_sets": result_sets}


# ── DMS 实例注册 ───────────────────────────────

# 数据库引擎到 DMS InstanceType 的映射
_ENGINE_TO_DMS_TYPE = {
    "rds-mysql": "MySQL",
    "polardb-mysql": "polardb_mysql",
    "mongodb": "MongoDB",
    "tair": "Redis",
}


def _get_current_uid(creds: Credentials, region: str | None = None) -> int:
    """获取当前 DMS 用户的 UID，用作 DBA UID。"""
    client = _create_client(creds, region)
    # 优先用 GetUser（需管理员权限）
    try:
        request = dms_models.GetUserRequest()
        response = client.get_user_with_options(request, _runtime())
        if response.body.success:
            return response.body.user.uid
    except Exception:
        pass
    # fallback: 用 GetUserActiveTenant 间接获取
    return -1


def register_instance(
    creds: Credentials,
    host: str,
    port: int,
    engine: str,
    instance_alias: str,
    database_user: str = "",
    database_password: str = "",
    region: str | None = None,
    env_type: str = "dev",
) -> dict[str, Any]:
    """将数据库实例注册到 DMS。

    Args:
        host: 实例连接地址
        port: 连接端口
        engine: 引擎类型 (rds-mysql / polardb-mysql / mongodb / tair)
        instance_alias: 实例别名
        database_user: 数据库账号
        database_password: 数据库密码
        region: 地域
        env_type: 环境类型 (dev/test/product)
    """
    region_id = region or creds.region_id
    client = _create_client(creds, region)
    tid = get_tenant_id(creds, region)

    # 获取 DMS 类型
    dms_type = _ENGINE_TO_DMS_TYPE.get(engine)
    if not dms_type:
        raise ValueError(f"不支持的引擎类型: {engine}")

    # 根据引擎确定 instance_source
    # - RDS MySQL: source="RDS"，DMS 能直接验证 RDS 实例
    # - PolarDB MySQL: source="VPC_IDC"，以 MySQL 类型注册（DMS 无法通过 RDS source 找到 PolarDB）
    # - Tair/MongoDB: source="RDS"，但实际执行命令走直连（DMS 不支持 NoSQL ExecuteScript）
    if engine == "polardb-mysql":
        instance_source = "VPC_IDC"
        dms_type = "mysql"  # PolarDB 在 DMS 中注册为 mysql 类型
    else:
        instance_source = "RDS"

    # 获取当前用户 UID 作为 DBA
    try:
        dba_uid = _get_current_uid(creds, region)
    except Exception:
        dba_uid = -1  # fallback

    request = dms_models.RegisterInstanceRequest(
        tid=tid,
        instance_type=dms_type,
        instance_source=instance_source,
        network_type="VPC",
        env_type=env_type,
        ecs_region=region_id,
        host=host,
        port=port,
        database_user=database_user or "default",
        database_password=database_password or "",
        instance_alias=instance_alias,
        dba_uid=dba_uid,
        safe_rule="",
        query_timeout=60,
        export_timeout=600,
        skip_test=not bool(database_password),  # 有密码则验证连通性
    )

    response = client.register_instance_with_options(request, _runtime())
    body = response.body

    if not body.success:
        raise RuntimeError(f"DMS 注册失败: {body.error_message}")

    # 注册后尝试同步元数据
    try:
        get_req = dms_models.GetInstanceRequest(tid=tid, host=host, port=port)
        get_resp = client.get_instance_with_options(get_req, _runtime())
        if get_resp.body.success and get_resp.body.instance:
            dms_instance_id = str(get_resp.body.instance.instance_id)
            sync_req = dms_models.SyncInstanceMetaRequest(
                tid=tid, instance_id=dms_instance_id
            )
            client.sync_instance_meta_with_options(sync_req, _runtime())
    except Exception:
        pass  # 同步失败不影响注册结果

    return {
        "success": True,
        "message": f"实例 {instance_alias} 已成功注册到 DMS",
        "host": host,
        "port": port,
        "engine": engine,
    }
