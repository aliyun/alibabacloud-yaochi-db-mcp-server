# Alibaba Cloud Yaochi DB MCP Server

Yaochi Database AI Native MCP Server — One MCP Server to manage all Alibaba Cloud databases.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://python.org)

[中文版 README](README_CN.md)

## What is Yaochi DB MCP Server?

A database tool service built on [Model Context Protocol (MCP)](https://modelcontextprotocol.io), enabling AI coding assistants (Cursor, Claude Desktop, Qoder, etc.) to directly operate Alibaba Cloud databases.

**Core Scenario**: After AI writes code, it automatically creates a database → creates tables → executes SQL to verify → calls Yaochi Agent for performance diagnosis — all without leaving the IDE.

## Supported Database Engines

| Engine | Operations |
|--------|------------|
| **RDS MySQL** | Create instance, execute SQL, ephemeral account mode |
| **PolarDB MySQL** | Create cluster, execute SQL, ephemeral account mode |
| **MongoDB** | Create replica set, execute MongoDB commands |
| **Tair (Redis)** | Create instance, execute Redis commands |

## Yaochi Agent

Built-in AI database advisor powered by Alibaba Cloud’s official documentation and expert knowledge:

- **Knowledge Q&A** — Instantly answers database usage questions, reducing support tickets
- **Intelligent Diagnosis** — Auto-executes performance diagnostics via OpenAPI, pinpointing issues
- **Best Practices** — Provides architecture recommendations and optimization suggestions tailored to your workload

Supports multi-turn conversations and covers all Alibaba Cloud database engines (RDS, PolarDB, MongoDB, Tair, Lindorm, etc.).

## Available Tools

| Tool | Description |
|------|-------------|
| `ask_yaochi_agent` | Yaochi Agent — AI database advisor (diagnosis, best practices, architecture) |
| `create_instance` | Create a database instance |
| `list_instances` | List existing instances |
| `execute_instance_sql` | Execute SQL via instance ID (ephemeral account, no password needed) |
| `execute_mysql` | Direct connect to MySQL/PolarDB and execute SQL |
| `execute_mongo` | Direct connect to MongoDB and execute commands |
| `execute_redis` | Direct connect to Tair/Redis and execute commands |
| `search_database` | Search databases in DMS |
| `execute_sql` | Execute SQL via DMS |
| `register_to_dms` | Register instance to DMS |

## Quick Start

### Installation

```bash
git clone http://gitlab.alibaba-inc.com/cloudmon/alibabacloud-yaochi-db-mcp-server.git
cd alibabacloud-yaochi-db-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

### Verify

```bash
yaochi-db-mcp-server
```

It enters stdio waiting mode (no output) on success. Press `Ctrl+C` to exit.

### Configure AI Client

Add to your AI client's MCP configuration:

```json
{
  "mcpServers": {
    "yaochi-db": {
      "command": "<project-path>/alibabacloud-yaochi-db-mcp-server/.venv/bin/yaochi-db-mcp-server",
      "env": {
        "ALIBABA_CLOUD_ACCESS_KEY_ID": "your-ak",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "your-sk",
        "ALIBABA_CLOUD_REGION_ID": "cn-hangzhou",
        "YAOCHI_ENABLE_WRITE_SQL": "true",
        "YAOCHI_ENABLE_DDL_SQL": "true"
      }
    }
  }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ALIBABA_CLOUD_ACCESS_KEY_ID` | — | Alibaba Cloud AccessKey ID (required) |
| `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | — | Alibaba Cloud AccessKey Secret (required) |
| `ALIBABA_CLOUD_REGION_ID` | `cn-hangzhou` | Default region |
| `YAOCHI_ENABLE_WRITE_SQL` | `true` | Allow INSERT/UPDATE/DELETE |
| `YAOCHI_ENABLE_DDL_SQL` | `false` | Allow CREATE/ALTER DDL |
| `YAOCHI_PUBLIC_IP` | Auto-detect | Manually specify public IP |

## Security Features

- **Ephemeral Accounts**: Automatically creates/destroys temporary database accounts per SQL execution — no persistent credentials
- **SQL Safety Checks**: Blocks DROP/TRUNCATE and other dangerous operations; disallows comments and multi-statements
- **Restrictive Whitelist**: Auto-provisions public access with current IP only (/32), without affecting existing rules
- **Write Control**: Fine-grained DML/DDL permissions via environment variables

## Usage Example

```
User: Create a PolarDB MySQL cluster, build an orders table, and set up a Tair cache

AI automatically:
1. create_instance(engine="polardb-mysql")
   → Returns instance_id="pc-bp1xxx"

2. execute_instance_sql(instance_id="pc-bp1xxx", engine="polardb-mysql", database="testdb",
     sql="CREATE TABLE orders (id BIGINT PRIMARY KEY, amount DECIMAL(10,2))", force=true)
   → Auto-provisions public access + whitelist + creates DB + creates table

3. create_instance(engine="tair")
   → Returns instance_id="r-bp1xxx"

4. execute_redis(host="r-bp1xxx.redis.rds.aliyuncs.com", port=6379, password="xxx",
     command="SET order:1001 '{\"amount\":99.9}'")
   → OK

5. ask_yaochi_agent(query="PolarDB cluster pc-bp1xxx performance diagnosis")
   → Returns optimization suggestions from Yaochi Agent
```

## License

[Apache License 2.0](LICENSE)

## Contributing

Issues and Pull Requests are welcome.

## Links

- [MCP Protocol Documentation](https://modelcontextprotocol.io)
- [Alibaba Cloud RAM Console](https://ram.console.aliyun.com/manage/ak)
- [DMS Console](https://dms.aliyun.com)
