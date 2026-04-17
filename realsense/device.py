"""Intel RealSense 共享工具: 设备定位、GUI 检测、输出路径。

D435i USB 标识:
    VID 0x8086 (Intel), PID 0x0B3A
"""

import os
import pathlib
import platform
import sys
from datetime import datetime

INTEL_VID = 0x8086
D435I_PID = 0x0B3A


def find_device(required_pid: int | None = D435I_PID):
    """通过 pyrealsense2 查找 RealSense 设备。

    Args:
        required_pid: 限定产品 ID (如 0x0B3A 表示 D435i)；None 则匹配任意 RealSense。

    Returns:
        (rs.device, info_dict) 或 (None, None)
    """
    import pyrealsense2 as rs

    ctx = rs.context()
    for dev in ctx.devices:
        pid_hex = dev.get_info(rs.camera_info.product_id)
        try:
            pid = int(pid_hex, 16)
        except ValueError:
            continue
        if required_pid is not None and pid != required_pid:
            continue
        info = {
            "name": dev.get_info(rs.camera_info.name),
            "serial": dev.get_info(rs.camera_info.serial_number),
            "firmware": dev.get_info(rs.camera_info.firmware_version),
            "physical_port": dev.get_info(rs.camera_info.physical_port),
            "pid": pid,
        }
        return dev, info
    return None, None


def has_display() -> bool:
    """判断当前会话是否可以打开 GUI 窗口。

    - macOS: 假定可用（本地图形会话）
    - Linux: 存在 DISPLAY 或 WAYLAND_DISPLAY 才可用（SSH 无转发时为 False）
    """
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def output_dir(subdir: str = "") -> pathlib.Path:
    """返回 ./out[/subdir]，不存在则创建。"""
    base = pathlib.Path(__file__).parent / "out"
    if subdir:
        base = base / subdir
    base.mkdir(parents=True, exist_ok=True)
    return base


def timestamped(prefix: str, ext: str) -> str:
    """生成带时间戳的文件名: <prefix>_YYYYMMDD_HHMMSS.<ext>"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}.{ext}"


def clean_exit(code: int = 0):
    """退出进程，macOS arm64 上跳过 Python/librealsense 析构。

    pyrealsense2-macosx 的 librealsense 在 context 销毁时有已知竞态:
    主线程 ~polling_device_watcher() 与后台轮询线程的 libusb_get_device_list
    争抢同一 libusb mutex，析构先一步释放后轮询线程访问 0x28 附近 → SIGSEGV。

    绕过方式是让进程由内核直接回收，不运行任何析构函数。
    """
    sys.stdout.flush()
    sys.stderr.flush()
    if sys.platform == "darwin" and platform.machine() == "arm64":
        os._exit(code)
    sys.exit(code)


def require_device(required_pid: int | None = D435I_PID):
    """查找设备，未找到则打印友好错误并退出。"""
    try:
        dev, info = find_device(required_pid)
    except Exception as e:
        print(f"[错误] pyrealsense2 访问设备失败: {e}", file=sys.stderr)
        sys.exit(1)
    if dev is None:
        target = "D435i" if required_pid == D435I_PID else "RealSense"
        print(f"[错误] 未找到 {target} 设备。请检查 USB 连接。", file=sys.stderr)
        if sys.platform == "linux":
            print("  Linux 用户需确保已配置 99-realsense-libusb.rules 或以 sudo 运行。", file=sys.stderr)
        sys.exit(1)
    return dev, info
