"""
数据库实例管理 API 封装

首版支持：
- MongoDB (DDS)：创建副本集实例 / 列出实例
- RDS MySQL：创建基础版实例 / 列出实例
- VPC 自动探测：自动选取区域内第一个可用 VPC + VSwitch
"""

from __future__ import annotations

import logging
from typing import Any

from alibabacloud_dds20151201.client import Client as DdsClient
from alibabacloud_dds20151201 import models as dds_models
from alibabacloud_rds20140815.client import Client as RdsClient
from alibabacloud_rds20140815 import models as rds_models
from alibabacloud_polardb20170801.client import Client as PolarDBClient
from alibabacloud_polardb20170801 import models as polardb_models
from alibabacloud_r_kvstore20150101.client import Client as TairClient
from alibabacloud_r_kvstore20150101 import models as tair_models
from alibabacloud_vpc20160428.client import Client as VpcClient
from alibabacloud_vpc20160428 import models as vpc_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

from yaochi_db_mcp.auth import Credentials
from yaochi_db_mcp.api.common import make_config, runtime, generate_password, detect_public_ip

logger = logging.getLogger(__name__)

# ── 支持的引擎 ──────────────────────────────────────────────

SUPPORTED_ENGINES = {
    "mongodb": "MongoDB 副本集（默认 7.0, 2C4G, 20GB）",
    "rds-mysql": "RDS MySQL 基础版（默认 8.0, 2C4G, 20GB ESSD）",
    "polardb-mysql": "PolarDB MySQL 集群（默认 8.0, 2C8G, ESSD）",
    "tair": "Tair 内存型（默认 社区版, 2GB, 主从架构）",
}

# ── 通用辅助 ─────────────────────────────────────────────────


def _runtime() -> util_models.RuntimeOptions:
    return runtime()


def _make_config(
    creds: Credentials, endpoint: str, region: str | None = None
) -> open_api_models.Config:
    return make_config(creds, endpoint, region)


# ── VPC 自动探测 ─────────────────────────────────────────────


def _detect_vpc(
    creds: Credentials, region: str
) -> tuple[str, str, str]:
    """自动探测区域内的 VPC 和 VSwitch。

    Returns:
        (vpc_id, vswitch_id, zone_id)

    Raises:
        RuntimeError: 找不到可用 VPC 或 VSwitch
    """
    config = _make_config(
        creds, f"vpc.{region}.aliyuncs.com", region
    )
    client = VpcClient(config)

    # 查询 VPC
    vpc_req = vpc_models.DescribeVpcsRequest(region_id=region, page_size=10)
    vpc_resp = client.describe_vpcs_with_options(vpc_req, _runtime())
    vpcs = vpc_resp.body.vpcs
    if not vpcs or not vpcs.vpc:
        raise RuntimeError(
            f"区域 {region} 下未找到 VPC。"
            f"请先在 VPC 控制台创建: https://vpc.console.aliyun.com/"
        )

    vpc_id = vpcs.vpc[0].vpc_id
    logger.info("自动选取 VPC: %s", vpc_id)

    # 查询该 VPC 下的 VSwitch
    vsw_req = vpc_models.DescribeVSwitchesRequest(
        region_id=region, vpc_id=vpc_id, page_size=10
    )
    vsw_resp = client.describe_vswitches_with_options(vsw_req, _runtime())
    vsws = vsw_resp.body.v_switches
    if not vsws or not vsws.v_switch:
        raise RuntimeError(
            f"VPC {vpc_id} 下未找到 VSwitch。"
            f"请先在 VPC 控制台创建: https://vpc.console.aliyun.com/"
        )

    vsw = vsws.v_switch[0]
    logger.info("自动选取 VSwitch: %s (zone=%s)", vsw.v_switch_id, vsw.zone_id)
    return vpc_id, vsw.v_switch_id, vsw.zone_id


# ── MongoDB ──────────────────────────────────────────────────


def _create_mongodb(
    creds: Credentials,
    region: str,
    instance_name: str,
    vpc_id: str,
    vswitch_id: str,
    zone_id: str,
) -> dict[str, Any]:
    """创建 MongoDB 副本集实例（开发默认规格）。"""
    config = _make_config(creds, "mongodb.aliyuncs.com", region)
    client = DdsClient(config)

    # 动态生成安全密码（替代硬编码）
    _password = generate_password(24)

    request = dds_models.CreateDBInstanceRequest(
        region_id=region,
        zone_id=zone_id,
        engine="MongoDB",
        engine_version="7.0",
        dbinstance_class="mdb.shard.4x.large.d",
        dbinstance_storage=20,
        replication_factor="3",
        storage_engine="WiredTiger",
        storage_type="cloud_essd1",
        network_type="VPC",
        vpc_id=vpc_id,
        v_switch_id=vswitch_id,
        account_password=_password,
        dbinstance_description=instance_name or "yaochi-mcp-mongodb",
        charge_type="PostPaid",
    )

    response = client.create_dbinstance_with_options(request, _runtime())
    body = response.body
    return {
        "engine": "mongodb",
        "instance_id": body.dbinstance_id,
        "account_password": _password,
        "region": region,
        "message": (
            f"MongoDB 实例创建成功: {body.dbinstance_id}\n"
            f"规格: 副本集 3 节点, 2C4G, 20GB\n"
            f"root 密码: {_password}\n"
            f"⚠️ 请妥善保存密码，后续连接时需要使用。\n"
            f"实例正在初始化中，通常需要 5-10 分钟。"
        ),
    }


def _list_mongodb(creds: Credentials, region: str) -> list[dict[str, Any]]:
    """列出 MongoDB 实例。"""
    config = _make_config(creds, "mongodb.aliyuncs.com", region)
    client = DdsClient(config)

    request = dds_models.DescribeDBInstancesRequest(
        region_id=region, page_size=50
    )
    response = client.describe_dbinstances_with_options(request, _runtime())

    instances = []
    db_instances = response.body.dbinstances
    if db_instances and db_instances.dbinstance:
        for inst in db_instances.dbinstance:
            instances.append({
                "engine": "mongodb",
                "instance_id": inst.dbinstance_id,
                "name": inst.dbinstance_description or "",
                "status": inst.dbinstance_status,
                "engine_version": inst.engine_version,
                "instance_class": inst.dbinstance_class,
                "region": inst.region_id,
                "zone": inst.zone_id,
                "network_type": inst.network_type,
                "charge_type": inst.charge_type,
            })
    return instances


# ── RDS MySQL ────────────────────────────────────────────────


def create_rds_database(
    creds: Credentials, region: str, instance_id: str, db_name: str
) -> None:
    """通过 OpenAPI 在 RDS 实例上创建数据库（公共工具函数）。"""
    config = _make_config(creds, "rds.aliyuncs.com", region)
    client = RdsClient(config)
    req = rds_models.CreateDatabaseRequest(
        dbinstance_id=instance_id,
        dbname=db_name,
        character_set_name="utf8mb4",
        dbdescription="Created by yaochi-mcp",
    )
    client.create_database_with_options(req, _runtime())
    logger.info("RDS 数据库已创建: %s @ %s", db_name, instance_id)


def _create_rds_mysql(
    creds: Credentials,
    region: str,
    instance_name: str,
    vpc_id: str,
    vswitch_id: str,
    zone_id: str,
    database_name: str = "testdb",
) -> dict[str, Any]:
    """创建 RDS MySQL 基础版实例（开发默认规格）。

    立即返回实例信息。数据库将在 execute_instance_sql 首次执行时自动创建。
    """
    config = _make_config(creds, "rds.aliyuncs.com", region)
    client = RdsClient(config)

    request = rds_models.CreateDBInstanceRequest(
        region_id=region,
        zone_id=zone_id,
        engine="MySQL",
        engine_version="8.0",
        dbinstance_class="mysql.n2e.medium.1",
        dbinstance_storage=20,
        dbinstance_storage_type="cloud_essd",
        dbinstance_net_type="Intranet",
        category="Basic",
        vpcid=vpc_id,
        v_switch_id=vswitch_id,
        security_iplist="0.0.0.0/0",
        dbinstance_description=instance_name or "yaochi-mcp-rds-mysql",
        pay_type="Postpaid",
    )

    response = client.create_dbinstance_with_options(request, _runtime())
    body = response.body
    instance_id = body.dbinstance_id

    return {
        "engine": "rds-mysql",
        "instance_id": instance_id,
        "connection_string": body.connection_string or "",
        "port": body.port or "",
        "database_name": database_name,
        "region": region,
        "message": (
            f"RDS MySQL 实例创建成功: {instance_id}\n"
            f"规格: 基础版, 2C4G, 20GB ESSD\n"
            f"连接地址: {body.connection_string or '初始化中'}\n"
            f"默认数据库: {database_name}（将在首次 execute_instance_sql 时自动创建）\n"
            f"⚠️ 实例初始化约需 5-10 分钟，就绪后可执行 SQL。"
        ),
    }


def _list_rds(creds: Credentials, region: str) -> list[dict[str, Any]]:
    """列出 RDS 实例。"""
    config = _make_config(creds, "rds.aliyuncs.com", region)
    client = RdsClient(config)

    request = rds_models.DescribeDBInstancesRequest(
        region_id=region, page_size=50
    )
    response = client.describe_dbinstances_with_options(request, _runtime())

    instances = []
    items = response.body.items
    if items and items.dbinstance:
        for inst in items.dbinstance:
            instances.append({
                "engine": f"rds-{(inst.engine or 'unknown').lower()}",
                "instance_id": inst.dbinstance_id,
                "name": inst.dbinstance_description or "",
                "status": inst.dbinstance_status,
                "engine_version": inst.engine_version,
                "instance_class": inst.dbinstance_class,
                "region": inst.region_id,
                "zone": inst.zone_id,
                "network_type": inst.instance_network_type,
                "charge_type": inst.pay_type,
                "connection_string": inst.connection_string or "",
            })
    return instances


# ── PolarDB MySQL ──────────────────────────────────────


def create_polardb_database(
    creds: Credentials, region: str, cluster_id: str, db_name: str
) -> None:
    """通过 OpenAPI 在 PolarDB 集群上创建数据库（公共工具函数）。"""
    config = _make_config(creds, "polardb.aliyuncs.com", region)
    client = PolarDBClient(config)
    req = polardb_models.CreateDatabaseRequest(
        dbcluster_id=cluster_id,
        dbname=db_name,
        character_set_name="utf8mb4",
        dbdescription="Created by yaochi-mcp",
    )
    client.create_database_with_options(req, _runtime())
    logger.info("PolarDB 数据库已创建: %s @ %s", db_name, cluster_id)


def _create_polardb_mysql(
    creds: Credentials,
    region: str,
    instance_name: str,
    vpc_id: str,
    vswitch_id: str,
    zone_id: str,
    database_name: str = "testdb",
) -> dict[str, Any]:
    """创建 PolarDB MySQL 集群（开发默认规格）。

    立即返回集群信息。数据库将在 execute_instance_sql 首次执行时自动创建。
    """
    config = _make_config(creds, "polardb.aliyuncs.com", region)
    client = PolarDBClient(config)

    request = polardb_models.CreateDBClusterRequest(
        region_id=region,
        zone_id=zone_id,
        dbtype="MySQL",
        dbversion="8.0",
        dbnode_class="polar.mysql.g2.medium",
        pay_type="Postpaid",
        vpcid=vpc_id,
        v_switch_id=vswitch_id,
        cluster_network_type="VPC",
        dbcluster_description=instance_name or "yaochi-mcp-polardb-mysql",
        creation_option="Normal",
    )

    response = client.create_dbcluster_with_options(request, _runtime())
    body = response.body
    cluster_id = body.dbcluster_id

    return {
        "engine": "polardb-mysql",
        "instance_id": cluster_id,
        "database_name": database_name,
        "region": region,
        "message": (
            f"PolarDB MySQL 集群创建成功: {cluster_id}\n"
            f"规格: 2C8G (polar.mysql.g2.medium), MySQL 8.0\n"
            f"默认数据库: {database_name}（将在首次 execute_instance_sql 时自动创建）\n"
            f"⚠️ 集群初始化约需 5-10 分钟，就绪后可执行 SQL。"
        ),
    }


def _list_polardb(creds: Credentials, region: str) -> list[dict[str, Any]]:
    """列出 PolarDB MySQL 集群。"""
    config = _make_config(creds, "polardb.aliyuncs.com", region)
    client = PolarDBClient(config)

    request = polardb_models.DescribeDBClustersRequest(
        region_id=region, dbtype="MySQL", page_size=50
    )
    response = client.describe_dbclusters_with_options(request, _runtime())

    instances = []
    items = response.body.items
    if items and items.dbcluster:
        for inst in items.dbcluster:
            instances.append({
                "engine": "polardb-mysql",
                "instance_id": inst.dbcluster_id,
                "name": inst.dbcluster_description or "",
                "status": inst.dbcluster_status,
                "engine_version": inst.dbversion,
                "instance_class": inst.dbnode_class,
                "region": inst.region_id,
                "zone": inst.zone_id,
                "network_type": inst.dbcluster_network_type,
                "charge_type": inst.pay_type,
            })
    return instances


# ── Tair ────────────────────────────────────────────


def _create_tair(
    creds: Credentials,
    region: str,
    instance_name: str,
    vpc_id: str,
    vswitch_id: str,
    zone_id: str,
) -> dict[str, Any]:
    """创建 Tair 内存型实例（开发默认规格）。"""
    config = _make_config(creds, "r-kvstore.aliyuncs.com", region)
    client = TairClient(config)

    request = tair_models.CreateInstanceRequest(
        region_id=region,
        zone_id=zone_id,
        instance_class="redis.master.small.default",
        instance_type="Redis",
        engine_version="5.0",
        node_type="MASTER_SLAVE",
        charge_type="PostPaid",
        network_type="VPC",
        vpc_id=vpc_id,
        v_switch_id=vswitch_id,
        instance_name=instance_name or "yaochi-mcp-tair",
    )

    response = client.create_instance_with_options(request, _runtime())
    body = response.body
    return {
        "engine": "tair",
        "instance_id": body.instance_id,
        "connection_string": getattr(body, 'connection_domain', '') or "",
        "port": getattr(body, 'port', 6379),
        "region": region,
        "message": (
            f"Tair 实例创建成功: {body.instance_id}\n"
            f"规格: 社区版 Redis 7.0, 主从架构\n"
            f"实例正在初始化中，通常需要 1-3 分钟。\n"
            f"请通过 DMS 控制台设置密码并连接: https://dms.aliyun.com"
        ),
    }


def _list_tair(creds: Credentials, region: str) -> list[dict[str, Any]]:
    """列出 Tair / Redis 实例。"""
    config = _make_config(creds, "r-kvstore.aliyuncs.com", region)
    client = TairClient(config)

    request = tair_models.DescribeInstancesRequest(
        region_id=region, page_size=50
    )
    response = client.describe_instances_with_options(request, _runtime())

    instances = []
    items = response.body.instances
    if items and items.kvstore_instance:
        for inst in items.kvstore_instance:
            instances.append({
                "engine": "tair",
                "instance_id": inst.instance_id,
                "name": inst.instance_name or "",
                "status": inst.instance_status,
                "engine_version": inst.engine_version,
                "instance_class": inst.instance_class,
                "region": inst.region_id,
                "zone": inst.zone_id,
                "network_type": inst.network_type,
                "charge_type": inst.charge_type,
                "connection_string": inst.connection_domain or "",
            })
    return instances


# ── 公网地址 + 白名单自动配置 ──────────────────────────────────


def ensure_public_access(
    creds: Credentials,
    instance_id: str,
    engine: str,
    region: str,
) -> str:
    """确保实例有公网地址且白名单包含当前 IP。

    流程：
    1. 探测当前机器公网 IP
    2. 检查实例是否已有公网地址
    3. 无公网地址则自动开通
    4. 配置白名单仅允许当前 IP

    Returns:
        公网连接地址（host:port 格式），失败返回空字符串
    """
    engine_lower = engine.lower().strip()

    # 探测公网 IP
    my_ip = detect_public_ip()
    if not my_ip:
        logger.warning("无法探测公网 IP，跳过公网配置")
        return ""

    whitelist_ip = f"{my_ip}/32"

    try:
        if engine_lower == "rds-mysql":
            return _ensure_rds_public(creds, instance_id, region, whitelist_ip)
        elif engine_lower == "polardb-mysql":
            return _ensure_polardb_public(creds, instance_id, region, whitelist_ip)
        elif engine_lower == "tair":
            return _ensure_tair_public(creds, instance_id, region, whitelist_ip)
        elif engine_lower == "mongodb":
            return _ensure_mongodb_public(creds, instance_id, region, whitelist_ip)
        else:
            logger.warning("不支持的引擎类型: %s", engine)
            return ""
    except Exception as e:
        logger.error("配置公网访问失败 [%s/%s]: %s", engine_lower, instance_id, e, exc_info=True)
        return ""


def _ensure_rds_public(
    creds: Credentials, instance_id: str, region: str, whitelist_ip: str
) -> str:
    """RDS MySQL: 开通公网 + 配置白名单。"""
    config = _make_config(creds, "rds.aliyuncs.com", region)
    client = RdsClient(config)

    # 查询现有连接地址
    req = rds_models.DescribeDBInstanceNetInfoRequest(dbinstance_id=instance_id)
    resp = client.describe_dbinstance_net_info_with_options(req, _runtime())
    net_infos = (resp.body.dbinstance_net_infos.dbinstance_net_info
                 if resp.body.dbinstance_net_infos else [])

    public_host, port = "", "3306"
    for item in net_infos:
        if item.iptype == "Public":
            public_host = item.connection_string
            port = str(item.port)
            break

    # 无公网地址则开通
    if not public_host:
        prefix = f"{instance_id}-pub"
        try:
            alloc_req = rds_models.AllocateInstancePublicConnectionRequest(
                dbinstance_id=instance_id,
                connection_string_prefix=prefix,
                port="3306",
            )
            client.allocate_instance_public_connection_with_options(alloc_req, _runtime())
            public_host = f"{prefix}.mysql.rds.aliyuncs.com"
            logger.info("RDS 公网地址已开通: %s", public_host)
        except Exception as e:
            if "already exist" in str(e).lower() or "已存在" in str(e):
                public_host = f"{prefix}.mysql.rds.aliyuncs.com"
            else:
                raise

    # 配置白名单
    try:
        wl_req = rds_models.ModifySecurityIpsRequest(
            dbinstance_id=instance_id,
            security_ips=whitelist_ip,
            dbinstance_iparray_name="mcp_public_access",
            modify_mode="Cover",
        )
        client.modify_security_ips_with_options(wl_req, _runtime())
        logger.info("RDS 白名单已配置: %s (组: mcp_public_access)", whitelist_ip)
    except Exception as e:
        logger.warning("RDS 白名单配置失败: %s", e)

    return f"{public_host}:{port}" if public_host else ""


def _ensure_polardb_public(
    creds: Credentials, cluster_id: str, region: str, whitelist_ip: str
) -> str:
    """PolarDB MySQL: 开通公网 + 配置白名单。"""
    config = _make_config(creds, "polardb.aliyuncs.com", region)
    client = PolarDBClient(config)

    # 查询连接地址
    req = polardb_models.DescribeDBClusterEndpointsRequest(dbcluster_id=cluster_id)
    resp = client.describe_dbcluster_endpoints_with_options(req, _runtime())

    public_host, port = "", "3306"
    for ep in (resp.body.items or []):
        addr_list = ep.address_items
        if hasattr(addr_list, 'address'):
            addr_list = addr_list.address
        for addr in (addr_list or []):
            if getattr(addr, 'net_type', '') == 'Public':
                public_host = addr.connection_string or ""
                port = str(addr.port or 3306)
                break
        if public_host:
            break

    # 无公网地址则为主端点开通
    if not public_host:
        endpoint_id = ""
        for ep in (resp.body.items or []):
            if getattr(ep, 'endpoint_type', '') == 'Primary':
                endpoint_id = ep.dbendpoint_id or ""
                break
        if not endpoint_id and resp.body.items:
            endpoint_id = resp.body.items[0].dbendpoint_id or ""

        if endpoint_id:
            try:
                alloc_req = polardb_models.CreateDBEndpointAddressRequest(
                    dbcluster_id=cluster_id,
                    dbendpoint_id=endpoint_id,
                    net_type="Public",
                    connection_string_prefix=f"{cluster_id}-pub",
                )
                client.create_dbendpoint_address_with_options(alloc_req, _runtime())
                public_host = f"{cluster_id}-pub.mysql.polardb.rds.aliyuncs.com"
                logger.info("PolarDB 公网地址已开通: %s", public_host)
            except Exception as e:
                if "already exist" in str(e).lower() or "已存在" in str(e):
                    public_host = f"{cluster_id}-pub.mysql.polardb.rds.aliyuncs.com"
                else:
                    raise

    # 配置白名单
    try:
        wl_req = polardb_models.ModifyDBClusterAccessWhitelistRequest(
            dbcluster_id=cluster_id,
            security_ips=whitelist_ip,
            dbcluster_iparray_name="mcp_public_access",
        )
        client.modify_dbcluster_access_whitelist_with_options(wl_req, _runtime())
        logger.info("PolarDB 白名单已配置: %s", whitelist_ip)
    except Exception as e:
        logger.warning("PolarDB 白名单配置失败: %s", e)

    return f"{public_host}:{port}" if public_host else ""


def _ensure_tair_public(
    creds: Credentials, instance_id: str, region: str, whitelist_ip: str
) -> str:
    """Tair/Redis: 开通公网 + 配置白名单。"""
    config = _make_config(creds, "r-kvstore.aliyuncs.com", region)
    client = TairClient(config)

    # 查询现有连接地址
    req = tair_models.DescribeDBInstanceNetInfoRequest(instance_id=instance_id)
    resp = client.describe_dbinstance_net_info_with_options(req, _runtime())
    net_infos = resp.body.net_info_items.instance_net_info if resp.body.net_info_items else []

    public_host, port = "", "6379"
    for item in net_infos:
        if getattr(item, 'iptype', '') == '1':  # 1=Public
            public_host = item.connection_string or ""
            port = str(item.port or 6379)
            break

    # 无公网地址则开通
    if not public_host:
        prefix = f"{instance_id}-pub"
        try:
            alloc_req = tair_models.AllocateInstancePublicConnectionRequest(
                instance_id=instance_id,
                connection_string_prefix=prefix,
                port="6379",
            )
            client.allocate_instance_public_connection_with_options(alloc_req, _runtime())
            public_host = f"{prefix}.redis.rds.aliyuncs.com"
            logger.info("Tair 公网地址已开通: %s", public_host)
        except Exception as e:
            if "already exist" in str(e).lower() or "已存在" in str(e):
                public_host = f"{prefix}.redis.rds.aliyuncs.com"
            else:
                raise

    # 配置白名单
    try:
        wl_req = tair_models.ModifySecurityIpsRequest(
            instance_id=instance_id,
            security_ips=whitelist_ip,
            security_ip_group_name="mcp_public_access",
            modify_mode="Cover",
        )
        client.modify_security_ips_with_options(wl_req, _runtime())
        logger.info("Tair 白名单已配置: %s", whitelist_ip)
    except Exception as e:
        logger.warning("Tair 白名单配置失败: %s", e)

    return f"{public_host}:{port}" if public_host else ""


def _ensure_mongodb_public(
    creds: Credentials, instance_id: str, region: str, whitelist_ip: str
) -> str:
    """MongoDB: 开通公网 + 配置白名单。"""
    config = _make_config(creds, "mongodb.aliyuncs.com", region)
    client = DdsClient(config)

    # 检查是否已有公网地址
    req = dds_models.DescribeDBInstanceAttributeRequest(dbinstance_id=instance_id)
    resp = client.describe_dbinstance_attribute_with_options(req, _runtime())

    public_host, port = "", "3717"
    db_instance = resp.body.dbinstances.dbinstance[0] if resp.body.dbinstances and resp.body.dbinstances.dbinstance else None
    if db_instance and db_instance.replica_sets and db_instance.replica_sets.replica_set:
        for rs in db_instance.replica_sets.replica_set:
            if getattr(rs, 'network_type', '') == 'Public':
                public_host = rs.connection_domain or ""
                port = str(rs.connection_port or 3717)
                break

    # 无公网地址则开通
    if not public_host:
        try:
            alloc_req = dds_models.AllocatePublicNetworkAddressRequest(
                dbinstance_id=instance_id,
            )
            client.allocate_public_network_address_with_options(alloc_req, _runtime())
            logger.info("MongoDB 公网地址已开通")
            # 重新查询获取地址
            resp = client.describe_dbinstance_attribute_with_options(req, _runtime())
            db_instance = resp.body.dbinstances.dbinstance[0] if resp.body.dbinstances and resp.body.dbinstances.dbinstance else None
            if db_instance and db_instance.replica_sets and db_instance.replica_sets.replica_set:
                for rs in db_instance.replica_sets.replica_set:
                    if getattr(rs, 'network_type', '') == 'Public':
                        public_host = rs.connection_domain or ""
                        port = str(rs.connection_port or 3717)
                        break
        except Exception as e:
            if "already" in str(e).lower() or "已存在" in str(e):
                pass
            else:
                raise

    # 配置白名单
    try:
        wl_req = dds_models.ModifySecurityIpsRequest(
            dbinstance_id=instance_id,
            security_ips=whitelist_ip,
            security_ip_group_name="mcp_public_access",
            modify_mode="Cover",
        )
        client.modify_security_ips_with_options(wl_req, _runtime())
        logger.info("MongoDB 白名单已配置: %s", whitelist_ip)
    except Exception as e:
        logger.warning("MongoDB 白名单配置失败: %s", e)

    return f"{public_host}:{port}" if public_host else ""


# ── 统一入口 ─────────────────────────────────────────────────


def create_instance(
    creds: Credentials,
    engine: str,
    region: str | None = None,
    instance_name: str = "",
    vpc_id: str = "",
    vswitch_id: str = "",
    database_name: str = "testdb",
) -> dict[str, Any]:
    """创建数据库实例（统一入口）。

    Args:
        creds: 凭证
        engine: 数据库引擎 ("mongodb" | "rds-mysql" | "polardb-mysql" | "tair")
        region: 地域，默认 cn-hangzhou
        instance_name: 实例名称（可选）
        vpc_id: VPC ID（可选，为空时自动探测）
        vswitch_id: VSwitch ID（可选，为空时自动探测）
        database_name: 初始数据库名（RDS/PolarDB 有效，默认 testdb）

    Returns:
        创建结果字典
    """
    region = region or creds.region_id
    engine_lower = engine.lower().strip()

    if engine_lower not in SUPPORTED_ENGINES:
        supported = "\n".join(f"  - {k}: {v}" for k, v in SUPPORTED_ENGINES.items())
        raise ValueError(
            f"不支持的数据库引擎: {engine}\n支持的引擎:\n{supported}"
        )

    # VPC 自动探测
    zone_id = ""
    if not vpc_id or not vswitch_id:
        logger.info("VPC/VSwitch 未指定，自动探测中...")
        vpc_id, vswitch_id, zone_id = _detect_vpc(creds, region)

    if engine_lower == "mongodb":
        return _create_mongodb(
            creds, region, instance_name, vpc_id, vswitch_id, zone_id
        )
    elif engine_lower == "rds-mysql":
        return _create_rds_mysql(
            creds, region, instance_name, vpc_id, vswitch_id, zone_id,
            database_name=database_name,
        )
    elif engine_lower == "polardb-mysql":
        return _create_polardb_mysql(
            creds, region, instance_name, vpc_id, vswitch_id, zone_id,
            database_name=database_name,
        )
    elif engine_lower == "tair":
        return _create_tair(
            creds, region, instance_name, vpc_id, vswitch_id, zone_id
        )
    else:
        raise ValueError(f"不支持的引擎: {engine}")


def list_instances(
    creds: Credentials,
    engine: str = "",
    region: str | None = None,
) -> list[dict[str, Any]]:
    """列出数据库实例（统一入口）。

    Args:
        creds: 凭证
        engine: 筛选引擎（可选，不传则查所有支持的产品）
        region: 地域，默认 cn-hangzhou

    Returns:
        实例信息列表
    """
    region = region or creds.region_id
    engine_lower = engine.lower().strip() if engine else ""

    all_instances: list[dict[str, Any]] = []

    if not engine_lower or engine_lower == "mongodb":
        try:
            all_instances.extend(_list_mongodb(creds, region))
        except Exception as e:
            logger.warning("查询 MongoDB 实例失败: %s", e)

    if not engine_lower or engine_lower.startswith("rds"):
        try:
            all_instances.extend(_list_rds(creds, region))
        except Exception as e:
            logger.warning("查询 RDS 实例失败: %s", e)

    if not engine_lower or engine_lower == "polardb-mysql":
        try:
            all_instances.extend(_list_polardb(creds, region))
        except Exception as e:
            logger.warning("查询 PolarDB 实例失败: %s", e)

    if not engine_lower or engine_lower == "tair":
        try:
            all_instances.extend(_list_tair(creds, region))
        except Exception as e:
            logger.warning("查询 Tair 实例失败: %s", e)

    return all_instances
