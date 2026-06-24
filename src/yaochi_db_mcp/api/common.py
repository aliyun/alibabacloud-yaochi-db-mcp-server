"""
API 层公共工具函数

提取公共函数避免循环依赖。
"""

from __future__ import annotations

import logging
import os
import secrets
import string
import subprocess
from urllib.request import urlopen, Request
from urllib.error import URLError

from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

from yaochi_db_mcp.auth import Credentials

logger = logging.getLogger(__name__)


def make_config(
    creds: Credentials, endpoint: str, region: str | None = None
) -> open_api_models.Config:
    """构建 OpenAPI 客户端配置。"""
    region_id = region or creds.region_id
    return open_api_models.Config(
        access_key_id=creds.access_key_id,
        access_key_secret=creds.access_key_secret,
        security_token=creds.security_token,
        region_id=region_id,
        endpoint=endpoint,
        user_agent=creds.user_agent,
    )


def runtime() -> util_models.RuntimeOptions:
    """标准运行时配置。"""
    return util_models.RuntimeOptions(read_timeout=30000, connect_timeout=10000)


# ── 密码生成（CSPRNG 级别）──────────────────────────


def generate_password(length: int = 32) -> str:
    """生成符合阿里云密码策略的随机密码。

    规则：8-32 位，至少包含大写字母、小写字母、数字、特殊字符中的 3 种。
    本实现保证包含全部 4 种字符类型。
    """
    length = max(8, min(32, length))

    U = string.ascii_uppercase
    L = string.ascii_lowercase
    D = string.digits
    S = "_!@#$%^&*()"
    pool = U + L + D + S

    chars = [
        secrets.choice(U),
        secrets.choice(L),
        secrets.choice(D),
        secrets.choice(S),
    ]
    chars.extend(secrets.choice(pool) for _ in range(length - len(chars)))

    secure_random = secrets.SystemRandom()
    secure_random.shuffle(chars)
    return "".join(chars)


# ── 公网 IP 探测 ──────────────────────────────────────

_IP_DETECT_URLS = [
    "https://ifconfig.me/ip",
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
]


def detect_public_ip() -> str:
    """探测当前机器的公网 IP 地址。

    优先级：
    1. 环境变量 YAOCHI_PUBLIC_IP（手动指定，适用于 NAT 等场景）
    2. curl 命令行（系统级工具，不受 App Sandbox 限制）
    3. urllib 直接请求（备用）

    如果全部失败，返回空字符串。
    """
    # 1. 环境变量优先
    env_ip = os.environ.get("YAOCHI_PUBLIC_IP", "").strip()
    if env_ip and "." in env_ip:
        logger.info("使用环境变量指定的公网 IP: %s", env_ip)
        return env_ip

    # 2. 通过 curl 探测（macOS 系统工具，不受沙箱限制）
    for url in _IP_DETECT_URLS:
        try:
            result = subprocess.run(
                ["curl", "-s", "--connect-timeout", "5", "-m", "5", url],
                capture_output=True, text=True, timeout=8,
            )
            if result.returncode == 0:
                ip = result.stdout.strip()
                if ip and "." in ip and len(ip) <= 15:
                    logger.info("探测到公网 IP: %s (via curl %s)", ip, url)
                    return ip
        except Exception as e:
            logger.debug("curl 探测失败 %s: %s", url, e)
            continue

    # 3. urllib 备用
    for url in _IP_DETECT_URLS:
        try:
            req = Request(url, headers={"User-Agent": "curl/7.88.0"})
            with urlopen(req, timeout=5) as resp:
                ip = resp.read().decode().strip()
                if ip and "." in ip and len(ip) <= 15:
                    logger.info("探测到公网 IP: %s (via urllib %s)", ip, url)
                    return ip
        except Exception as e:
            logger.debug("urllib 探测失败 %s: %s", url, e)
            continue

    logger.warning("无法探测公网 IP，所有方式均失败")
    return ""
