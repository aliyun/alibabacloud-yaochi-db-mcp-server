"""
临时数据库账号服务 — 借鉴 RDS OpenAPI MCP Server 的 DBService 模式

流程：
1. 获取实例连接信息（优先 VPC 内网，其次公网）
2. 创建临时账号 (mcp_ + 随机串)，赋予 ReadWrite 权限
3. 执行用户 SQL
4. 自动删除临时账号

参考：https://github.com/aliyun/alibabacloud-rds-openapi-mcp-server
"""

from __future__ import annotations

import logging
import secrets
import socket
import string
from typing import Any

from alibabacloud_rds20140815.client import Client as RdsClient
from alibabacloud_rds20140815 import models as rds_models
from alibabacloud_polardb20170801.client import Client as PolarDBClient
from alibabacloud_polardb20170801 import models as polardb_models

from yaochi_db_mcp.auth import Credentials
from yaochi_db_mcp.api.common import make_config, runtime, generate_password

logger = logging.getLogger(__name__)


# ── 账号名生成 ────────────────────────────────────────────────


# generate_password 已移至 common.py，此处仅保留 _random_account_name


def _random_account_name() -> str:
    """生成临时账号名：mcp_ + 10 位随机小写字母数字。"""
    chars = string.ascii_lowercase + string.digits
    return "mcp_" + "".join(secrets.choice(chars) for _ in range(10))


# ── 连通性探测 ─────────────────────────────────────────────────


def test_connect(host: str, port: int, timeout: float = 2.0) -> bool:
    """TCP 连通性探测。

    Args:
        host: 目标主机
        port: 目标端口
        timeout: 超时秒数

    Returns:
        True 表示可达
    """
    try:
        with socket.create_connection((host, int(port)), timeout):
            return True
    except Exception:
        return False


# ── RDS MySQL 临时账号服务 ──────────────────────────────────────


class RDSDBService:
    """RDS MySQL 临时账号 + SQL 执行服务。

    使用 context manager 模式，自动管理临时账号生命周期：
        with RDSDBService(creds, region, instance_id, database) as svc:
            result = svc.execute_sql("SELECT 1")
    """

    def __init__(
        self,
        creds: Credentials,
        region: str,
        instance_id: str,
        database: str = "",
        privilege: str = "ReadWrite",
    ):
        self.creds = creds
        self.region = region
        self.instance_id = instance_id
        self.database = database
        self.privilege = privilege  # ReadOnly / ReadWrite

        self._client: RdsClient | None = None
        self._account_name = ""
        self._account_password = ""
        self._host = ""
        self._port = 3306

    def __enter__(self):
        config = make_config(self.creds, "rds.aliyuncs.com", self.region)
        self._client = RdsClient(config)

        # 1. 确保数据库存在（通过 OpenAPI，不需要 TCP 连通）
        if self.database:
            self._ensure_database_exists()
        # 2. 获取连接地址（需要 TCP 可达）
        self._resolve_connection()
        # 3. 创建临时账号
        self._create_temp_account()
        # 4. 授权数据库
        if self.database:
            self._grant_privilege()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._delete_account()
        self._client = None

    def _resolve_connection(self):
        """获取实例连接地址，优先 VPC 内网，其次公网。"""
        req = rds_models.DescribeDBInstanceNetInfoRequest(
            dbinstance_id=self.instance_id
        )
        resp = self._client.describe_dbinstance_net_info_with_options(
            req, runtime()
        )
        net_infos = resp.body.dbinstance_net_infos.dbinstance_net_info

        vpc_host, vpc_port = "", 3306
        public_host, public_port = "", 3306

        for item in net_infos:
            if item.iptype == "Private":
                vpc_host = item.connection_string
                vpc_port = int(item.port)
            elif "Public" in (item.iptype or ""):
                public_host = item.connection_string
                public_port = int(item.port)

        if vpc_host and test_connect(vpc_host, vpc_port):
            self._host, self._port = vpc_host, vpc_port
            logger.info("使用 VPC 内网连接: %s:%d", vpc_host, vpc_port)
        elif public_host and test_connect(public_host, public_port):
            self._host, self._port = public_host, public_port
            logger.info("使用公网连接: %s:%d", public_host, public_port)
        else:
            raise RuntimeError(
                f"无法连接 RDS 实例 {self.instance_id}，"
                f"VPC({vpc_host}:{vpc_port}) 和公网({public_host}:{public_port}) 均不可达。\n"
                f"请确认：1) 实例已就绪(Running) 2) 白名单已放开 3) MCP Server 与实例网络互通"
            )

    def _ensure_database_exists(self):
        """检查数据库是否存在，不存在则通过 OpenAPI 自动创建。"""
        try:
            req = rds_models.DescribeDatabasesRequest(
                dbinstance_id=self.instance_id,
                dbname=self.database,
            )
            resp = self._client.describe_databases_with_options(req, runtime())
            databases = resp.body.databases
            if databases and databases.database:
                logger.info("数据库已存在: %s", self.database)
                return
        except Exception:
            pass  # 查询失败则尝试创建

        # 数据库不存在，自动创建
        try:
            req = rds_models.CreateDatabaseRequest(
                dbinstance_id=self.instance_id,
                dbname=self.database,
                character_set_name="utf8mb4",
                dbdescription="Auto-created by yaochi-mcp",
            )
            self._client.create_database_with_options(req, runtime())
            logger.info("数据库自动创建成功: %s @ %s", self.database, self.instance_id)
        except Exception as e:
            # 如果已存在（并发情况），忽略错误
            if "already exists" in str(e).lower() or "Duplicate" in str(e):
                logger.info("数据库已存在（并发创建）: %s", self.database)
            else:
                logger.warning("自动创建数据库失败: %s", e)
                raise RuntimeError(
                    f"数据库 {self.database} 不存在且自动创建失败: {e}"
                )

    def _create_temp_account(self):
        """创建临时数据库账号。"""
        self._account_name = _random_account_name()
        self._account_password = generate_password(32)

        req = rds_models.CreateAccountRequest(
            dbinstance_id=self.instance_id,
            account_name=self._account_name,
            account_password=self._account_password,
            account_description="Created by yaochi-mcp for SQL execution",
        )
        self._client.create_account_with_options(req, runtime())
        logger.info("临时账号已创建: %s @ %s", self._account_name, self.instance_id)

    def _grant_privilege(self):
        """为临时账号授予数据库权限。"""
        req = rds_models.GrantAccountPrivilegeRequest(
            dbinstance_id=self.instance_id,
            account_name=self._account_name,
            dbname=self.database,
            account_privilege=self.privilege,
        )
        self._client.grant_account_privilege_with_options(req, runtime())
        logger.info(
            "已授权 %s 对 %s 的 %s 权限",
            self._account_name, self.database, self.privilege,
        )

    def _delete_account(self):
        """删除临时账号（容错处理）。"""
        if not self._account_name or not self._client:
            return
        try:
            req = rds_models.DeleteAccountRequest(
                dbinstance_id=self.instance_id,
                account_name=self._account_name,
            )
            self._client.delete_account_with_options(req, runtime())
            logger.info("临时账号已删除: %s", self._account_name)
        except Exception as e:
            logger.warning("删除临时账号失败（可手动清理）: %s", e)

    def execute_sql(self, sql: str) -> dict[str, Any]:
        """使用临时账号连接实例并执行 SQL。

        Args:
            sql: SQL 语句

        Returns:
            执行结果字典
        """
        import pymysql

        conn = pymysql.connect(
            host=self._host,
            port=self._port,
            user=self._account_name,
            password=self._account_password,
            database=self.database or None,
            connect_timeout=10,
            read_timeout=30,
            charset="utf8mb4",
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    return {
                        "columns": columns,
                        "rows": [list(row) for row in rows],
                        "row_count": len(rows),
                    }
                else:
                    conn.commit()
                    return {
                        "affected_rows": cursor.rowcount,
                        "message": "SQL 执行成功",
                    }
        finally:
            conn.close()

    @property
    def connection_info(self) -> dict[str, Any]:
        """当前连接信息（供调试/日志使用）。"""
        return {
            "host": self._host,
            "port": self._port,
            "user": self._account_name,
            "instance_id": self.instance_id,
        }


# ── PolarDB MySQL 临时账号服务 ─────────────────────────────────


class PolarDBDBService:
    """PolarDB MySQL 临时账号 + SQL 执行服务。

    使用 context manager 模式：
        with PolarDBDBService(creds, region, cluster_id, database) as svc:
            result = svc.execute_sql("SELECT 1")
    """

    def __init__(
        self,
        creds: Credentials,
        region: str,
        cluster_id: str,
        database: str = "",
        privilege: str = "ReadWrite",
    ):
        self.creds = creds
        self.region = region
        self.cluster_id = cluster_id
        self.database = database
        self.privilege = privilege

        self._client: PolarDBClient | None = None
        self._account_name = ""
        self._account_password = ""
        self._host = ""
        self._port = 3306

    def __enter__(self):
        config = make_config(self.creds, "polardb.aliyuncs.com", self.region)
        self._client = PolarDBClient(config)

        # 1. 确保数据库存在（通过 OpenAPI，不需要 TCP 连通）
        if self.database:
            self._ensure_database_exists()
        # 2. 获取连接地址（需要 TCP 可达）
        self._resolve_connection()
        # 3. 创建临时账号
        self._create_temp_account()
        if self.database:
            self._grant_privilege()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._delete_account()
        self._client = None

    def _resolve_connection(self):
        """获取 PolarDB 集群连接地址（优先可达的端点）。"""
        req = polardb_models.DescribeDBClusterEndpointsRequest(
            dbcluster_id=self.cluster_id
        )
        resp = self._client.describe_dbcluster_endpoints_with_options(
            req, runtime()
        )
        items = resp.body.items

        # 收集所有候选连接地址: [(host, port, net_type, endpoint_type)]
        candidates = []
        for ep in (items or []):
            if not ep.address_items:
                continue
            addr_list = ep.address_items
            if hasattr(addr_list, 'address'):
                addr_list = addr_list.address
            for addr in (addr_list or []):
                h = getattr(addr, 'connection_string', '') or ''
                p = int(addr.port) if getattr(addr, 'port', None) else 3306
                nt = getattr(addr, 'net_type', '') or ''
                et = getattr(ep, 'endpoint_type', '') or ''
                if h:
                    candidates.append((h, p, nt, et))

        # 排序优先级: Cluster+Private > Cluster+Public > 其他Private > 其他Public
        def _sort_key(item):
            h, p, nt, et = item
            ep_score = 0 if et == "Cluster" else 1
            net_score = 0 if nt == "Private" else 1
            return (ep_score, net_score)
        candidates.sort(key=_sort_key)

        # 逐个尝试 test_connect，选第一个可达的
        host, port = "", 3306
        for h, p, nt, et in candidates:
            if test_connect(h, p):
                host, port = h, p
                logger.info("PolarDB 选中可达端点: %s:%d (net=%s, type=%s)", h, p, nt, et)
                break

        if not host:
            raise RuntimeError(
                f"无法连接 PolarDB 集群 {self.cluster_id}。\n"
                f"请确认：1) 集群已就绪(Running) 2) 白名单已放开 3) 网络互通"
            )

        self._host, self._port = host, port
        logger.info("PolarDB 连接地址: %s:%d", host, port)

    def _ensure_database_exists(self):
        """检查数据库是否存在，不存在则通过 OpenAPI 自动创建。"""
        try:
            req = polardb_models.DescribeDatabasesRequest(
                dbcluster_id=self.cluster_id,
                dbname=self.database,
            )
            resp = self._client.describe_databases_with_options(req, runtime())
            databases = resp.body.databases
            if databases and databases.database:
                logger.info("PolarDB 数据库已存在: %s", self.database)
                return
        except Exception:
            pass

        # 数据库不存在，自动创建
        try:
            req = polardb_models.CreateDatabaseRequest(
                dbcluster_id=self.cluster_id,
                dbname=self.database,
                character_set_name="utf8mb4",
                dbdescription="Auto-created by yaochi-mcp",
            )
            self._client.create_database_with_options(req, runtime())
            logger.info("PolarDB 数据库自动创建成功: %s @ %s", self.database, self.cluster_id)
        except Exception as e:
            if "already exists" in str(e).lower() or "Duplicate" in str(e):
                logger.info("PolarDB 数据库已存在（并发创建）: %s", self.database)
            else:
                logger.warning("PolarDB 自动创建数据库失败: %s", e)
                raise RuntimeError(
                    f"PolarDB 数据库 {self.database} 不存在且自动创建失败: {e}"
                )

    def _create_temp_account(self):
        """创建临时账号。"""
        self._account_name = _random_account_name()
        self._account_password = generate_password(32)

        req = polardb_models.CreateAccountRequest(
            dbcluster_id=self.cluster_id,
            account_name=self._account_name,
            account_password=self._account_password,
            account_type="Normal",
            account_description="Created by yaochi-mcp for SQL execution",
        )
        self._client.create_account_with_options(req, runtime())
        logger.info("PolarDB 临时账号已创建: %s", self._account_name)

    def _grant_privilege(self):
        """为临时账号授权。"""
        req = polardb_models.GrantAccountPrivilegeRequest(
            dbcluster_id=self.cluster_id,
            account_name=self._account_name,
            dbname=self.database,
            account_privilege=self.privilege,
        )
        self._client.grant_account_privilege_with_options(req, runtime())

    def _delete_account(self):
        """删除临时账号。"""
        if not self._account_name or not self._client:
            return
        try:
            req = polardb_models.DeleteAccountRequest(
                dbcluster_id=self.cluster_id,
                account_name=self._account_name,
            )
            self._client.delete_account_with_options(req, runtime())
            logger.info("PolarDB 临时账号已删除: %s", self._account_name)
        except Exception as e:
            logger.warning("删除 PolarDB 临时账号失败: %s", e)

    def execute_sql(self, sql: str) -> dict[str, Any]:
        """使用临时账号执行 SQL。"""
        import pymysql

        conn = pymysql.connect(
            host=self._host,
            port=self._port,
            user=self._account_name,
            password=self._account_password,
            database=self.database or None,
            connect_timeout=10,
            read_timeout=30,
            charset="utf8mb4",
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    return {
                        "columns": columns,
                        "rows": [list(row) for row in rows],
                        "row_count": len(rows),
                    }
                else:
                    conn.commit()
                    return {
                        "affected_rows": cursor.rowcount,
                        "message": "SQL 执行成功",
                    }
        finally:
            conn.close()

    @property
    def connection_info(self) -> dict[str, Any]:
        return {
            "host": self._host,
            "port": self._port,
            "user": self._account_name,
            "cluster_id": self.cluster_id,
        }

