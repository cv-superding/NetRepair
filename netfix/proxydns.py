"""代理环境与 DNS 出口诊断。

这一组检查针对一类很具体的故障：**代理客户端所有节点都超时，但本机其实有网**。

2026-10-22 实测过一次真实案例：校园网下发的 DNS 服务器整台挂掉，
而 Clash Verge 的「DNS 覆写」是关闭的（`enable_dns_settings: false`），
订阅里也没有 dns 段 —— 于是 mihomo 只能用系统 DNS 解析节点域名，
全部解析超时，界面上表现为「所有节点 Timeout」。
用户当时的判断是「校园网把代理封了」，实际与封锁无关。

同类故障还有两个：
- 双网卡（有线 + 手机 USB 共享）默认路由跃点数相同 → 出口在两条链路之间摇摆；
- 代理客户端用了 DoH，但引导 DNS 指向已失效的服务器 → 引导死循环。

本模块只做**探测与读取**，不修改任何东西；修改动作在 engine.py 里。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from .sysutil import run_cmd, run_ps

#: 国内可达、支持 ECS 的公共 DNS。用作修复目标，也用作探测基准。
PUBLIC_DNS = ("223.5.5.5", "119.29.29.29")

#: 用来判断「能不能解析」的探测域名。选国内大站，避免被墙因素干扰判断。
PROBE_DOMAIN = "www.baidu.com"

#: 已知的代理客户端配置目录（相对于 %APPDATA%）
CLIENT_DIRS = (
    "io.github.clash-verge-rev.clash-verge-rev",
    "clash-verge",
    "io.github.clash-verge-rev.clash-verge",
    "mihomo-party",
    "io.github.mihomo-party.app",
)


@dataclass
class DnsServer:
    """一台 DNS 服务器的探测结果。"""

    server: str
    ok: bool = False
    resolved: str = ""
    detail: str = ""
    responded: bool = False   # 服务器是否响应；与「能否解析域名」分开判定


@dataclass
class AdapterDns:
    """一块网卡上配置的 DNS。"""

    index: int
    name: str
    servers: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ 网卡 DNS

def list_adapter_dns() -> list[AdapterDns]:
    """列出所有配置了 DNS 的网卡（只取 IPv4）。

    用 PowerShell 而不是 `ipconfig`：后者要按中文/英文关键字切段，
    在非中文系统上会直接失效；`Get-DnsClientServerAddress` 返回结构化字段，稳。
    """
    script = (
        "Get-DnsClientServerAddress -AddressFamily IPv4 | "
        "Where-Object { $_.ServerAddresses } | ForEach-Object { "
        "'{0}|{1}|{2}' -f $_.InterfaceIndex, $_.InterfaceAlias, ($_.ServerAddresses -join ',') }"
    )
    res = run_ps(script, timeout=60)
    out: list[AdapterDns] = []
    for line in (res.output or "").splitlines():
        parts = line.strip().split("|")
        if len(parts) < 3:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            continue
        servers = [s.strip() for s in parts[2].split(",") if s.strip()]
        out.append(AdapterDns(index=idx, name=parts[1].strip(), servers=servers))
    return out


def probe_dns(server: str, domain: str = PROBE_DOMAIN, timeout: int = 8) -> DnsServer:
    """用 `nslookup` 指定服务器解析一个域名，判断这台 DNS 是否真的可用。

    为什么不自己发 UDP 包：nslookup 是系统自带、行为稳定，
    且能顺带暴露「服务器无响应」与「有响应但拒绝」的区别；
    这个工具本来就是薄封装系统命令的风格，保持一致。
    """
    result = DnsServer(server=server)
    res = run_cmd(["nslookup", domain, server], timeout=timeout)
    text = res.output or ""
    low = text.lower()

    # ⚠️ 必须先找应答、再判超时。
    # nslookup 常见的输出是「先打印一次 DNS request timed out，重试后才给出结果」，
    # 按关键字先判超时会把**可用**的服务器误报成无响应 —— 实测踩过。
    # 应答段形如：
    #   名称:    www.a.shifen.com
    #   Addresses:  39.156.70.239
    #               39.156.70.46          ← 续行没有 "Address:" 前缀
    # 只认「名称/Name」之后的内容，避免把服务器自身地址算进结果。
    ips: list[str] = []
    in_answer = False
    for line in text.splitlines():
        if re.match(r"\s*(?:名称|Name)\s*:", line):
            in_answer = True
            continue
        if not in_answer:
            continue
        m = re.match(r"\s*(?:Address|Addresses)\s*:\s*(.+)", line)
        if m:
            ips.extend(re.findall(r"[0-9a-fA-F:.]+", m.group(1)))
            continue
        m2 = re.match(r"^\s+([0-9a-fA-F:.]+)\s*$", line)
        if m2:
            ips.append(m2.group(1))
    ips = [x for x in ips if x != server]
    # 优先 IPv4：这个工具整体是 IPv4 语境，把 AAAA 报出来会让用户以为「解析到奇怪的地址」
    ip = next((x for x in ips if "." in x), ips[0] if ips else "")

    if ip:
        result.ok = True
        result.responded = True
        result.resolved = ip
        note = "（首次请求超时后重试成功）" if ("timed out" in low or "超时" in text) else ""
        result.detail = f"解析正常（{domain} → {ip}）{note}"
        return result

    if res.timeout or "timed out" in low or "超时" in text:
        result.detail = "无响应（超时）"
        return result
    if "can't find" in low or "找不到" in text or "no answer" in low:
        result.responded = True
        result.detail = "有响应，但查不到该域名"
        return result

    result.detail = "未取得解析结果（无法确认服务器是否响应）"
    return result


def probe_all(servers: list[str], timeout: int = 8) -> list[DnsServer]:
    """逐台探测；同一台只测一次。"""
    seen, out = set(), []
    for s in servers:
        if s in seen:
            continue
        seen.add(s)
        out.append(probe_dns(s, timeout=timeout))
    return out


# ------------------------------------------------------------------ 默认路由

@dataclass
class DefaultRoute:
    gateway: str
    interface: str
    metric: int


def default_routes() -> list[DefaultRoute]:
    """解析 `route print -4` 里的默认路由（0.0.0.0/0）。

    这里必须用 route print 而不是 `Get-NetRoute`：
    后者在部分 PowerShell 5.1 环境下返回的对象字段名不一致，解析更脆。
    """
    res = run_cmd(["route", "print", "-4"], timeout=30)
    routes: list[DefaultRoute] = []
    for line in (res.output or "").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        if parts[0] != "0.0.0.0" or parts[1] != "0.0.0.0":
            continue
        gateway, interface, metric = parts[2], parts[3], parts[4]
        if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", gateway):
            continue  # 「在链路上」这类非网关行
        try:
            routes.append(DefaultRoute(gateway, interface, int(metric)))
        except ValueError:
            continue
    return routes


def ambiguous_routes() -> list[DefaultRoute]:
    """返回「跃点数并列最低」的那组默认路由。

    并列意味着 Windows 可以走任意一条，长连接会在两条出口之间摇摆
    —— 典型表现是「时好时坏、开了代理断断续续」。
    """
    routes = default_routes()
    if len(routes) < 2:
        return []
    lowest = min(r.metric for r in routes)
    tied = [r for r in routes if r.metric == lowest]
    return tied if len(tied) > 1 else []


# ------------------------------------------------------------------ 代理客户端

@dataclass
class ProxyClient:
    name: str
    base: str
    dns_override: bool | None = None   # None = 没读到配置
    default_nameserver: list[str] = field(default_factory=list)
    nameserver: list[str] = field(default_factory=list)
    profile_has_dns: bool | None = None


def _appdata() -> str:
    return os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")


def _read_yaml_simple(path: str) -> dict:
    """极简 YAML 读取：只取本模块关心的标量与字符串列表。

    不引入 PyYAML —— 打包体积与依赖都不值得，而这里需要的字段结构是固定的。
    """
    data: dict = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError:
        return data

    current_key = None
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if indent == 0 and ":" in stripped:
            key, _, val = stripped.partition(":")
            current_key = key.strip()
            val = val.strip()
            data[current_key] = val if val else []
            continue

        if stripped.startswith("- ") and current_key:
            item = stripped[2:].strip().strip("'\"")
            if isinstance(data.get(current_key), list):
                data[current_key].append(item)
    return data


def find_proxy_clients() -> list[ProxyClient]:
    """扫描已知的代理客户端配置目录。"""
    base_root = _appdata()
    found: list[ProxyClient] = []
    for rel in CLIENT_DIRS:
        base = os.path.join(base_root, rel)
        if not os.path.isdir(base):
            continue
        client = ProxyClient(name=rel, base=base)

        verge = os.path.join(base, "verge.yaml")
        if os.path.isfile(verge):
            cfg = _read_yaml_simple(verge)
            raw = str(cfg.get("enable_dns_settings", "")).lower()
            if raw in ("true", "false"):
                client.dns_override = raw == "true"

        dns_cfg = os.path.join(base, "dns_config.yaml")
        if os.path.isfile(dns_cfg):
            cfg = _read_yaml_simple(dns_cfg)
            client.default_nameserver = [
                str(x) for x in (cfg.get("default-nameserver") or []) if str(x).strip()
            ]
            client.nameserver = [str(x) for x in (cfg.get("nameserver") or []) if str(x).strip()]

        client.profile_has_dns = _active_profile_has_dns(base)
        found.append(client)
    return found


def _active_profile_has_dns(base: str) -> bool | None:
    """活动订阅里有没有 dns 段。

    没有 dns 段 + 覆写关闭 = mihomo 完全依赖系统 DNS，这正是那次故障的组合。
    """
    profiles = os.path.join(base, "profiles")
    if not os.path.isdir(profiles):
        return None
    current = os.path.join(base, "profiles.yaml")
    target = ""
    if os.path.isfile(current):
        for line in open(current, "r", encoding="utf-8", errors="ignore"):
            if line.strip().startswith("current:"):
                target = line.split(":", 1)[1].strip().strip("'\"")
                break
    if not target:
        return None
    path = os.path.join(profiles, f"{target}.yaml")
    if not os.path.isfile(path):
        # 指针指向的文件不存在时**不能**退回去扫全部订阅：
        # 别的订阅通常都带 dns 段，扫一圈会得到「有 dns」的假结论（实测踩过）。
        return None
    candidates = [path]
    for path in candidates:
        try:
            text = open(path, "r", encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if re.search(r"^dns:\s*$", text, re.MULTILINE):
            return True
    return False if candidates else None


def diagnose_client(client: ProxyClient) -> list[str]:
    """给出一台客户端的配置问题清单（人话）。空列表 = 没发现问题。"""
    issues: list[str] = []
    if client.dns_override is False:
        issues.append("DNS 覆写未开启（enable_dns_settings: false），只能用系统 DNS")
    if client.profile_has_dns is False and client.dns_override is False:
        issues.append("活动订阅没有 dns 段，叠加覆写关闭 → 完全依赖系统 DNS")
    bad_bootstrap = [
        s for s in client.default_nameserver
        if s.lower() in ("system", "8.8.8.8", "8.8.4.4", "2001:4860:4860::8888")
    ]
    if bad_bootstrap:
        issues.append(f"引导 DNS 含不可达项：{', '.join(bad_bootstrap)}")
    if client.default_nameserver and all(
        s.startswith("http") for s in client.default_nameserver
    ):
        issues.append("引导 DNS 全是 DoH 域名，域名本身无法解析 → 引导死循环")
    return issues


def patch_client_config(client: ProxyClient) -> tuple[bool, list[str]]:
    """修复客户端配置：打开 DNS 覆写 + 引导 DNS 换成可达的纯 IP。

    只改两个字段，其余内容原样保留；改动前由调用方负责备份。
    """
    steps: list[str] = []
    ok = True

    verge = os.path.join(client.base, "verge.yaml")
    if os.path.isfile(verge):
        try:
            text = open(verge, "r", encoding="utf-8", errors="ignore").read()
            new = re.sub(
                r"(?m)^(\s*enable_dns_settings\s*:\s*)false\s*$",
                r"\1true",
                text,
            )
            if new != text:
                open(verge, "w", encoding="utf-8", newline="\n").write(new)
                steps.append("已开启 DNS 覆写（enable_dns_settings: true）")
            else:
                steps.append("DNS 覆写已是开启状态，无需修改")
        except OSError as exc:
            ok = False
            steps.append(f"写入 verge.yaml 失败：{exc}")

    dns_cfg = os.path.join(client.base, "dns_config.yaml")
    if os.path.isfile(dns_cfg):
        try:
            text = open(dns_cfg, "r", encoding="utf-8", errors="ignore").read()
            new = _replace_nameserver_block(text)
            if new != text:
                open(dns_cfg, "w", encoding="utf-8", newline="\n").write(new)
                steps.append("引导 DNS 已替换为 " + " / ".join(PUBLIC_DNS))
            else:
                steps.append("引导 DNS 已可用，无需修改")
        except OSError as exc:
            ok = False
            steps.append(f"写入 dns_config.yaml 失败：{exc}")
    return ok, steps


def _replace_nameserver_block(text: str) -> str:
    """把 default-nameserver / nameserver 换成可达值，其余行不动。

    用逐行替换而不是整体重写：用户可能在这份文件里放了自定义规则，
    整体重写会把它们冲掉。
    """
    lines = text.splitlines()
    out: list[str] = []
    section = ""
    public_lines = [f"  - {ip}" for ip in PUBLIC_DNS]

    for line in lines:
        stripped = line.strip()
        if re.match(r"^(default-nameserver|nameserver)\s*:\s*$", stripped):
            section = stripped.split(":")[0]
            out.append(line)
            out.extend(public_lines)
            continue
        if section and re.match(r"^\s*-\s+", line):
            # 跳过原来的列表项（已被 public_lines 取代）
            continue
        if stripped and not stripped.startswith("-"):
            section = ""
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


# ------------------------------------------------------------------ 汇总

def snapshot() -> dict:
    """一次性收集诊断所需的全部事实，供 UI 与日志使用。"""
    adapters = list_adapter_dns()
    servers = [s for ad in adapters for s in ad.servers]
    clients = find_proxy_clients()
    return {
        "adapters": [
            {"index": a.index, "name": a.name, "servers": a.servers} for a in adapters
        ],
        "dns": [
            {"server": d.server, "ok": d.ok, "resolved": d.resolved,
             "detail": d.detail, "responded": d.responded}
            for d in probe_all(servers)
        ],
        "routes": [
            {"gateway": r.gateway, "interface": r.interface, "metric": r.metric}
            for r in default_routes()
        ],
        "ambiguous": [
            {"gateway": r.gateway, "interface": r.interface, "metric": r.metric}
            for r in ambiguous_routes()
        ],
        "clients": [
            {
                "name": c.name,
                "base": c.base,
                "dns_override": c.dns_override,
                "default_nameserver": c.default_nameserver,
                "profile_has_dns": c.profile_has_dns,
                "issues": diagnose_client(c),
            }
            for c in clients
        ],
    }


if __name__ == "__main__":  # 手动排查用
    print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
