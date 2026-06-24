# Alibaba Cloud Yaochi DB MCP Server

瑶池数据库 AI Native MCP Server — 一个 MCP Server 统一管理阿里云全系数据库。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://python.org)

[English README](README.md)

## 什么是瑶池数据库 MCP Server？

基于 [Model Context Protocol (MCP)](https://modelcontextprotocol.io) 构建的数据库工具服务，让 AI 编码助手（Cursor、Claude Desktop、Qoder 等）可以直接操作阿里云数据库。

**核心场景**：AI 写完代码后，自动创建数据库 → 建表 → 执行 SQL 验证 —— 全程无需离开 IDE。

## 支持的数据库引擎

| 引擎 | 操作 |
|------|------|
| **RDS MySQL** | 创建实例、执行 SQL、临时账号模式 |
| **PolarDB MySQL** | 创建集群、执行 SQL、临时账号模式 |
| **MongoDB** | 创建副本集、执行 MongoDB 命令 |
| **Tair (Redis)** | 创建实例、执行 Redis 命令 |

## 提供的工具

| 工具 | 说明 |
|------|------|
| `create_instance` | 创建数据库实例 |
| `list_instances` | 列出已有实例 |
| `execute_instance_sql` | 通过实例 ID 执行 SQL（临时账号，无需密码） |
| `execute_mysql` | 直连 MySQL/PolarDB 执行 SQL |
| `execute_mongo` | 直连 MongoDB 执行命令 |
| `execute_redis` | 直连 Tair/Redis 执行命令 |
| `search_database` | 搜索 DMS 中的数据库 |
| `execute_sql` | 通过 DMS 执行 SQL |
| `register_to_dms` | 注册实例到 DMS |
| `ask_yaochi_agent` | 瑶池 Agent 大模型问答 |

## 快速开始

### 安装

```bash
git clone https://github.com/aliyun/alibabacloud-yaochi-db-mcp-server.git
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
用户：帮我创建一个 RDS MySQL，然后建个 users 表

AI 自动完成：
1. create_instance(engine="rds-mysql")
   → 返回 instance_id="rm-bp1xxx"

2. execute_instance_sql(instance_id="rm-bp1xxx", database="testdb",
     sql="CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(50))", force=true)
   → 自动开通公网 + 白名单 + 建库 + 建表成功

3. execute_instance_sql(instance_id="rm-bp1xxx", database="testdb",
     sql="SELECT * FROM users")
   → 返回查询结果
```

## 许可证

[Apache License 2.0](LICENSE)

## 贡献

欢迎提交 Issue 和 Pull Request。

## 相关链接

- [MCP 协议官方文档](https://modelcontextprotocol.io)
- [阿里云 RAM 控制台](https://ram.console.aliyun.com/manage/ak)
- [DMS 数据管理控制台](https://dms.aliyun.com)
