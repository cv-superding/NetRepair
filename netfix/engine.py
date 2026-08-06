"""网络修复引擎。

每个修复项 = 一个 RepairItem，内部由若干「步骤」组成。
执行结果精确到步骤级别，方便用户看到到底做了什么、哪一步失败。

风险分级：
  safe   —— 无副作用，可放心执行（默认勾选）
  medium —— 会短暂断网或改动配置，已做备份（默认勾选）
  high   —— 会清空用户自定义规则/数据（默认不勾选，需手动确认）

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import winreg
from dataclasses import dataclass, field
from typing import Callable

from .sysutil import (
    BACKUP_DIR,
    LOGGER,
    CmdResult,
    ensure_dirs,
    hosts_path,
    run_cmd,
    run_ps,
    run_shell,
)

# ==================================================================== 数据结构

RISK_SAFE = "safe"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

RISK_TEXT = {RISK_SAFE: "安全", RISK_MEDIUM: "常规", RISK_HIGH: "谨慎"}


@dataclass
class StepResult:
    title: str
    ok: bool
    detail: str = ""


@dataclass
class RepairResult:
    ok: bool
    steps: list[StepResult] = field(default_factory=list)
    summary: str = ""
    need_reboot: bool = False


@dataclass
class RepairItem:
    key: str
    name: str
    desc: str
    risk: str
    action: Callable[[], RepairResult]
    default_checked: bool = True
    need_reboot: bool = False
    note: str = ""


# ==================================================================== 备份

DEFAULT_HOSTS = """# Copyright (c) 1993-2009 Microsoft Corp.
#
# This is a sample HOSTS file used by Microsoft TCP/IP for Windows.
#
# This file contains the mappings of IP addresses to host names. Each
# entry should be kept on an individual line. The IP address should
# be placed in the first column followed by the corresponding host name.
# The IP address and the host name should be separated by at least one
# space.
#
# Additionally, comments (such as these) may be inserted on individual
# lines or following the machine name denoted by a '#' symbol.
#
# For example:
#
#      102.54.94.97     rhino.acme.com          # source server
#       38.25.63.10     x.acme.com              # x client host

# localhost name resolution is handled within DNS itself.
#\t127.0.0.1       localhost
#\t::1             localhost
"""


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_file(src: str, tag: str) -> str | None:
    """备份文件到备份目录，返回备份路径。"""
    ensure_dirs()
    if not os.path.isfile(src):
        return None
    dst = os.path.join(BACKUP_DIR, f"{tag}_{_stamp()}.bak")
    try:
        shutil.copy2(src, dst)
        LOGGER.info(f"已备份 {src} -> {dst}")
        return dst
    except OSError as exc:
        LOGGER.warn(f"备份 {src} 失败：{exc}")
        return None


def backup_json(data: dict, tag: str) -> str | None:
    ensure_dirs()
    dst = os.path.join(BACKUP_DIR, f"{tag}_{_stamp()}.json")
    try:
        with open(dst, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        LOGGER.info(f"已备份配置 -> {dst}")
        return dst
    except OSError as exc:
        LOGGER.warn(f"备份配置失败：{exc}")
        return None


def list_backups() -> list[dict]:
    ensure_dirs()
    out: list[dict] = []
    try:
        names = os.listdir(BACKUP_DIR)
    except OSError:
        return out
    for name in sorted(names, reverse=True):
        full = os.path.join(BACKUP_DIR, name)
        if not os.path.isfile(full):
            continue
        if name.startswith("hosts_"):
            kind, label = "hosts", "Hosts 文件"
        elif name.startswith("proxy_"):
            kind, label = "proxy", "代理设置"
        else:
            kind, label = "other", "其它"
        try:
            st = os.stat(full)
            ts = _dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            size = st.st_size
        except OSError:
            ts, size = "-", 0
        out.append({"name": name, "path": full, "kind": kind,
                    "label": label, "time": ts, "size": size})
    return out


def restore_backup(path: str) -> tuple[bool, str]:
    """还原一个备份文件。"""
    name = os.path.basename(path)
    if not os.path.isfile(path):
        return False, "备份文件不存在"
    try:
        if name.startswith("hosts_"):
            target = hosts_path()
            backup_file(target, "hosts_beforerestore")
            shutil.copy2(path, target)
            run_cmd(["ipconfig", "/flushdns"], timeout=30)
            return True, f"已还原 Hosts 文件到 {target}"
        if name.startswith("proxy_"):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            _apply_proxy_settings(data)
            _notify_wininet()
            return True, "已还原系统代理设置"
        return False, "未知的备份类型，无法自动还原"
    except Exception as exc:  # noqa: BLE001
        return False, f"还原失败：{exc}"


# ==================================================================== 注册表 / 代理

_INET_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
_PROXY_VALUES = ("ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL", "MigrateProxy")


def read_proxy_settings() -> dict:
    data: dict = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INET_KEY, 0, winreg.KEY_READ) as key:
            for name in _PROXY_VALUES:
                try:
                    value, vtype = winreg.QueryValueEx(key, name)
                    data[name] = {"value": value, "type": vtype}
                except FileNotFoundError:
                    pass
    except OSError:
        pass
    return data


def _apply_proxy_settings(data: dict) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INET_KEY, 0, winreg.KEY_SET_VALUE) as key:
        for name in _PROXY_VALUES:
            if name in data:
                entry = data[name]
                winreg.SetValueEx(key, name, 0, entry["type"], entry["value"])
            else:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass


def _notify_wininet() -> None:
    """通知 WinINet 代理配置已变更，使浏览器立即生效。"""
    try:
        import ctypes

        wininet = ctypes.windll.Wininet
        wininet.InternetSetOptionW(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
        wininet.InternetSetOptionW(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH
    except Exception:  # noqa: BLE001
        pass


def _clear_proxy_for_hive(root, subkey: str) -> tuple[bool, str]:
    removed: list[str] = []
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            try:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
                removed.append("ProxyEnable=0")
            except OSError:
                pass
            for name in ("ProxyServer", "ProxyOverride", "AutoConfigURL"):
                try:
                    winreg.DeleteValue(key, name)
                    removed.append(f"删除 {name}")
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
    except FileNotFoundError:
        return True, "该用户配置不存在，跳过"
    except OSError as exc:
        return False, f"访问注册表失败：{exc}"
    return True, "，".join(removed) if removed else "无需修改"


# ==================================================================== 工具函数

def _step(res: RepairResult, title: str, cmd: CmdResult,
          tolerate: bool = False, success_hint: str = "") -> None:
    """把一次命令执行结果记录为一个步骤。"""
    ok = cmd.ok or tolerate
    detail = cmd.first_line() or ("执行完成" if cmd.ok else f"返回码 {cmd.code}")
    if cmd.ok and success_hint:
        detail = success_hint
    if not cmd.ok and tolerate:
        detail = f"已跳过（{detail}）"
    res.steps.append(StepResult(title, ok, detail))
    LOGGER.write(f"{title} -> {'成功' if ok else '失败'} | {detail}",
                 "OK" if ok else "ERROR")


def _finish(res: RepairResult, ok_msg: str, fail_msg: str) -> RepairResult:
    failed = [s for s in res.steps if not s.ok]
    res.ok = not failed
    res.summary = ok_msg if res.ok else f"{fail_msg}（{len(failed)}/{len(res.steps)} 步失败）"
    return res


def get_active_adapters() -> list[dict]:
    """获取已启用的物理网卡列表。"""
    script = (
        "Get-NetAdapter -Physical | Where-Object {$_.Status -eq 'Up'} | "
        "Select-Object Name,InterfaceIndex,InterfaceDescription | ConvertTo-Json -Compress"
    )
    res = run_ps(script, timeout=60)
    if not res.ok or not res.output:
        return []
    try:
        data = json.loads(res.output)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [d for d in data if isinstance(d, dict)]


# ==================================================================== 各修复项实现

def fix_dns_cache() -> RepairResult:
    """刷新 DNS 缓存。"""
    res = RepairResult(ok=True)
    _step(res, "清空 DNS 解析缓存", run_cmd(["ipconfig", "/flushdns"], timeout=45),
          success_hint="已成功刷新 DNS 解析缓存")
    _step(res, "重新注册 DNS 记录", run_cmd(["ipconfig", "/registerdns"], timeout=90),
          tolerate=True)
    _step(res, "重启 DNS Client 服务", run_ps(
        "Restart-Service -Name Dnscache -Force; if($?){'Dnscache 服务已重启'}else{'服务受保护，已跳过'}",
        timeout=60), tolerate=True)
    return _finish(res, "DNS 缓存已刷新", "DNS 缓存刷新部分失败")


def fix_winsock() -> RepairResult:
    """重置 Winsock 目录（清除第三方 LSP 劫持）。"""
    res = RepairResult(ok=True, need_reboot=True)
    _step(res, "重置 Winsock 目录", run_cmd(["netsh", "winsock", "reset"], timeout=90),
          success_hint="Winsock 目录已重置为默认状态")
    _step(res, "重置 Winsock 目录项（catalog）",
          run_cmd(["netsh", "winsock", "reset", "catalog"], timeout=90), tolerate=True)
    _step(res, "重置 WinHTTP 代理", run_cmd(["netsh", "winhttp", "reset", "proxy"], timeout=60),
          tolerate=True)
    return _finish(res, "Winsock 已重置（需重启生效）", "Winsock 重置部分失败")


def fix_tcpip() -> RepairResult:
    """重置 TCP/IP 协议栈。"""
    res = RepairResult(ok=True, need_reboot=True)
    _step(res, "重置 IP 协议栈", run_cmd(["netsh", "int", "ip", "reset"], timeout=120),
          success_hint="IP 协议栈已重置")
    _step(res, "重置 IPv4 配置", run_cmd(["netsh", "int", "ipv4", "reset"], timeout=120),
          tolerate=True)
    _step(res, "重置 IPv6 配置", run_cmd(["netsh", "int", "ipv6", "reset"], timeout=120),
          tolerate=True)
    _step(res, "重置 TCP 全局参数", run_cmd(["netsh", "int", "tcp", "reset"], timeout=120),
          tolerate=True)
    _step(res, "恢复 TCP 自动调优", run_cmd(
        ["netsh", "int", "tcp", "set", "global", "autotuninglevel=normal"], timeout=60),
        tolerate=True)
    return _finish(res, "TCP/IP 协议栈已重置（需重启生效）", "TCP/IP 重置部分失败")


def fix_gateway() -> RepairResult:
    """修复默认网关：释放并重新获取 IP 与网关。"""
    res = RepairResult(ok=True)
    _step(res, "释放当前 IP 地址", run_cmd(["ipconfig", "/release"], timeout=90), tolerate=True)
    _step(res, "重新获取 IP 与默认网关", run_cmd(["ipconfig", "/renew"], timeout=120),
          success_hint="已向 DHCP 服务器重新申请地址")

    gw = run_ps(
        "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | "
        "Sort-Object RouteMetric | Select-Object -First 1).NextHop", timeout=45)
    got = gw.output.strip()
    if got and got not in ("0.0.0.0",):
        res.steps.append(StepResult("校验默认网关", True, f"当前默认网关：{got}"))
        LOGGER.ok(f"校验默认网关 -> {got}")
        ping = run_cmd(["ping", "-n", "2", "-w", "1200", got], timeout=30)
        reachable = ping.ok and ("TTL=" in ping.output or "ttl=" in ping.output)
        res.steps.append(StepResult("测试网关连通性", reachable,
                                    "网关可达" if reachable else "网关暂不可达，请检查路由器或网线"))
    else:
        res.steps.append(StepResult("校验默认网关", False,
                                    "未检测到默认网关，请确认网线/无线已连接"))
        LOGGER.error("校验默认网关 -> 未检测到默认网关")
    return _finish(res, "默认网关已修复", "默认网关修复未完全成功")


def fix_hosts() -> RepairResult:
    """重置 Hosts 文件为系统默认内容（自动备份原文件）。"""
    res = RepairResult(ok=True)
    path = hosts_path()
    bak = backup_file(path, "hosts")
    res.steps.append(StepResult("备份原 Hosts 文件", bak is not None,
                                f"备份至 {bak}" if bak else "原文件不存在或无法备份，将直接写入默认内容"))
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass
    try:
        with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(DEFAULT_HOSTS)
        res.steps.append(StepResult("写入默认 Hosts 内容", True, f"已重置 {path}"))
        LOGGER.ok(f"写入默认 Hosts 内容 -> {path}")
    except OSError as exc:
        res.steps.append(StepResult("写入默认 Hosts 内容", False,
                                    f"写入失败：{exc}（可能被安全软件保护）"))
        LOGGER.error(f"写入 Hosts 失败：{exc}")
    _step(res, "刷新 DNS 缓存使其生效", run_cmd(["ipconfig", "/flushdns"], timeout=45),
          tolerate=True)
    return _finish(res, "Hosts 文件已重置", "Hosts 重置失败")


def fix_proxy() -> RepairResult:
    """重置浏览器 / 系统代理设置。"""
    res = RepairResult(ok=True)
    old = read_proxy_settings()
    if old:
        bak = backup_json(old, "proxy")
        res.steps.append(StepResult("备份当前代理设置", bak is not None,
                                    f"备份至 {bak}" if bak else "备份失败，但不影响修复"))

    ok, detail = _clear_proxy_for_hive(winreg.HKEY_CURRENT_USER, _INET_KEY)
    res.steps.append(StepResult("清除当前用户代理（IE / Edge / Chrome 共用）", ok, detail))
    LOGGER.write(f"清除当前用户代理 -> {detail}", "OK" if ok else "ERROR")

    ok2, detail2 = _clear_proxy_for_hive(winreg.HKEY_USERS, ".DEFAULT\\" + _INET_KEY)
    res.steps.append(StepResult("清除系统默认用户代理", True,
                                detail2 if ok2 else f"跳过（{detail2}）"))

    _step(res, "重置 WinHTTP 系统级代理",
          run_cmd(["netsh", "winhttp", "reset", "proxy"], timeout=60),
          success_hint="WinHTTP 已恢复为直连")
    _step(res, "重置 WinHTTP 代理追踪", run_cmd(["netsh", "winhttp", "reset", "tracing"], timeout=45),
          tolerate=True)

    _notify_wininet()
    res.steps.append(StepResult("通知浏览器刷新代理配置", True, "已广播设置变更消息"))
    return _finish(res, "代理设置已恢复为直连", "代理重置部分失败")


def fix_arp_netbios() -> RepairResult:
    """清理 ARP 与 NetBIOS 缓存。"""
    res = RepairResult(ok=True)
    _step(res, "清空 ARP 缓存", run_shell("arp -d *", timeout=45), tolerate=True,
          success_hint="ARP 缓存已清空")
    _step(res, "重置 NetBIOS 名称缓存", run_cmd(["nbtstat", "-R"], timeout=45), tolerate=True)
    _step(res, "释放并刷新 NetBIOS 名称", run_cmd(["nbtstat", "-RR"], timeout=45), tolerate=True)
    _step(res, "清理邻居缓存", run_ps(
        "Clear-NetNeighbor -Confirm:$false -ErrorAction SilentlyContinue; '邻居缓存已清理'",
        timeout=60), tolerate=True)
    return _finish(res, "ARP / NetBIOS 缓存已清理", "缓存清理部分失败")


def fix_dns_server_auto() -> RepairResult:
    """将 DNS 服务器恢复为自动获取（清除被篡改的 DNS）。"""
    res = RepairResult(ok=True)
    adapters = get_active_adapters()
    if not adapters:
        res.steps.append(StepResult("查找活动网卡", False, "未找到已连接的物理网卡"))
        return _finish(res, "", "未找到可修复的网卡")
    res.steps.append(StepResult("查找活动网卡", True,
                                "、".join(a.get("Name", "?") for a in adapters)))
    for ad in adapters:
        idx = ad.get("InterfaceIndex")
        name = ad.get("Name", str(idx))
        cmd = run_ps(
            f"Set-DnsClientServerAddress -InterfaceIndex {idx} -ResetServerAddresses; "
            f"if($?){{'已恢复自动获取 DNS'}}else{{'设置失败'}}", timeout=60)
        _step(res, f"恢复网卡「{name}」DNS 为自动获取", cmd, tolerate=True)
    _step(res, "刷新 DNS 缓存", run_cmd(["ipconfig", "/flushdns"], timeout=45), tolerate=True)
    return _finish(res, "DNS 服务器已恢复自动获取", "DNS 服务器恢复部分失败")


def fix_network_services() -> RepairResult:
    """修复网络相关系统服务（设为自动并启动）。"""
    services = [
        ("Dhcp", "DHCP Client"),
        ("Dnscache", "DNS Client"),
        ("nsi", "Network Store Interface"),
        ("netprofm", "Network List Service"),
        ("NlaSvc", "Network Location Awareness"),
        ("LanmanWorkstation", "Workstation"),
        ("WinHttpAutoProxySvc", "WinHTTP Web Proxy Auto-Discovery"),
    ]
    res = RepairResult(ok=True)
    for svc, label in services:
        script = (
            f"$s=Get-Service -Name '{svc}' -ErrorAction SilentlyContinue;"
            f"if($null -eq $s){{'服务不存在，跳过';exit 0}};"
            f"Set-Service -Name '{svc}' -StartupType Automatic -ErrorAction SilentlyContinue;"
            f"if($s.Status -ne 'Running'){{Start-Service -Name '{svc}' -ErrorAction SilentlyContinue}};"
            f"$s.Refresh();'当前状态：'+$s.Status"
        )
        _step(res, f"检查服务 {label} ({svc})", run_ps(script, timeout=60), tolerate=True)
    return _finish(res, "网络服务已检查并启动", "部分网络服务修复失败")


def fix_adapter_restart() -> RepairResult:
    """重启网络适配器。"""
    res = RepairResult(ok=True)
    adapters = get_active_adapters()
    if not adapters:
        res.steps.append(StepResult("查找活动网卡", False, "未找到已连接的物理网卡"))
        return _finish(res, "", "未找到可重启的网卡")
    for ad in adapters:
        name = ad.get("Name", "?")
        cmd = run_ps(
            f"Restart-NetAdapter -Name '{name}' -Confirm:$false; "
            f"if($?){{'网卡已重启'}}else{{'重启失败，可能需要驱动支持'}}", timeout=120)
        _step(res, f"重启网卡「{name}」", cmd, tolerate=True)
    _step(res, "重新获取 IP 地址", run_cmd(["ipconfig", "/renew"], timeout=120), tolerate=True)
    return _finish(res, "网络适配器已重启", "网卡重启部分失败")


def fix_firewall() -> RepairResult:
    """重置 Windows 防火墙为默认策略。"""
    res = RepairResult(ok=True)
    _step(res, "导出当前防火墙策略作为备份", run_cmd(
        ["netsh", "advfirewall", "export",
         os.path.join(BACKUP_DIR, f"firewall_{_stamp()}.wfw")], timeout=90), tolerate=True)
    _step(res, "重置防火墙为默认策略",
          run_cmd(["netsh", "advfirewall", "reset"], timeout=90),
          success_hint="防火墙已恢复默认策略")
    _step(res, "启用所有配置文件的防火墙", run_cmd(
        ["netsh", "advfirewall", "set", "allprofiles", "state", "on"], timeout=60), tolerate=True)
    return _finish(res, "防火墙已重置", "防火墙重置失败")


def fix_route_table() -> RepairResult:
    """清理路由表中的残留静态路由。"""
    res = RepairResult(ok=True)
    dump = run_cmd(["route", "print", "-4"], timeout=45)
    res.steps.append(StepResult("读取当前路由表", dump.ok,
                                f"共 {len(dump.output.splitlines())} 行" if dump.ok else "读取失败"))
    _step(res, "清除残留静态路由", run_shell("route -f", timeout=60), tolerate=True,
          success_hint="静态网关路由已清除")
    _step(res, "重新获取路由与网关", run_cmd(["ipconfig", "/renew"], timeout=120), tolerate=True)
    return _finish(res, "路由表已清理", "路由表清理部分失败")


def fix_ie_settings() -> RepairResult:
    """重置 IE / 系统 Internet 选项中的网络相关设置。"""
    res = RepairResult(ok=True)
    keys = [
        ("EnableHttp1_1", winreg.REG_DWORD, 1, "启用 HTTP 1.1"),
        ("ProxyHttp1.1", winreg.REG_DWORD, 0, "关闭代理 HTTP 1.1"),
        ("SecureProtocols", winreg.REG_DWORD, 0xA80, "启用 TLS 1.0/1.1/1.2"),
        ("GlobalUserOffline", winreg.REG_DWORD, 0, "取消脱机工作模式"),
    ]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INET_KEY, 0, winreg.KEY_SET_VALUE) as key:
            for name, vtype, value, label in keys:
                try:
                    winreg.SetValueEx(key, name, 0, vtype, value)
                    res.steps.append(StepResult(label, True, f"{name} = {value}"))
                except OSError as exc:
                    res.steps.append(StepResult(label, False, str(exc)))
    except OSError as exc:
        res.steps.append(StepResult("打开 Internet 设置注册表项", False, str(exc)))

    _step(res, "重置 WinHTTP SSL/TLS 默认设置", run_ps(
        "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; 'OK'",
        timeout=45), tolerate=True)
    _notify_wininet()
    return _finish(res, "Internet 选项已恢复默认", "Internet 选项修复部分失败")


def fix_tcp_tuning() -> RepairResult:
    """优化 TCP 全局参数（解决网速慢/卡顿）。"""
    res = RepairResult(ok=True)
    tweaks = [
        (["netsh", "int", "tcp", "set", "global", "autotuninglevel=normal"], "恢复接收窗口自动调优"),
        (["netsh", "int", "tcp", "set", "global", "chimney=disabled"], "关闭 TCP Chimney 卸载"),
        (["netsh", "int", "tcp", "set", "global", "rss=enabled"], "启用接收端缩放 RSS"),
        (["netsh", "int", "tcp", "set", "global", "ecncapability=disabled"], "关闭 ECN 拥塞通知"),
        (["netsh", "int", "tcp", "set", "global", "timestamps=disabled"], "关闭 TCP 时间戳"),
        (["netsh", "int", "ip", "set", "global", "taskoffload=disabled"], "关闭任务卸载"),
    ]
    for cmd, label in tweaks:
        _step(res, label, run_cmd(cmd, timeout=60), tolerate=True)
    return _finish(res, "TCP 参数已优化", "TCP 参数优化部分失败")


# ==================================================================== 修复项注册表

def build_items() -> list[RepairItem]:
    return [
        RepairItem(
            key="dns_cache", name="刷新 DNS 缓存", risk=RISK_SAFE,
            desc="清除本机 DNS 解析缓存并重新注册，解决网站解析到错误 IP、打不开个别网站的问题",
            action=fix_dns_cache, default_checked=True),

        RepairItem(
            key="winsock", name="重置 Winsock 目录", risk=RISK_MEDIUM,
            desc="清除第三方软件（VPN / 加速器 / 杀软）残留的 LSP 劫持，修复「有网但浏览器打不开」",
            action=fix_winsock, default_checked=True, need_reboot=True,
            note="重置后需重启计算机生效"),

        RepairItem(
            key="tcpip", name="重置 TCP/IP 协议栈", risk=RISK_MEDIUM,
            desc="将 IPv4 / IPv6 / TCP 全局配置恢复到 Windows 出厂默认，修复协议栈损坏",
            action=fix_tcpip, default_checked=True, need_reboot=True,
            note="重置后需重启计算机生效"),

        RepairItem(
            key="proxy", name="重置浏览器代理设置", risk=RISK_MEDIUM,
            desc="清除被流氓软件或失效梯子设置的 IE / Edge / Chrome 系统代理与 PAC 脚本，恢复直连",
            action=fix_proxy, default_checked=True,
            note="修改前会自动备份，可在「备份还原」页恢复"),

        RepairItem(
            key="gateway", name="修复默认网关", risk=RISK_MEDIUM,
            desc="释放并重新向路由器申请 IP 地址与默认网关，并测试网关连通性",
            action=fix_gateway, default_checked=True,
            note="执行过程中会短暂断网数秒"),

        RepairItem(
            key="dns_server", name="恢复 DNS 服务器为自动获取", risk=RISK_MEDIUM,
            desc="清除被篡改的手动 DNS 地址，恢复由路由器 / 运营商自动分配",
            action=fix_dns_server_auto, default_checked=True,
            note="若你手动设置过 114/223 等公共 DNS，将被清除"),

        RepairItem(
            key="arp", name="清理 ARP / NetBIOS 缓存", risk=RISK_SAFE,
            desc="清空地址解析与局域网名称缓存，解决局域网互访异常、ARP 欺骗残留",
            action=fix_arp_netbios, default_checked=True),

        RepairItem(
            key="services", name="修复网络系统服务", risk=RISK_SAFE,
            desc="检查 DHCP、DNS Client、NSI 等关键网络服务，设为自动启动并拉起",
            action=fix_network_services, default_checked=True),

        RepairItem(
            key="hosts", name="重置 Hosts 文件", risk=RISK_HIGH,
            desc="将 Hosts 恢复为系统默认内容，清除恶意屏蔽 / 域名劫持记录",
            action=fix_hosts, default_checked=False,
            note="会清空你手动添加的所有映射，修改前自动备份"),

        RepairItem(
            key="adapter", name="重启网络适配器", risk=RISK_HIGH,
            desc="禁用并重新启用物理网卡，解决网卡假死、感叹号、无法识别网络",
            action=fix_adapter_restart, default_checked=False,
            note="执行时会断网约 10 秒"),

        RepairItem(
            key="tcp_tuning", name="优化 TCP 全局参数", risk=RISK_MEDIUM,
            desc="恢复接收窗口自动调优、关闭易出问题的卸载功能，改善网速慢与频繁卡顿",
            action=fix_tcp_tuning, default_checked=False),

        RepairItem(
            key="firewall", name="重置 Windows 防火墙", risk=RISK_HIGH,
            desc="将防火墙恢复为默认策略，解决因错误规则导致的程序无法联网",
            action=fix_firewall, default_checked=False,
            note="会清空所有自定义防火墙规则，执行前自动导出备份"),

        RepairItem(
            key="route", name="清理路由表残留", risk=RISK_HIGH,
            desc="清除 VPN / 虚拟网卡遗留的持久化静态路由，修复部分网段无法访问",
            action=fix_route_table, default_checked=False,
            note="会短暂中断所有网络连接"),

        RepairItem(
            key="ie", name="修复 Internet 选项", risk=RISK_SAFE,
            desc="恢复 HTTP1.1、TLS 协议开关与脱机工作状态，修复网页报安全错误",
            action=fix_ie_settings, default_checked=False),
    ]
