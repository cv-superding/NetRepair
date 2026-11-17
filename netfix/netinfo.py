"""网卡详细信息采集：一次性枚举网卡的 IP / 掩码 / 网关 / DHCP / DNS / MAC。

设计原则：
- 沿用项目「PowerShell 结构化字段 + ConvertTo-Json」风格，不解析 ipconfig /all
  （本地化关键字会失效），见 proxydns.py 的注释；
- 只用标准库，不引入 psutil 等新依赖；
- 任何失败返回空列表 / 空串，由 UI 层决定是否提示。

公网 IP 通过 HTTP 公开服务获取，失败静默返回空串——它是锦上添花，
本地网卡信息不依赖它。

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>
Licensed under the GNU General Public License v3.0.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from urllib.request import Request, urlopen

from .sysutil import LOGGER, run_ps

#: 公网 IP 查询服务（按顺序尝试，第一个成功即用）。返回纯文本 IP 的服务。
_PUBLIC_IP_SERVICES = (
    "https://api.ipify.org",
    "https://ipinfo.io/ip",
    "https://www.icanhazip.com",
)


@dataclass
class AdapterInfo:
    """一块网卡的完整配置信息。"""

    index: int = 0
    name: str = ""
    description: str = ""
    mac: str = ""
    ipv4: list[str] = field(default_factory=list)
    mask: str = ""
    gateway: str = ""
    dhcp: list[str] = field(default_factory=list)
    dns: list[str] = field(default_factory=list)
    link_speed: str = ""
    status: str = ""


def _prefix_to_mask(prefix: int) -> str:
    """把 CIDR 前缀长度（如 24）转成点分十进制掩码（255.255.255.0）。"""
    if not isinstance(prefix, int) or prefix < 0 or prefix > 32:
        return ""
    bits = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0
    return ".".join(str((bits >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def _split(value) -> list[str]:
    """把 PowerShell `-join ','` 出来的字符串规整为非空列表。"""
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value).split(",") if x.strip()]


def list_adapters() -> list[AdapterInfo]:
    """采集所有网卡的详细信息；失败返回空列表。

    用 `Get-NetIPConfiguration -Detailed` 拿 IP/网关/DHCP/DNS/接口，
    再对每块网卡用 `Get-NetAdapter` 补 MAC / 链路速度 / 状态。
    """
    script = r"""$ErrorActionPreference='SilentlyContinue'
Get-NetIPConfiguration -Detailed | ForEach-Object {
  $idx = $_.InterfaceIndex
  $adapter = Get-NetAdapter -InterfaceIndex $idx -ErrorAction SilentlyContinue
  $ips = @($_.IPv4Address.IPAddress) | Where-Object {$_}
  $prefix = @($_.IPv4Address.PrefixLength) | Select-Object -First 1
  $dhcp = @($_.DHCPServer.ServerAddresses | Where-Object {$_}) -join ','
  $dns = @($_.DNSServer.ServerAddresses | Where-Object {$_}) -join ','
  [pscustomobject]@{
    Index = $idx
    Name = [string]$_.InterfaceAlias
    Desc = [string]$adapter.InterfaceDescription
    Mac = [string]$adapter.MacAddress
    Ips = ($ips -join ',')
    Prefix = [string]$prefix
    Gateway = [string]$_.IPv4DefaultGateway.NextHop
    Dhcp = $dhcp
    Dns = $dns
    Speed = [string]$adapter.LinkSpeed
    Status = [string]$adapter.Status
  }
} | ConvertTo-Json -Compress -Depth 4 | ForEach-Object {
  [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($_))
}"""
    # 说明：PowerShell 输出经 base64 编码为纯 ASCII，规避 run_ps 的
    # 编码回退顺序（oem 优先）把 UTF-8 中文网卡名解成乱码。
    res = run_ps(script, timeout=60)
    if not res.ok or not res.output:
        LOGGER.warn(f"采集网卡信息失败：{res.first_line() or '无输出'}")
        return []

    try:
        decoded = base64.b64decode(res.output.strip()).decode("utf-8")
        data = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        LOGGER.warn(f"解析网卡信息失败：{exc}")
        return []
    if isinstance(data, dict):
        data = [data]

    out: list[AdapterInfo] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("Index") or 0)
        except (TypeError, ValueError):
            idx = 0
        try:
            prefix = int(row.get("Prefix") or 0)
        except (TypeError, ValueError):
            prefix = 0
        out.append(AdapterInfo(
            index=idx,
            name=str(row.get("Name") or ""),
            description=str(row.get("Desc") or ""),
            mac=str(row.get("Mac") or ""),
            ipv4=_split(row.get("Ips")),
            mask=_prefix_to_mask(prefix),
            gateway=str(row.get("Gateway") or ""),
            dhcp=_split(row.get("Dhcp")),
            dns=_split(row.get("Dns")),
            link_speed=str(row.get("Speed") or ""),
            status=str(row.get("Status") or ""),
        ))
    return out


def fetch_public_ip(timeout: int = 5) -> str:
    """获取公网 IP；所有服务都失败时返回空串（静默，不打扰用户）。"""
    for url in _PUBLIC_IP_SERVICES:
        try:
            req = Request(url, headers={"User-Agent": "NetRepair-NetInfo"})
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310
                text = resp.read().decode("utf-8", "replace").strip()
            # 简单校验：结果应像 IP（只含数字/点/冒号）
            if text and all(ch.isdigit() or ch in ".:" for ch in text):
                return text
        except Exception:  # noqa: BLE001
            continue
    return ""
