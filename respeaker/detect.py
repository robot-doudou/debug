"""检测 ReSpeaker XVF3800 USB 设备信息。"""

import subprocess
import sys
import re


def _detect_usb_macos():
    """通过 ioreg 检测 XVF3800 USB 设备 (macOS)。"""
    result = subprocess.run(
        ["ioreg", "-p", "IOUSB", "-l"],
        capture_output=True,
        text=True,
    )
    lines = result.stdout.splitlines()
    device_info = {}
    in_device = False
    for line in lines:
        if "XVF3800" in line:
            in_device = True
            device_info["name"] = line.strip()
        if in_device:
            for key in [
                "USB Product Name",
                "USB Vendor Name",
                "USB Serial Number",
                "idVendor",
                "idProduct",
                "Device Speed",
            ]:
                pattern = r'"' + re.escape(key) + r'"\s*=\s*"?([^"}\n]+)"?'
                m = re.search(pattern, line)
                if m:
                    device_info[key] = m.group(1).strip()
            if "}" in line and in_device and len(device_info) > 3:
                break
    return device_info


def _detect_usb_linux():
    """通过 lsusb 检测 XVF3800 USB 设备 (Linux)。"""
    result = subprocess.run(
        ["lsusb", "-v"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    device_info = {}
    in_device = False
    for line in result.stdout.splitlines():
        if "XVF3800" in line:
            in_device = True
            device_info["name"] = line.strip()
        if in_device:
            stripped = line.strip()
            for key in [
                "idVendor",
                "idProduct",
                "iProduct",
                "iManufacturer",
                "iSerial",
                "bcdUSB",
            ]:
                if stripped.startswith(key):
                    # lsusb -v 格式: "idVendor  0x2886 Seeed..." 或 "iProduct  2 reSpeaker..."
                    value = stripped.split(None, 1)[-1] if " " in stripped else ""
                    # iProduct/iManufacturer/iSerial 带 descriptor index，去掉前导数字
                    if key.startswith("i") and key[1].isupper():
                        value = re.sub(r"^\d+\s+", "", value)
                    device_info[key] = value.strip()
            if stripped == "" and device_info:
                break
    # 映射到统一的 key 名称
    mapped = {}
    if device_info:
        mapped["name"] = device_info.get("iProduct", device_info.get("name", ""))
        mapped["USB Product Name"] = device_info.get("iProduct", "")
        mapped["USB Vendor Name"] = device_info.get("iManufacturer", "")
        mapped["USB Serial Number"] = device_info.get("iSerial", "")
        mapped["idVendor"] = device_info.get("idVendor", "")
        mapped["idProduct"] = device_info.get("idProduct", "")
        mapped["Device Speed"] = device_info.get("bcdUSB", "")
    return mapped


def detect_usb():
    """检测 XVF3800 USB 设备（自动适配平台）。"""
    if sys.platform == "darwin":
        return _detect_usb_macos()
    elif sys.platform == "linux":
        return _detect_usb_linux()
    else:
        print(f"  不支持的平台: {sys.platform}")
        return {}


def _detect_audio_macos():
    """通过 system_profiler 检测音频设备 (macOS)。"""
    result = subprocess.run(
        ["system_profiler", "SPAudioDataType"],
        capture_output=True,
        text=True,
    )
    lines = result.stdout.splitlines()
    devices = []
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith(("Audio", "Devices")):
            if current:
                devices.append(current)
            current = {"name": stripped.rstrip(":")}
        elif current and ":" in stripped:
            k, v = stripped.split(":", 1)
            current[k.strip()] = v.strip()
    if current:
        devices.append(current)
    return devices


def _detect_audio_linux():
    """通过 /proc/asound 和 arecord/aplay 检测音频设备 (Linux)。"""
    devices = []

    # 优先从 /proc/asound/cards 读取，比 arecord -l 更可靠（PipeWire 环境下也能工作）
    try:
        with open("/proc/asound/cards") as f:
            cards_text = f.read()
        for m in re.finditer(
            r"^\s*(\d+)\s+\[(\w+)\s*\]:\s+(.+?)\n\s+(.+)$",
            cards_text,
            re.MULTILINE,
        ):
            card_num, card_id, card_type, card_desc = m.groups()
            # 读取该声卡的 pcm 设备，区分输入/输出
            import pathlib

            card_dir = pathlib.Path(f"/proc/asound/card{card_num}")
            streams = set()
            for pcm_dir in sorted(card_dir.glob("pcm*")):
                info_file = pcm_dir / "info"
                if info_file.exists():
                    info_text = info_file.read_text()
                    stream_m = re.search(r"stream:\s+(\w+)", info_text)
                    if stream_m:
                        streams.add(stream_m.group(1))
            direction_parts = []
            if "CAPTURE" in streams:
                direction_parts.append("输入")
            if "PLAYBACK" in streams:
                direction_parts.append("输出")
            devices.append({
                "name": card_desc.strip(),
                "方向": "/".join(direction_parts) if direction_parts else "未知",
                "card": f"{card_num} ({card_id})",
                "类型": card_type.strip(),
            })
    except FileNotFoundError:
        pass

    # 如果 /proc/asound 没有结果，回退到 arecord/aplay
    if not devices:
        for cmd, direction in [("arecord", "输入"), ("aplay", "输出")]:
            result = subprocess.run(
                [cmd, "-l"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for line in result.stdout.splitlines():
                m = re.match(
                    r"card\s+(\d+):\s+(\w+)\s+\[(.+?)\],\s+device\s+(\d+):\s+(.+)",
                    line,
                )
                if m:
                    card_num, card_id, card_desc, dev_num, dev_desc = m.groups()
                    devices.append({
                        "name": card_desc.strip(),
                        "方向": direction,
                        "card": f"{card_num} ({card_id})",
                        "device": dev_num,
                        "描述": dev_desc.strip(),
                    })
    return devices


def detect_audio():
    """检测音频设备（自动适配平台）。"""
    if sys.platform == "darwin":
        return _detect_audio_macos()
    elif sys.platform == "linux":
        return _detect_audio_linux()
    else:
        print(f"  不支持的平台: {sys.platform}")
        return []


if __name__ == "__main__":
    print("=== USB 设备检测 ===")
    usb = detect_usb()
    if usb:
        for k, v in usb.items():
            print(f"  {k}: {v}")
    else:
        print("  未检测到 XVF3800 设备！")

    print("\n=== 音频设备检测 ===")
    for dev in detect_audio():
        print(f"\n  [{dev['name']}]")
        for k, v in dev.items():
            if k != "name":
                print(f"    {k}: {v}")
