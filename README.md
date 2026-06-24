# Alibaba Cloud Yaochi DB MCP Server

Yaochi Database AI Native MCP Server — One MCP Server to manage all Alibaba Cloud databases.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://python.org)

[中文版 README](README_CN.md)

## What is Yaochi DB MCP Server?

A database tool service built on [Model Context Protocol (MCP)](https://modelcontextprotocol.io), enabling AI coding assistants (Cursor, Claude Desktop, Qoder, etc.) to directly operate Alibaba Cloud databases.

**Core Scenario**: After AI writes code, it automatically creates a database → creates tables → executes SQL to verify — all without leaving the IDE.

## Supported Database Engines

| Engine | Operations |
|--------|------------|
| **RDS MySQL** | Create instance, execute SQL, ephemeral account mode |
| **PolarDB MySQL** | Create cluster, execute SQL, ephemeral account mode |
| **MongoDB** | Create replica set, execute MongoDB commands |
| **Tair (Redis)** | Create instance, execute Redis commands |

## Available Tools

| Tool | Description |
|------|-------------|
| `create_instance` | Create a database instance |
| `list_instances` | List existing instances |
| `execute_instance_sql` | Execute SQL via instance ID (ephemeral account, no password needed) |
| `execute_mysql` | Direct connect to MySQL/PolarDB and execute SQL |
| `execute_mongo` | Direct connect to MongoDB and execute commands |
| `execute_redis` | Direct connect to Tair/Redis and execute commands |
| `search_database` | Search databases in DMS |
| `execute_sql` | Execute SQL via DMS |
| `register_to_dms` | Register instance to DMS |
| `ask_yaochi_agent` | Yaochi Agent LLM Q&A |

## Quick Start

### Installation

```bash
git clone https://github.com/aliyun/alibabacloud-yaochi-db-mcp-server.git
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
User: Create an RDS MySQL and build a users table

AI automatically:
1. create_instance(engine="rds-mysql")
   → Returns instance_id="rm-bp1xxx"

2. execute_instance_sql(instance_id="rm-bp1xxx", database="testdb",
     sql="CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(50))", force=true)
   → Auto-provisions public access + whitelist + creates DB + creates table

3. execute_instance_sql(instance_id="rm-bp1xxx", database="testdb",
     sql="SELECT * FROM users")
   → Returns query results
```

## License

[Apache License 2.0](LICENSE)

## Contributing

Issues and Pull Requests are welcome.

## Links

- [MCP Protocol Documentation](https://modelcontextprotocol.io)
- [Alibaba Cloud RAM Console](https://ram.console.aliyun.com/manage/ak)
- [DMS Console](https://dms.aliyun.com)
