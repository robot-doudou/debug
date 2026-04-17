"""检测 Intel RealSense D435i USB 设备与 SDK 可用性。

同时显示:
- USB 层信息 (macOS: ioreg / Linux: lsusb)
- pyrealsense2 枚举的设备、传感器、支持的流配置
"""

import re
import subprocess
import sys


def _detect_usb_macos():
    """通过 ioreg 检测 RealSense USB 设备 (macOS)。"""
    result = subprocess.run(
        ["ioreg", "-p", "IOUSB", "-l"],
        capture_output=True,
        text=True,
    )
    devices = []
    current = None
    depth = 0
    start_depth = -1
    for line in result.stdout.splitlines():
        if current is None and "RealSense" in line:
            current = {"header": line.strip()}
            start_depth = depth
        if current is not None:
            for key in [
                "USB Product Name",
                "USB Vendor Name",
                "USB Serial Number",
                "idVendor",
                "idProduct",
                "Device Speed",
                "bcdDevice",
            ]:
                pattern = r'"' + re.escape(key) + r'"\s*=\s*"?([^"}\n]+)"?'
                m = re.search(pattern, line)
                if m and key not in current:
                    current[key] = m.group(1).strip()
        depth += line.count("{") - line.count("}")
        if current is not None and depth <= start_depth and "}" in line:
            devices.append(current)
            current = None
            start_depth = -1
    return devices


def _detect_usb_linux():
    """通过 lsusb 检测 RealSense USB 设备 (Linux)。"""
    result = subprocess.run(
        ["lsusb", "-v", "-d", "8086:"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    devices = []
    current = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Bus ") and "Device " in stripped:
            if current is not None and _is_realsense(current):
                devices.append(current)
            current = {"header": stripped}
            continue
        if current is None:
            continue
        for key in [
            "idVendor",
            "idProduct",
            "iProduct",
            "iManufacturer",
            "iSerial",
            "bcdUSB",
        ]:
            if stripped.startswith(key + " "):
                value = stripped[len(key):].strip()
                if key.startswith("i") and len(key) > 1 and key[1].isupper():
                    value = re.sub(r"^\d+\s+", "", value)
                current[key] = value
    if current is not None and _is_realsense(current):
        devices.append(current)
    return devices


def _is_realsense(info: dict) -> bool:
    joined = " ".join(str(v) for v in info.values())
    return "RealSense" in joined or "D435" in joined or "D455" in joined


def detect_usb():
    if sys.platform == "darwin":
        return _detect_usb_macos()
    if sys.platform == "linux":
        return _detect_usb_linux()
    print(f"  不支持的平台: {sys.platform}")
    return []


# ioreg Device Speed 编码 (IOUSBFamily kUSBDeviceSpeed*)
_MACOS_SPEED = {
    "0": "low      (USB 1.0,     1.5 Mbps)",
    "1": "full     (USB 1.1,      12 Mbps)",
    "2": "high     (USB 2.0,     480 Mbps)",
    "3": "super    (USB 3.0,     5 Gbps)",
    "4": "super+   (USB 3.1 G2, 10 Gbps)",
    "5": "super+x2 (USB 3.2,    20 Gbps)",
}


def _pretty_usb(info: dict) -> dict:
    """将 idVendor/idProduct/Device Speed 转成更友好的显示。"""
    out = {}
    for k, v in info.items():
        if k in ("idVendor", "idProduct") and str(v).isdigit():
            out[k] = f"0x{int(v):04X} ({v})"
        elif k == "Device Speed" and str(v) in _MACOS_SPEED:
            out[k] = f"{v} → {_MACOS_SPEED[v]}"
        else:
            out[k] = v
    return out


def _probe_sdk_in_process():
    """实际枚举 SDK 设备。由 --sdk-probe 子进程调用。

    末尾用 os._exit(0) 跳过 Python/librealsense 析构：
    pyrealsense2-macosx 的 librealsense 轮询线程会在进程退出时与析构函数竞争 libusb mutex，
    导致 SIGSEGV (crash stack: polling_device_watcher::~dtor vs libusb_get_device_list)。
    """
    import json
    import os

    def _emit(payload):
        print(json.dumps(payload))
        sys.stdout.flush()
        os._exit(0)

    try:
        import pyrealsense2 as rs
    except ImportError as e:
        _emit({"error": f"import: {e}"})

    try:
        ctx = rs.context()
        ctx_devices = list(ctx.devices)
    except RuntimeError as e:
        _emit({"error": f"runtime: {e}"})

    devices = []
    for dev in ctx_devices:
        info = {
            "name": dev.get_info(rs.camera_info.name),
            "serial": dev.get_info(rs.camera_info.serial_number),
            "firmware": dev.get_info(rs.camera_info.firmware_version),
            "product_id": dev.get_info(rs.camera_info.product_id),
            "physical_port": dev.get_info(rs.camera_info.physical_port),
            "usb_type": dev.get_info(rs.camera_info.usb_type_descriptor)
            if dev.supports(rs.camera_info.usb_type_descriptor)
            else "",
            "sensors": [],
        }
        for sensor in dev.query_sensors():
            sensor_info = {
                "name": sensor.get_info(rs.camera_info.name),
                "profiles": [],
            }
            for profile in sensor.get_stream_profiles():
                stream_name = str(profile.stream_type()).split(".")[-1]
                fmt = str(profile.format()).split(".")[-1]
                fps = profile.fps()
                if profile.is_video_stream_profile():
                    v = profile.as_video_stream_profile()
                    desc = f"{stream_name:>8} {v.width()}x{v.height()} @ {fps:>3}fps {fmt}"
                else:
                    desc = f"{stream_name:>8}           @ {fps:>3}Hz  {fmt}"
                sensor_info["profiles"].append(desc)
            info["sensors"].append(sensor_info)
        devices.append(info)
    _emit({"devices": devices})


def detect_sdk():
    """在子进程里枚举 SDK 设备，防止 native 崩溃拖垮主进程。"""
    import json

    result = subprocess.run(
        [sys.executable, __file__, "--sdk-probe"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"  SDK 子进程异常退出 (code={result.returncode})")
        if result.returncode < 0 or result.returncode >= 128:
            sig = result.returncode - 128 if result.returncode >= 128 else -result.returncode
            print(f"  可能是 native 段错误 (signal {sig})")
        if sys.platform == "darwin":
            print("  macOS 常见原因: USB 2 协商 / 原生 UVC 驱动抢占，详见 README。")
        elif sys.platform == "linux":
            print("  Linux 常见原因: udev 规则未配置，尝试 sudo 或安装 99-realsense-libusb.rules。")
        if result.stderr.strip():
            print(f"  stderr: {result.stderr.strip()[:200]}")
        return []

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  SDK 输出解析失败: {result.stdout[:200]}")
        return []

    if "error" in payload:
        err = payload["error"]
        print(f"  SDK 访问失败: {err}")
        if err.startswith("import"):
            print("  请确认当前虚拟环境装了 pyrealsense2(-macosx)。")
        return []

    return payload.get("devices", [])


def main():
    print("=== USB 设备检测 ===")
    usb_devices = detect_usb()
    if not usb_devices:
        print("  未检测到 RealSense USB 设备")
    for d in usb_devices:
        print()
        for k, v in _pretty_usb(d).items():
            print(f"  {k}: {v}")

    print("\n=== RealSense SDK 设备枚举 ===")
    sdk_devices = detect_sdk()
    if not sdk_devices:
        print("  pyrealsense2 未找到设备")
        return
    for dev in sdk_devices:
        print(f"\n  [{dev['name']}]")
        for k in ("serial", "firmware", "product_id", "usb_type", "physical_port"):
            if dev.get(k):
                print(f"    {k}: {dev[k]}")
        for sensor in dev["sensors"]:
            print(f"\n    --- 传感器: {sensor['name']} ---")
            unique = sorted(set(sensor["profiles"]))
            for p in unique[:30]:
                print(f"      {p}")
            if len(unique) > 30:
                print(f"      ... (另有 {len(unique) - 30} 个配置)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sdk-probe":
        _probe_sdk_in_process()
    else:
        main()
