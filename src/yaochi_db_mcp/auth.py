"""
凭证管理模块

支持三种凭证来源（按优先级）：
1. 环境变量 ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET
2. aliyun CLI 配置文件 ~/.aliyun/config.json
3. ECS 实例 RAM 角色（环境变量 ALIBABA_CLOUD_ECS_METADATA）
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_DEFAULT_REGION = "cn-hangzhou"


@dataclass
class Credentials:
    """阿里云凭证"""

    access_key_id: str
    access_key_secret: str
    region_id: str = _DEFAULT_REGION
    security_token: str | None = None
    # SDK 请求统一携带的 User-Agent
    user_agent: str = field(default="AlibabaCloud-YaochiDB-MCP/0.1.0", init=False)


def load_credentials() -> Credentials:
    """加载阿里云凭证。

    优先级：
    1. 环境变量 (ALIBABA_CLOUD_ACCESS_KEY_ID, ...)
    2. aliyun CLI 配置文件 (~/.aliyun/config.json)

    Raises:
        ValueError: 未找到有效凭证
    """
    creds = _try_env_vars()
    if creds:
        logger.info("凭证来源: 环境变量")
        return creds

    creds = _try_cli_config()
    if creds:
        logger.info("凭证来源: aliyun CLI 配置文件")
        return creds

    raise ValueError(
        "未找到阿里云凭证。请通过以下任一方式配置：\n"
        "  方式 1: 设置环境变量\n"
        "    export ALIBABA_CLOUD_ACCESS_KEY_ID=your-ak\n"
        "    export ALIBABA_CLOUD_ACCESS_KEY_SECRET=your-sk\n"
        "    export ALIBABA_CLOUD_REGION_ID=cn-hangzhou  # 可选\n"
        "  方式 2: 运行 aliyun configure 配置 CLI\n"
        "  获取 AK/SK: https://ram.console.aliyun.com/manage/ak"
    )


def _try_env_vars() -> Credentials | None:
    """尝试从环境变量加载凭证。"""
    ak = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
    sk = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")

    if not ak or not sk:
        return None

    return Credentials(
        access_key_id=ak,
        access_key_secret=sk,
        region_id=os.environ.get("ALIBABA_CLOUD_REGION_ID", _DEFAULT_REGION),
        security_token=os.environ.get("ALIBABA_CLOUD_SECURITY_TOKEN"),
    )


def _try_cli_config() -> Credentials | None:
    """尝试从 aliyun CLI 配置文件加载凭证。

    支持读取 ~/.aliyun/config.json 中指定 profile 的凭证。
    profile 选择优先级：
    1. 环境变量 ALIBABA_CLOUD_PROFILE
    2. config.json 中的 current 字段
    3. 默认 "default"
    """
    config_path = os.path.expanduser("~/.aliyun/config.json")
    if not os.path.exists(config_path):
        return None

    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 aliyun CLI 配置文件失败: %s", e)
        return None

    profile_name = os.environ.get(
        "ALIBABA_CLOUD_PROFILE",
        config.get("current", "default"),
    )

    for profile in config.get("profiles", []):
        if profile.get("name") != profile_name:
            continue

        ak = profile.get("access_key_id", "")
        sk = profile.get("access_key_secret", "")
        if not ak or not sk:
            logger.warning("profile '%s' 中缺少 AK/SK", profile_name)
            return None

        return Credentials(
            access_key_id=ak,
            access_key_secret=sk,
            region_id=profile.get("region_id", _DEFAULT_REGION),
            security_token=profile.get("sts_token"),
        )

    logger.warning("未找到 profile '%s'", profile_name)
    return None
