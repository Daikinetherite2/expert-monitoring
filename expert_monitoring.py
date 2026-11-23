#!/usr/bin/env python3
"""
DAIKI SYSTEM MONITOR
A modern, live Windows 11 terminal dashboard.

Requirements:
    py -m pip install rich psutil

Run:
    py daiki_monitor.py
Exit:
    Q or Ctrl+C
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import time
from datetime import datetime, timedelta

import psutil
from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

APP_NAME = "DAIKI SYSTEM MONITOR"
REFRESH_RATE = 1.0
PROCESS_LIMIT = 8

console = Console()
BOOT_TIME = psutil.boot_time()
LAST_NET = psutil.net_io_counters()
LAST_DISK = psutil.disk_io_counters()
LAST_SAMPLE = time.monotonic()


def fmt_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def fmt_rate(value: float) -> str:
    return f"{fmt_bytes(value)}/s"


def uptime_text() -> str:
    seconds = max(0, int(time.time() - BOOT_TIME))
    return str(timedelta(seconds=seconds)).split(".")[0]


def get_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("1.1.1.1", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "Unavailable"


def color_for(value: float) -> str:
    if value >= 85:
        return "bold red"
    if value >= 65:
        return "bold yellow"
    return "bold green"


def make_metric(title: str, value: str, subtitle: str, percent: float, color: str) -> Panel:
    percent = max(0.0, min(100.0, percent))
    content = Group(
        Text(value, style=f"bold {color}", justify="center"),
        Text(subtitle, style="dim", justify="center"),
        Text(""),
        ProgressBar(total=100, completed=percent, width=30, complete_style=color, finished_style=color),
    )
    return Panel(
        Align.center(content, vertical="middle"),
        title=f"[bold white]{title}[/]",
        border_style=color,
        box=box.ROUNDED,
        padding=(1, 1),
    )


def make_header() -> Panel:
    now = datetime.now().strftime("%A, %d %B %Y  |  %H:%M:%S")
    host = platform.node() or "Windows PC"
    os_name = f"{platform.system()} {platform.release()} ({platform.version().split('.')[0]})"
    left = Text()
    left.append("◆ ", style="bold cyan")
    left.append(APP_NAME, style="bold white")
    left.append("\n")
    left.append(f"{host}  •  {os_name}", style="dim")
    right = Text()
    right.append(now + "\n", style="bold white")
    right.append(f"Uptime: {uptime_text()}  •  IP: {get_ip()}", style="dim")
    grid = Table.grid(expand=True)
    grid.add_column(ratio=3)
    grid.add_column(justify="right", ratio=2)
    grid.add_row(left, right)
    return Panel(grid, border_style="cyan", box=box.ROUNDED, padding=(0, 2))


def make_system_info() -> Panel:
    cpu_name = platform.processor() or "CPU information unavailable"
    logical = psutil.cpu_count(logical=True) or 0
    physical = psutil.cpu_count(logical=False) or 0
    ram = psutil.virtual_memory()
    boot = datetime.fromtimestamp(BOOT_TIME).strftime("%d %b %Y %H:%M")
    rows = Table.grid(expand=True, padding=(0, 1))
    rows.add_column(style="dim", width=16)
    rows.add_column(style="white")
    rows.add_row("Processor", cpu_name[:65])
    rows.add_row("CPU cores", f"{physical} physical / {logical} logical")
    rows.add_row("Memory", f"{fmt_bytes(ram.total)} total")
    rows.add_row("Windows boot", boot)
    rows.add_row("Python", platform.python_version())
    return Panel(rows, title="[bold white]SYSTEM INFO[/]", border_style="bright_blue", box=box.ROUNDED)


def make_disk_panel() -> Panel:
    table = Table(box=box.SIMPLE, expand=True, show_header=True, header_style="bold cyan")
    table.add_column("Drive", style="white")
    table.add_column("Total", justify="right")
    table.add_column("Used", justify="right")
    table.add_column("Free", justify="right")
    table.add_column("Usage", justify="right")
    found = False
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts.lower():
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        found = True
        table.add_row(
            part.device or part.mountpoint,
            fmt_bytes(usage.total),
            fmt_bytes(usage.used),
            fmt_bytes(usage.free),
            f"[{color_for(usage.percent)}]{usage.percent:.0f}%[/]",
        )
    if not found:
        table.add_row("No accessible drives", "-", "-", "-", "-")
    return Panel(table, title="[bold white]STORAGE[/]", border_style="magenta", box=box.ROUNDED)


def make_process_panel() -> Panel:
    table = Table(box=box.SIMPLE, expand=True, show_header=True, header_style="bold cyan")
    table.add_column("PROCESS", ratio=3, no_wrap=True)
    table.add_column("PID", justify="right", width=7)
    table.add_column("CPU %", justify="right", width=8)
    table.add_column("MEMORY", justify="right", width=10)

    processes = []
    for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            info = proc.info
            mem = info["memory_info"].rss if info["memory_info"] else 0
            processes.append((info["name"] or "Unknown", info["pid"], info["cpu_percent"] or 0.0, mem))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    processes.sort(key=lambda item: item[3], reverse=True)
    for name, pid, cpu, memory in processes[:PROCESS_LIMIT]:
        table.add_row(
            name[:32],
            str(pid),
            f"{cpu:.1f}",
            fmt_bytes(memory),
        )
    return Panel(table, title=f"[bold white]TOP PROCESSES — BY MEMORY[/]", border_style="green", box=box.ROUNDED)


def make_network_panel(delta: float) -> Panel:
    global LAST_NET
    current = psutil.net_io_counters()
    rx = (current.bytes_recv - LAST_NET.bytes_recv) / max(delta, 0.001)
    tx = (current.bytes_sent - LAST_NET.bytes_sent) / max(delta, 0.001)
    LAST_NET = current

    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(
        Text.assemble(("↓ DOWNLOAD\n", "dim"), (fmt_rate(rx), "bold green")),
        Text.assemble(("↑ UPLOAD\n", "dim"), (fmt_rate(tx), "bold cyan")),
    )
    grid.add_row(
        Text.assemble(("Received total: ", "dim"), (fmt_bytes(current.bytes_recv), "white")),
        Text.assemble(("Sent total: ", "dim"), (fmt_bytes(current.bytes_sent), "white")),
    )
    return Panel(grid, title="[bold white]NETWORK[/]", border_style="cyan", box=box.ROUNDED)


def make_disk_io_panel(delta: float) -> Panel:
    global LAST_DISK
    current = psutil.disk_io_counters()
    if current is None:
        return Panel("Disk I/O information unavailable", title="DISK ACTIVITY", border_style="yellow")
    read_rate = (current.read_bytes - LAST_DISK.read_bytes) / max(delta, 0.001)
    write_rate = (current.write_bytes - LAST_DISK.write_bytes) / max(delta, 0.001)
    LAST_DISK = current
    content = Text()
    content.append("READ   ", style="dim")
    content.append(fmt_rate(read_rate) + "\n", style="bold green")
    content.append("WRITE  ", style="dim")
    content.append(fmt_rate(write_rate), style="bold yellow")
    return Panel(Align.center(content, vertical="middle"), title="[bold white]DISK ACTIVITY[/]", border_style="yellow", box=box.ROUNDED)


def build_layout(delta: float) -> Layout:
    cpu = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=4),
        Layout(name="metrics", size=9),
        Layout(name="middle", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["metrics"].split_row(
        Layout(make_metric("CPU", f"{cpu:.0f}%", f"{psutil.cpu_count(logical=True)} logical processors", cpu, color_for(cpu))),
        Layout(make_metric("MEMORY", f"{memory.percent:.0f}%", f"{fmt_bytes(memory.used)} / {fmt_bytes(memory.total)}", memory.percent, color_for(memory.percent))),
        Layout(make_metric("SWAP", f"{swap.percent:.0f}%", f"{fmt_bytes(swap.used)} / {fmt_bytes(swap.total)}", swap.percent, color_for(swap.percent))),
    )
    layout["middle"].split_row(
        Layout(name="left", ratio=3),
        Layout(name="right", ratio=2),
    )
    layout["left"].split_column(
        Layout(make_process_panel(), ratio=3),
        Layout(make_disk_panel(), ratio=2),
    )
    layout["right"].split_column(
        Layout(make_system_info(), ratio=3),
        Layout(make_network_panel(delta), ratio=2),
        Layout(make_disk_io_panel(delta), ratio=2),
    )
    footer = Text("  Q  Exit     Ctrl+C  Exit     Refresh: 1 second", style="dim", justify="center")
    layout["footer"].update(Panel(footer, border_style="grey50", box=box.ROUNDED))
    layout["header"].update(make_header())
    return layout


def main() -> None:
    # Prime CPU counters so the first displayed sample is meaningful.
    psutil.cpu_percent(interval=None)
    for proc in psutil.process_iter():
        try:
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    last = time.monotonic()
    try:
        with Live(build_layout(1.0), console=console, screen=True, auto_refresh=False, transient=False) as live:
            while True:
                now = time.monotonic()
                delta = now - last
                last = now
                live.update(build_layout(delta), refresh=True)
                time.sleep(REFRESH_RATE)
    except KeyboardInterrupt:
        pass
    finally:
        console.clear()
        console.print("[bold cyan]DAIKI SYSTEM MONITOR[/] [dim]closed[/]")


if __name__ == "__main__":
    main()
