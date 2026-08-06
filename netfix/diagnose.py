"""网络诊断模块。

借鉴 Open365 的「双路探测」思路：
  · 直连探测（原始 socket，绕过系统代理）
  · 代理路径探测（走 WinINet / 系统代理的 HTTP 请求）
两条路径对比即可区分「真断网」「代理被劫持」「DNS 故障」「LSP 损坏」。

诊断结果会给出建议修复项（suggest），主界面据此自动勾选，做到「按病因最小修复」。

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import json
import os
import socket
import winreg
from dataclasses import dataclass, field

from .sysutil import LOGGER, hosts_path, run_cmd, run_ps

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"

LEVEL_TEXT = {LEVEL_OK: "正常", LEVEL_WARN: "注意", LEVEL_ERROR: "异常"}


@dataclass
class CheckResult:
    key: str
    name: str
    level: str
    detail: str
    suggest: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ 探测原语

def tcp_probe(host: str, port: int, timeout: float = 3.0) -> bool:
    """原始 TCP 连接探测，完全绕过系统代理。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def dns_resolve(name: str, timeout: float = 4.0) -> str | None:
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        return socket.gethostbyname(name)
    except OSError:
        return None
    finally:
        socket.setdefaulttimeout(old)


# ------------------------------------------------------------------ 各检查项

def check_adapter() -> CheckResult:
    res = run_ps(
        "Get-NetAdapter -Physical | Select-Object Name,LinkSpeed,"
        "@{n='Status';e={$_.Status.ToString()}} | ConvertTo-Json -Compress",
        timeout=60)
    if not res.ok or not res.output:
        return CheckResult("adapter", "网络适配器", LEVEL_WARN,
                           "无法读取网卡信息（可能缺少 PowerShell 网络模块）", ["services"])
    try:
        data = json.loads(res.output)
    except json.JSONDecodeError:
        return CheckResult("adapter", "网络适配器", LEVEL_WARN, "网卡信息解析失败", [])
    if isinstance(data, dict):
        data = [data]
    up = [d for d in data if str(d.get("Status", "")).lower() == "up"]
    if up:
        names = "、".join(f"{d.get('Name')}（{d.get('LinkSpeed')}）" for d in up)
        return CheckResult("adapter", "网络适配器", LEVEL_OK, f"已连接：{names}")
    return CheckResult("adapter", "网络适配器", LEVEL_ERROR,
                       f"共 {len(data)} 块物理网卡，均未连接。请检查网线或无线开关",
                       ["adapter", "services"])


def check_ip() -> CheckResult:
    res = run_ps(
        "Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127.*'} | "
        "Select-Object IPAddress,PrefixOrigin,InterfaceAlias | ConvertTo-Json -Compress", timeout=60)
    try:
        data = json.loads(res.output) if res.output else []
    except json.JSONDecodeError:
        data = []
    if isinstance(data, dict):
        data = [data]
    if not data:
        return CheckResult("ip", "IP 地址配置", LEVEL_ERROR,
                           "未获取到有效 IPv4 地址", ["gateway", "services", "tcpip"])
    apipa = [d for d in data if str(d.get("IPAddress", "")).startswith("169.254.")]
    valid = [d for d in data if not str(d.get("IPAddress", "")).startswith("169.254.")]
    if not valid and apipa:
        return CheckResult("ip", "IP 地址配置", LEVEL_ERROR,
                           f"仅获取到自动专用地址 {apipa[0].get('IPAddress')}，DHCP 分配失败",
                           ["gateway", "services", "adapter"])
    show = "、".join(f"{d.get('IPAddress')}（{d.get('InterfaceAlias')}）" for d in valid[:3])
    return CheckResult("ip", "IP 地址配置", LEVEL_OK, f"已获取：{show}")


def check_gateway() -> CheckResult:
    res = run_ps(
        "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | "
        "Sort-Object RouteMetric | Select-Object -First 1).NextHop", timeout=45)
    gw = (res.output or "").strip().splitlines()[0].strip() if res.output.strip() else ""
    if not gw or gw == "0.0.0.0":
        return CheckResult("gateway", "默认网关", LEVEL_ERROR,
                           "未检测到默认网关，无法访问外网", ["gateway", "route", "tcpip"])
    ping = run_cmd(["ping", "-n", "2", "-w", "1200", gw], timeout=25)
    if "TTL=" in ping.output or "ttl=" in ping.output:
        return CheckResult("gateway", "默认网关", LEVEL_OK, f"网关 {gw} 可正常通信")
    return CheckResult("gateway", "默认网关", LEVEL_ERROR,
                       f"网关 {gw} 无响应，可能是路由器故障或网线松动", ["gateway", "arp", "adapter"])


def check_dns() -> CheckResult:
    targets = ["www.baidu.com", "www.msftconnecttest.com"]
    hits = []
    for t in targets:
        ip = dns_resolve(t)
        if ip:
            hits.append(f"{t} → {ip}")
    if len(hits) == len(targets):
        return CheckResult("dns", "DNS 域名解析", LEVEL_OK, "解析正常：" + "；".join(hits))
    if hits:
        return CheckResult("dns", "DNS 域名解析", LEVEL_WARN,
                           "部分域名解析失败：" + "；".join(hits),
                           ["dns_cache", "dns_server"])
    return CheckResult("dns", "DNS 域名解析", LEVEL_ERROR,
                       "所有域名均无法解析，DNS 服务异常或被劫持",
                       ["dns_cache", "dns_server", "hosts", "services"])


def check_direct() -> CheckResult:
    """直连探测：原始 socket，不经过任何代理。"""
    probes = [("223.5.5.5", 443), ("119.29.29.29", 443), ("114.114.114.114", 53)]
    ok = [f"{h}:{p}" for h, p in probes if tcp_probe(h, p, 3.0)]
    if ok:
        return CheckResult("direct", "外网直连（绕过代理）", LEVEL_OK,
                           f"可直接连通 {'、'.join(ok)}")
    return CheckResult("direct", "外网直连（绕过代理）", LEVEL_ERROR,
                       "无法建立任何外网 TCP 连接，链路层或协议栈异常",
                       ["tcpip", "winsock", "gateway", "firewall"])


_HTTP_TARGETS = [
    "http://www.msftconnecttest.com/connecttest.txt",
    "http://connect.rom.miui.com/generate_204",
    "http://www.baidu.com",
]


def check_via_proxy() -> CheckResult:
    """代理路径探测：走系统代理配置发起 HTTP 请求。

    单个站点可能因 CDN、代理节点抖动而偶发 502/超时，因此依次探测多个目标，
    只要有一个成功就判定 HTTP 通路正常，避免把偶发抖动误报成「断网」。
    """
    urls = ";".join(f"'{u}'" for u in _HTTP_TARGETS)
    script = (
        f"$ts=@({urls});"
        "foreach($u in $ts){"
        " try{$r=Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 6 -MaximumRedirection 3;"
        "      Write-Output ('OK|'+$u+'|'+[int]$r.StatusCode)}"
        " catch{$sc='';if($_.Exception.Response){$sc=[int]$_.Exception.Response.StatusCode};"
        "      Write-Output ('ERR|'+$u+'|'+$sc+'|'+$_.Exception.Message)}}"
    )
    res = run_ps(script, timeout=60)
    ok_hits, fails = [], []
    for line in (res.output or "").splitlines():
        line = line.strip()
        if line.startswith("OK|"):
            parts = line.split("|")
            ok_hits.append(f"{_short_host(parts[1])}（HTTP {parts[-1]}）")
        elif line.startswith("ERR|"):
            parts = line.split("|", 3)
            code = parts[2] or "无响应"
            fails.append(f"{_short_host(parts[1])}（{code}）")

    if ok_hits:
        detail = "HTTP 请求成功：" + "、".join(ok_hits)
        if fails:
            detail += f"；另有 {len(fails)} 个站点未通（{'、'.join(fails)}），多为线路抖动，不影响判定"
        return CheckResult("http", "网页访问（走系统代理）", LEVEL_OK, detail)

    if not fails:
        return CheckResult("http", "网页访问（走系统代理）", LEVEL_WARN,
                           "未能获取探测结果，PowerShell 可能被安全软件拦截", [])
    return CheckResult("http", "网页访问（走系统代理）", LEVEL_ERROR,
                       f"{len(fails)} 个测试站点全部无法访问：{'、'.join(fails)}",
                       ["proxy", "winsock", "dns_cache"])


def _short_host(url: str) -> str:
    try:
        return url.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return url


def check_proxy_settings() -> CheckResult:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    enable, server, pac = 0, "", ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            for name in ("ProxyEnable", "ProxyServer", "AutoConfigURL"):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                    if name == "ProxyEnable":
                        enable = int(value)
                    elif name == "ProxyServer":
                        server = str(value)
                    else:
                        pac = str(value)
                except FileNotFoundError:
                    pass
    except OSError:
        pass

    winhttp = run_cmd(["netsh", "winhttp", "show", "proxy"], timeout=30)
    winhttp_direct = "直接访问" in winhttp.output or "Direct access" in winhttp.output

    problems = []
    if enable and server:
        problems.append(f"已启用代理服务器 {server}")
    if pac:
        problems.append(f"已配置自动代理脚本 {pac}")
    if not winhttp_direct and winhttp.ok:
        problems.append("WinHTTP 存在系统级代理")

    if problems:
        return CheckResult("proxy_cfg", "代理设置", LEVEL_WARN,
                           "；".join(problems) + "。若无需代理请重置", ["proxy"])
    return CheckResult("proxy_cfg", "代理设置", LEVEL_OK, "未启用代理，当前为直连模式")


def check_hosts() -> CheckResult:
    path = hosts_path()
    if not os.path.isfile(path):
        return CheckResult("hosts_chk", "Hosts 文件", LEVEL_WARN,
                           "Hosts 文件不存在", ["hosts"])
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError as exc:
        return CheckResult("hosts_chk", "Hosts 文件", LEVEL_WARN, f"无法读取：{exc}", [])

    entries = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            entries.append((parts[0], parts[1:]))

    blocking = [e for e in entries if e[0] in ("0.0.0.0", "127.0.0.1", "::1")
                and not all(h.lower() in ("localhost", "localhost.localdomain") for h in e[1])]
    size = os.path.getsize(path)

    if len(entries) == 0:
        return CheckResult("hosts_chk", "Hosts 文件", LEVEL_OK, "无自定义映射，状态干净")
    if len(blocking) >= 10 or size > 64 * 1024:
        return CheckResult("hosts_chk", "Hosts 文件", LEVEL_ERROR,
                           f"存在 {len(entries)} 条映射（其中 {len(blocking)} 条屏蔽型），"
                           f"文件 {size // 1024}KB，疑似被篡改或广告屏蔽表", ["hosts"])
    return CheckResult("hosts_chk", "Hosts 文件", LEVEL_WARN,
                       f"存在 {len(entries)} 条自定义映射，若访问异常可考虑重置", ["hosts"])


# Windows 自带的传输服务提供程序 DLL（与系统语言无关）
_SYSTEM_LSP_DLLS = {
    "mswsock.dll", "winrnr.dll", "napinsp.dll", "pnrpnsp.dll", "nlaapi.dll",
    "wshbth.dll", "rasadhlp.dll", "wshqos.dll", "wshtcpip.dll", "wship6.dll",
    "winhttp.dll", "whhelper.dll", "wshhyperv.dll", "wshunix.dll",
}


def parse_winsock_catalog(text: str) -> tuple[int, list[str]]:
    """解析 netsh winsock show catalog。

    只看「目录提供程序项」（传输服务提供程序），命名空间提供程序不属于 LSP，
    并且通过 DLL 路径而非本地化描述文本来判定，避免中文系统误报。
    返回 (目录项数量, 可疑 DLL 路径列表)。
    """
    section = None
    count = 0
    paths: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if ("目录提供程序项" in s) or ("Catalog Provider Entry" in s):
            section = "catalog"
            count += 1
            continue
        if ("命名空间提供程序项" in s) or ("NameSpace Provider Entry" in s):
            section = "ns"
            continue
        if section != "catalog":
            continue
        if s.startswith("提供程序路径") or s.startswith("Provider Path"):
            value = s.split(":", 1)[1].strip() if ":" in s else ""
            if value:
                paths.append(value)

    suspicious: list[str] = []
    for p in dict.fromkeys(paths):
        expanded = os.path.expandvars(p).lower().replace("/", "\\")
        base = os.path.basename(expanded)
        win = os.environ.get("SystemRoot", r"C:\Windows").lower()
        in_system = expanded.startswith(win + "\\system32") or \
            expanded.startswith(win + "\\syswow64")
        if base in _SYSTEM_LSP_DLLS and in_system:
            continue
        suspicious.append(p)
    return count, suspicious


def check_winsock() -> CheckResult:
    res = run_cmd(["netsh", "winsock", "show", "catalog"], timeout=60)
    if not res.ok:
        return CheckResult("lsp", "Winsock / LSP", LEVEL_WARN, "无法读取 Winsock 目录", [])
    count, suspicious = parse_winsock_catalog(res.output)
    if suspicious:
        return CheckResult(
            "lsp", "Winsock / LSP", LEVEL_ERROR,
            f"共 {count} 个传输服务提供程序，其中 {len(suspicious)} 个由第三方注入："
            f"{'；'.join(suspicious[:3])}。这类 LSP 劫持常导致浏览器无法联网",
            ["winsock"])
    if count == 0:
        return CheckResult("lsp", "Winsock / LSP", LEVEL_WARN,
                           "未解析到任何传输服务提供程序，Winsock 目录可能已损坏", ["winsock"])
    return CheckResult("lsp", "Winsock / LSP", LEVEL_OK,
                       f"共 {count} 个传输服务提供程序，全部为系统内置组件，未发现 LSP 劫持")


def check_services() -> CheckResult:
    names = ["Dhcp", "Dnscache", "nsi", "netprofm", "NlaSvc"]
    # 注意：ServiceControllerStatus 是枚举，ConvertTo-Json 会序列化成数字（4=Running），
    # 必须显式 ToString()，否则会把正常运行的服务全部误判为「未运行」。
    script = (
        "Get-Service -Name " + ",".join(f"'{n}'" for n in names) +
        " -ErrorAction SilentlyContinue | "
        "Select-Object Name,@{n='Status';e={$_.Status.ToString()}} | ConvertTo-Json -Compress"
    )
    res = run_ps(script, timeout=60)
    try:
        data = json.loads(res.output) if res.output else []
    except json.JSONDecodeError:
        data = []
    if isinstance(data, dict):
        data = [data]
    if not data:
        return CheckResult("svc", "网络系统服务", LEVEL_WARN, "无法查询服务状态", [])
    stopped = [d.get("Name") for d in data if str(d.get("Status", "")).lower() != "running"]
    if stopped:
        return CheckResult("svc", "网络系统服务", LEVEL_ERROR,
                           f"以下关键服务未运行：{'、'.join(str(s) for s in stopped)}", ["services"])
    return CheckResult("svc", "网络系统服务", LEVEL_OK,
                       f"{len(data)} 项关键网络服务均正常运行")


# ------------------------------------------------------------------ 编排

CHECKS = [
    ("网络适配器", check_adapter),
    ("IP 地址配置", check_ip),
    ("默认网关", check_gateway),
    ("DNS 域名解析", check_dns),
    ("外网直连", check_direct),
    ("网页访问", check_via_proxy),
    ("代理设置", check_proxy_settings),
    ("Hosts 文件", check_hosts),
    ("Winsock / LSP", check_winsock),
    ("网络系统服务", check_services),
]


def diagnose_conclusion(results: list[CheckResult]) -> tuple[str, str]:
    """根据双路探测结果给出病因结论 (level, text)。"""
    by_key = {r.key: r for r in results}

    def lvl(key: str) -> str:
        return by_key[key].level if key in by_key else LEVEL_OK

    direct_ok = lvl("direct") == LEVEL_OK
    http_ok = lvl("http") == LEVEL_OK
    dns_ok = lvl("dns") == LEVEL_OK
    adapter_bad = lvl("adapter") == LEVEL_ERROR
    gw_bad = lvl("gateway") == LEVEL_ERROR
    lsp_bad = lvl("lsp") == LEVEL_ERROR
    proxy_set = lvl("proxy_cfg") != LEVEL_OK

    if adapter_bad:
        return LEVEL_ERROR, "网卡未连接。请先检查网线是否插好、无线是否开启，再执行修复。"
    if gw_bad:
        return LEVEL_ERROR, "无法与路由器通信。建议修复默认网关并重启网络适配器。"
    if direct_ok and not http_ok and proxy_set:
        return LEVEL_ERROR, "确诊为代理问题：直连正常但走代理失败，多为流氓软件偷设代理或梯子失效，重置代理即可。"
    if direct_ok and not http_ok and lsp_bad:
        return LEVEL_ERROR, "确诊为 Winsock / LSP 损坏：底层连接正常但 HTTP 走不出去，重置 Winsock 后重启即可。"
    if direct_ok and not dns_ok:
        return LEVEL_ERROR, "确诊为 DNS 故障：IP 可通但域名解析失败，建议刷新 DNS 缓存并恢复自动获取 DNS。"
    if not direct_ok:
        return LEVEL_ERROR, "底层网络不通：TCP/IP 协议栈可能损坏，建议重置协议栈与 Winsock 后重启。"
    if not http_ok:
        return LEVEL_ERROR, "网页无法打开但底层连通，建议重置代理与 Winsock。"
    if any(r.level == LEVEL_WARN for r in results):
        return LEVEL_WARN, "网络基本正常，但存在若干可优化项，可按建议选择性修复。"
    return LEVEL_OK, "网络状态良好，各项检查均通过，暂无需修复。"


def collect_suggestions(results: list[CheckResult]) -> list[str]:
    """汇总自动勾选的修复项。

    只采纳「异常(ERROR)」级检查给出的建议——「注意(WARN)」仅在界面上提示，
    不自动勾选。这样可避免把用户正在正常使用的配置（例如可用的本地代理、
    自己维护的 Hosts 映射）当成故障给清掉，符合「按病因最小修复」的原则。
    """
    keys: list[str] = []
    for r in results:
        if r.level != LEVEL_ERROR:
            continue
        for k in r.suggest:
            if k not in keys:
                keys.append(k)
    return keys


def _post_process(results: list[CheckResult]) -> None:
    """交叉校正：代理路径通畅时，已启用的代理不算故障。"""
    by_key = {r.key: r for r in results}
    http = by_key.get("http")
    proxy = by_key.get("proxy_cfg")
    if http is not None and proxy is not None and http.level == LEVEL_OK:
        if proxy.level == LEVEL_WARN:
            proxy.level = LEVEL_OK
            proxy.suggest = []
            proxy.detail = proxy.detail.split("。若无需代理")[0] + \
                "。经实测该代理工作正常，无需处理；如需彻底断开代理可手动勾选重置。"


def run_all(progress=None) -> list[CheckResult]:
    results: list[CheckResult] = []
    total = len(CHECKS)
    for idx, (label, fn) in enumerate(CHECKS, start=1):
        if progress:
            progress(idx - 1, total, f"正在检测：{label}")
        try:
            r = fn()
        except Exception as exc:  # noqa: BLE001
            r = CheckResult(f"err{idx}", label, LEVEL_WARN, f"检测异常：{exc}")
        LOGGER.write(f"诊断 [{r.name}] {LEVEL_TEXT.get(r.level, r.level)} - {r.detail}",
                     "OK" if r.level == LEVEL_OK else "WARN")
        results.append(r)
    _post_process(results)
    if progress:
        progress(total, total, "检测完成")
    return results
