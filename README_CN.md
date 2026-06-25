# Alibaba Cloud Yaochi DB MCP Server

瑶池数据库 AI Native MCP Server — 一个 MCP Server 统一管理阿里云全系数据库。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://python.org)

[English README](README.md)

## 什么是瑶池数据库 MCP Server？

基于 [Model Context Protocol (MCP)](https://modelcontextprotocol.io) 构建的数据库工具服务，让 AI 编码助手（Cursor、Claude Desktop、Qoder 等）可以直接操作阿里云数据库。

**核心场景**：AI 写完代码后，自动创建数据库 → 建表 → 执行 SQL 验证 → 调用瑶池数据库 Agent 执行性能诊断 —— 全程无需离开 IDE。

## 支持的数据库引擎

| 引擎 | 操作 |
|------|------|
| **RDS MySQL** | 创建实例、执行 SQL、临时账号模式 |
| **PolarDB MySQL** | 创建集群、执行 SQL、临时账号模式 |
| **MongoDB** | 创建副本集、执行 MongoDB 命令 |
| **Tair (Redis)** | 创建实例、执行 Redis 命令 |

## 瑶池数据库 Agent

内置 AI 数据库智能顾问，融合官方文档知识库与专家经验：

- **知识问答** — 即时解答数据库使用问题，减少咨询工单
- **智能诊断** — 通过 OpenAPI 自动执行性能诊断任务，精准定位问题
- **最佳实践** — 提供架构选型建议和业务场景优化方案

支持多轮对话，覆盖阿里云全系数据库引擎（RDS、PolarDB、MongoDB、Tair、Lindorm 等）。

## 提供的工具

| 工具 | 说明 |
|------|------|
| `ask_yaochi_agent` | 瑶池数据库 Agent — AI 数据库智能顾问（诊断、最佳实践、架构建议） |
| `create_instance` | 创建数据库实例 |
| `list_instances` | 列出已有实例 |
| `execute_instance_sql` | 通过实例 ID 执行 SQL（临时账号，无需密码） |
| `execute_mysql` | 直连 MySQL/PolarDB 执行 SQL |
| `execute_mongo` | 直连 MongoDB 执行命令 |
| `execute_redis` | 直连 Tair/Redis 执行命令 |
| `search_database` | 搜索 DMS 中的数据库 |
| `execute_sql` | 通过 DMS 执行 SQL |
| `register_to_dms` | 注册实例到 DMS |

## 快速开始

### 安装

```bash
git clone http://gitlab.alibaba-inc.com/cloudmon/alibabacloud-yaochi-db-mcp-server.git
cd alibabacloud-yaochi-db-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

### 验证

```bash
yaochi-db-mcp-server
```

启动后进入 stdio 等待模式（无输出），说明安装成功。`Ctrl+C` 退出。

### 配置 AI 客户端

在你的 AI 客户端 MCP 配置中添加：

```json
{
  "mcpServers": {
    "yaochi-db": {
      "command": "<项目路径>/alibabacloud-yaochi-db-mcp-server/.venv/bin/yaochi-db-mcp-server",
      "env": {
        "ALIBABA_CLOUD_ACCESS_KEY_ID": "你的AK",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "你的SK",
        "ALIBABA_CLOUD_REGION_ID": "cn-hangzhou",
        "YAOCHI_ENABLE_WRITE_SQL": "true",
        "YAOCHI_ENABLE_DDL_SQL": "true"
      }
    }
  }
}
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ALIBABA_CLOUD_ACCESS_KEY_ID` | — | 阿里云 AccessKey ID（必填） |
| `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | — | 阿里云 AccessKey Secret（必填） |
| `ALIBABA_CLOUD_REGION_ID` | `cn-hangzhou` | 默认地域 |
| `YAOCHI_ENABLE_WRITE_SQL` | `true` | 允许 INSERT/UPDATE/DELETE |
| `YAOCHI_ENABLE_DDL_SQL` | `false` | 允许 CREATE/ALTER 等 DDL |
| `YAOCHI_PUBLIC_IP` | 自动探测 | 手动指定公网 IP |

## 安全特性

- **临时账号**：每次 SQL 执行自动创建/销毁临时数据库账号，无持久凭据残留
- **SQL 安全检查**：拦截 DROP/TRUNCATE 等危险操作，禁止注释和多语句
- **限制性白名单**：自动开通公网时仅允许当前 IP（/32），不影响已有规则
- **写操作开关**：通过环境变量精确控制 DML/DDL 权限

## 使用示例

```
用户：帮我开一个 PolarDB MySQL 集群，建个 orders 表，再开一个 Tair 做缓存

AI 自动完成：
1. create_instance(engine="polardb-mysql")
   → 返回 instance_id="pc-bp1xxx"

2. execute_instance_sql(instance_id="pc-bp1xxx", engine="polardb-mysql", database="testdb",
     sql="CREATE TABLE orders (id BIGINT PRIMARY KEY, amount DECIMAL(10,2))", force=true)
   → 自动开通公网 + 白名单 + 建库 + 建表成功

3. create_instance(engine="tair")
   → 返回 instance_id="r-bp1xxx"

4. execute_redis(host="r-bp1xxx.redis.rds.aliyuncs.com", port=6379, password="xxx",
     command="SET order:1001 '{\"amount\":99.9}'")
   → OK

5. ask_yaochi_agent(query="PolarDB 集群 pc-bp1xxx 性能诊断")
   → 瑶池数据库 Agent 返回优化建议
```

## 许可证

[Apache License 2.0](LICENSE)

## 贡献

欢迎提交 Issue 和 Pull Request。

## 相关链接

- [MCP 协议官方文档](https://modelcontextprotocol.io)
- [阿里云 RAM 控制台](https://ram.console.aliyun.com/manage/ak)
- [DMS 数据管理控制台](https://dms.aliyun.com)
