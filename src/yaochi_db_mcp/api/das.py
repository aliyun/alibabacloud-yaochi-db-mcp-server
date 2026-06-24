"""
DAS（数据库自治服务）API 封装

提供瑶池 Agent 大模型能力接口，支持：
- 数据库知识问答
- 性能诊断
- 多轮对话（通过 session_id 保持上下文）
"""

from __future__ import annotations

import logging
from typing import Any

from alibabacloud_das20200116.client import Client as DasClient
from alibabacloud_das20200116 import models as das_models

from yaochi_db_mcp.auth import Credentials
from yaochi_db_mcp.api.common import make_config, runtime

logger = logging.getLogger(__name__)

# DAS 支持的产品来源
VALID_SOURCES = [
    "yaochi", "tair", "dbs", "polardb-ai",
    "polarx", "polarx-light", "lindorm", "mongodb", "polardb",
]


def ask_yaochi_agent(
    creds: Credentials,
    query: str,
    session_id: str = "",
    source: str = "yaochi",
    extra_info: str = "",
    region: str | None = None,
) -> dict[str, Any]:
    """调用瑶池 Agent 大模型能力接口（SSE 流式聚合）。

    Args:
        creds: 阿里云凭证
        query: 自然语言问题
        session_id: 会话 ID（UUID 格式），不传则创建新会话
        source: 云产品来源（yaochi/tair/polardb/mongodb 等）
        extra_info: 附加信息（JSON 字符串）
        region: 地域 ID

    Returns:
        Agent 回复结果字典
    """
    region = region or creds.region_id or "cn-hangzhou"
    config = make_config(creds, f"das.{region}.aliyuncs.com", region)
    client = DasClient(config)

    # 构建请求
    request = das_models.GetYaoChiAgentRequest(
        query=query,
        session_id=session_id or None,
        source=source if source in VALID_SOURCES else "yaochi",
        extra_info=extra_info or None,
    )

    # SSE 流式调用，聚合所有 chunk
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    final_session_id = ""
    product = ""
    function_calls: list[dict] = []
    sub_agents: list[dict] = []

    for resp in client.get_yao_chi_agent_with_sse(request, runtime()):
        body = resp.body
        if not body:
            continue

        # 聚合内容
        if body.content:
            content_parts.append(body.content)
        if body.reasoning_content:
            reasoning_parts.append(body.reasoning_content)
        if body.session_id:
            final_session_id = body.session_id
        if body.product:
            product = body.product

        # 收集已完成的工具调用
        if body.function_call:
            for fc in body.function_call:
                status = fc.status or ""
                if status == "success" and fc.name:
                    function_calls.append({
                        "name": fc.name,
                        "arguments": fc.arguments or "",
                        "id": fc.id or "",
                    })

        # 收集子 Agent 信息
        if body.sub_agent_call:
            for sa in body.sub_agent_call:
                if sa.sub_agent_name:
                    sub_agents.append({
                        "id": sa.sub_agent_id or "",
                        "name": sa.sub_agent_name,
                        "status": sa.status or "",
                    })

    # 组装最终结果
    result: dict[str, Any] = {
        "content": "".join(content_parts),
        "session_id": final_session_id,
    }
    if reasoning_parts:
        result["reasoning"] = "".join(reasoning_parts)
    if product:
        result["product"] = product
    if function_calls:
        result["function_calls"] = function_calls
    if sub_agents:
        # 去重
        seen = set()
        unique = []
        for sa in sub_agents:
            key = sa["id"] or sa["name"]
            if key not in seen:
                seen.add(key)
                unique.append(sa)
        result["sub_agents"] = unique

    logger.info("瑶池 Agent 回复: session=%s, content_len=%d",
                result["session_id"], len(result["content"]))
    return result
