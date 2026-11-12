#!/usr/bin/env python3
# proxy_switcher.py - Windows 代理/内网安全切换工具
#
# 用法:
#   python proxy_switcher.py -y            开启科学上网 (连热点 + 开代理 + 设系统代理)
#   python proxy_switcher.py -n            回内网 (一次性: 杀代理 + 还原系统代理 + 可选禁用虚拟网卡)
#   python proxy_switcher.py -n --watch    回内网守护: 持续强制退出代理进程 (Ctrl+C 退出)
#
# 安全闸门: -y 模式下，只有在确认已连上"科学上网 WiFi"后才会开启代理；
#           若仍连着公司/未知网络，直接拒绝开启，避免在公司网直连梯子。
# 守护模式: -n --watch 会常驻后台，发现代理进程立即杀死，防止手滑重开导致 ARP 告警。

import argparse
import ctypes
import subprocess
import sys
import time

try:
    import psutil
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil"])
    import psutil

import winreg

# ===================== 配置区（按你的环境修改） =====================
CONFIG = {
    # -y 要启动的代理客户端。推荐纯 xray（进程单一、无 GUI、kill 确定）：
    "proxy_start_cmd": [
        r"E:\Software\v2rayN-windows-64_260708\v2rayN-windows-64\bin\xray\xray.exe",
        "-config",
        r"E:\Software\v2rayN-windows-64_260708\v2rayN-windows-64\bin\xray\config.json",
    ],
    # 备选1 仍用 v2rayN GUI（注意 v2rayN 不认 -config，仅启动界面）：
    # "proxy_start_cmd": [r"E:\Software\v2rayN-windows-64_260708\v2rayN-windows-64\v2rayN.exe"],
    # 备选2 完全手动启动（留空列表，自己开客户端）：
    # "proxy_start_cmd": [],

    # -n / --watch 要杀死的代理相关进程名（小写，含扩展名）
    # 同时含 GUI(v2rayN.exe) 与核心引擎(xray.exe)：杀 GUI 失败时可兜底杀引擎
    "proxy_process_names": [
        "v2rayN.exe", "xray.exe", "clash.exe", "clashpremium.exe",
        "tailscale.exe", "wintun.exe", "sing-box.exe",
    ],

    # -n 二次检测的"外网连通性探测"站点：内网模式下这些本应不可达；
    # 若任一能 ping 通，说明代理仍在泄漏（红色告警）。ping 不通≠绝对干净
    # （公司防火墙也会让它们不通），故仅作泄漏指示灯，不作为"干净证明"。
    "leak_check_hosts": ["google.com", "youtube.com"],

    # 系统代理地址（不带 http:// 前缀，直接 IP:PORT）
    #   v2ray 默认 http 代理常是 10809、10808；clash 常是 7890；按需改
    "proxy_server": "127.0.0.1:10808",
    "proxy_override": "localhost;127.0.0.1;10.*;192.168.*;172.16.*",

    # WiFi 切换（不需要则留空字符串 ""）
    "wifi_ssid_y": "shine",    # -y 要连的科学上网 WiFi
    "wifi_ssid_n": "dzds-a",    # -n 要连的内网 WiFi（可选兜底）

    # -n 要禁用的虚拟网卡关键字（需管理员；留空 [] 则跳过）
    "vnic_keywords": ["Wintun", "Tailscale", "TAP-Windows"],

    # WiFi 切换总开关
    "enable_wifi_switch": True,

    # --watch 守护扫描间隔（秒）。越小越及时但越占资源
    "guard_interval": 2,
}
# ===================================================================

INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
C = {"INFO": "\033[96m", "OK": "\033[92m", "WARN": "\033[93m",
     "ERR": "\033[91m", "END": "\033[0m"}


def log(msg, level="INFO"):
    print(f"{C.get(level, '')}[{level}]{C['END']} {msg}")


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---------- 系统代理 ----------
def _notify_proxy_change():
    try:
        internet_set_option = ctypes.windll.Wininet.InternetSetOptionW
        internet_set_option(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
        internet_set_option(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH
    except Exception:
        pass


def set_system_proxy(server, override):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, server)
            winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ, override)
        _notify_proxy_change()
        log(f"系统代理已设置为 {server}", "OK")
    except Exception as e:
        log(f"设置系统代理失败: {e}", "ERR")


def clear_system_proxy():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, "")
            winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ, "")
        _notify_proxy_change()
        log("系统代理已还原（关闭）", "OK")
    except Exception as e:
        log(f"还原系统代理失败: {e}", "ERR")


# ---------- 进程 ----------
def _try_kill(proc, pname):
    """尝试强杀进程，返回 'killed' / 'denied' / 'gone'"""
    try:
        proc.kill()
        return "killed"
    except psutil.AccessDenied:
        return "denied"
    except psutil.NoSuchProcess:
        return "gone"


def kill_proxy_processes(names):
    killed, denied = set(), set()
    for proc in psutil.process_iter(["name"]):
        try:
            pname = (proc.info["name"] or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if pname in names:
            log(f"发现代理进程 {pname}，尝试终止...", "WARN")
            r = _try_kill(proc, pname)
            if r == "killed":
                killed.add(pname)
            elif r == "denied":
                denied.add(pname)
    if killed:
        log(f"已杀死代理进程: {', '.join(sorted(killed))}", "OK")
    if denied:
        log(f"终止被拒绝(权限不足? 请以管理员运行): {', '.join(sorted(denied))}", "ERR")
    if not killed and not denied:
        log("未发现运行中的代理进程", "INFO")


def start_proxy(cmd):
    if not cmd:
        log("未配置 proxy_start_cmd，跳过自动启动（请手动启动代理客户端）", "WARN")
        return
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"已启动代理: {' '.join(cmd)}", "OK")
        time.sleep(2)
    except Exception as e:
        log(f"启动代理失败: {e}", "ERR")


# ---------- 进程状态检测 ----------
def list_proxy_processes(names):
    """返回当前仍在运行的代理进程名集合（用于二次确认）"""
    running = set()
    for proc in psutil.process_iter(["name"]):
        try:
            pname = (proc.info["name"] or "").lower()
            if pname in names:
                running.add(pname)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return running


def get_system_proxy_status():
    """读取当前系统代理状态，返回 (是否开启, 地址)"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS) as k:
            try:
                enabled = winreg.QueryValueEx(k, "ProxyEnable")[0]
            except FileNotFoundError:
                enabled = 0
            try:
                server = winreg.QueryValueEx(k, "ProxyServer")[0]
            except FileNotFoundError:
                server = ""
        return (bool(enabled), server or "")
    except Exception:
        return (False, "")


def verify_no_leak(hosts):
    """内网模式下 ping 外网站点：任一成功 = 疑似代理泄漏。返回成功(泄漏)的列表。"""
    if not hosts:
        return []
    leaked = []
    for h in hosts:
        try:
            r = subprocess.run(["ping", "-n", "1", "-w", "1500", h],
                               capture_output=True, text=True)
            if r.returncode == 0:
                leaked.append(h)
        except Exception:
            continue
    return leaked


# ---------- WiFi ----------
def get_current_wifi():
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "interfaces"],
            encoding="gbk", errors="ignore")
        for line in out.splitlines():
            if "SSID" in line and "BSSID" not in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        return None
    return None


def connect_wifi(ssid):
    if not ssid:
        return True
    try:
        r = subprocess.run(["netsh", "wlan", "connect", f"name={ssid}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            log(f"已发起连接 WiFi: {ssid}", "OK")
            return True
        log(f"连接 WiFi 失败: {ssid} ({r.stderr.strip()})", "ERR")
        return False
    except Exception as e:
        log(f"连接 WiFi 异常: {e}", "ERR")
        return False


# ---------- 虚拟网卡 ----------
def disable_vnics(keywords):
    if not keywords:
        return
    if not is_admin():
        log("禁用虚拟网卡需要管理员权限，已跳过（请以管理员运行以获得完整效果）", "WARN")
        return
    for kw in keywords:
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Disable-NetAdapter -Name '*{kw}*' -Confirm:$false -ErrorAction SilentlyContinue"],
                capture_output=True)
            log(f"已尝试禁用含 '{kw}' 的虚拟网卡", "OK")
        except Exception as e:
            log(f"禁用虚拟网卡异常 ({kw}): {e}", "WARN")


# ---------- 守护：持续强制退出代理进程 ----------
def guard_loop(interval):
    log(f"进入内网守护：每 {interval} 秒扫描，发现代理进程立即强制退出（Ctrl+C 退出）", "WARN")
    if not is_admin():
        log("当前未以管理员运行；若代理进程以管理员启动，终止可能被拒绝，请改用管理员运行。", "WARN")
    names = [n.lower() for n in CONFIG["proxy_process_names"]]
    try:
        while True:
            for proc in psutil.process_iter(["name"]):
                try:
                    pname = (proc.info["name"] or "").lower()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if pname in names:
                    log(f"守护发现 {pname}，强制终止...", "WARN")
                    r = _try_kill(proc, pname)
                    if r == "killed":
                        log(f"守护强制退出: {pname}", "OK")
                        clear_system_proxy()  # 双保险：顺手再还原一次系统代理
                    elif r == "denied":
                        log(f"守护终止被拒绝: {pname}（权限不足，请以管理员运行脚本）", "ERR")
            time.sleep(interval)
    except KeyboardInterrupt:
        log("守护已退出，恢复为普通状态（后续不再自动杀进程）", "INFO")


# ---------- 模式 ----------
def mode_yes():
    log("=== 开启科学上网模式 (-y) ===")
    if CONFIG["enable_wifi_switch"] and CONFIG["wifi_ssid_y"]:
        if not connect_wifi(CONFIG["wifi_ssid_y"]):
            log("无法连接科学上网 WiFi，中止。", "ERR")
            return
        time.sleep(4)
        cur = get_current_wifi()
        if cur != CONFIG["wifi_ssid_y"]:
            log(f"安全闸门：当前 WiFi 为 '{cur}'，并非科学上网网络。"
                f"拒绝在公司/未知网络下开启代理，已中止。", "ERR")
            return
        log(f"安全闸门通过：当前已连接 {cur}", "OK")
    else:
        log("未配置/未启用 WiFi 切换，跳过联网校验（请确认你已脱离公司网络）", "WARN")
    start_proxy(CONFIG["proxy_start_cmd"])
    set_system_proxy(CONFIG["proxy_server"], CONFIG["proxy_override"])
    log("科学上网模式就绪。", "OK")


def mode_no(watch=False):
    log("=== 回内网模式 (-n) ===")
    names = [n.lower() for n in CONFIG["proxy_process_names"]]
    kill_proxy_processes(names)
    clear_system_proxy()

    log("等待 5 秒以确认代理进程已彻底退出...", "INFO")
    time.sleep(5)

    # 二次检测：确认进程已死、系统代理已关、外网不可达
    remaining = list_proxy_processes(names)
    proxy_on, proxy_server = get_system_proxy_status()
    leaked = verify_no_leak(CONFIG.get("leak_check_hosts", []))
    problems = []
    if remaining:
        problems.append(f"仍有代理进程运行: {', '.join(sorted(remaining))}")
    if proxy_on:
        problems.append(f"系统代理仍未关闭（当前: {proxy_server}）")
    if leaked:
        problems.append(f"外网仍可连通（疑似代理泄漏）: {', '.join(leaked)}")

    if problems:
        log("二次检测未通过，暂不连接公司 WiFi，请手动排查：", "ERR")
        for p in problems:
            log(f"  - {p}", "ERR")
        if watch:
            guard_loop(CONFIG.get("guard_interval", 2))
        else:
            log("内网模式未完成：代理未彻底退出。", "WARN")
        return

    log("二次检测通过：代理已退出、系统代理已还原。", "OK")
    if CONFIG["enable_wifi_switch"] and CONFIG["wifi_ssid_n"]:
        connect_wifi(CONFIG["wifi_ssid_n"])
    disable_vnics(CONFIG["vnic_keywords"])
    if watch:
        guard_loop(CONFIG.get("guard_interval", 2))
    else:
        log("内网模式就绪（代理已关、系统代理已还原、已连内网）。", "OK")


def main():
    ap = argparse.ArgumentParser(description="代理/内网安全切换")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("-y", "--yes", action="store_true", help="开启科学上网")
    group.add_argument("-n", "--no", action="store_true", help="回内网")
    ap.add_argument("-w", "--watch", action="store_true",
                    help="内网守护：持续强制退出代理进程（需配合 -n，Ctrl+C 退出）")
    args = ap.parse_args()

    if args.no and not is_admin():
        if args.watch:
            log("提示：--watch 若无法杀死代理进程，请改用管理员运行本脚本。", "WARN")
        if CONFIG["vnic_keywords"]:
            log("提示：-n 含禁用虚拟网卡，建议以管理员运行以获得完整效果。", "WARN")

    if args.yes:
        if args.watch:
            log("--watch 仅在内网模式(-n)下有意义，已忽略。", "WARN")
        mode_yes()
    else:
        mode_no(watch=args.watch)


if __name__ == "__main__":
    main()
