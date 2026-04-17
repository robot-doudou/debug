"""XVF3800 设备查找工具。

在 macOS 上通过 PyAudio 设备名匹配。
在 Linux 上先尝试名称匹配，失败则通过 /proc/asound 定位声卡号，
生成临时 ALSA 配置绕过 PipeWire 直接访问硬件设备。

注意: Linux 上需要用户在 audio 组中，或已配置 udev 规则。
"""

import os
import re
import sys
import tempfile

import pyaudio

DEVICE_KEYWORD = "XVF3800"

_alsa_config_file = None  # 保持临时文件引用防止被回收


def _find_by_name(pa: pyaudio.PyAudio, direction: str) -> int | None:
    """通过设备名关键字查找 (macOS / 原生 ALSA)。"""
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if DEVICE_KEYWORD not in info["name"]:
            continue
        if direction == "input" and info["maxInputChannels"] > 0:
            return i
        if direction == "output" and info["maxOutputChannels"] > 0:
            return i
    return None


def _find_card_from_proc() -> int | None:
    """从 /proc/asound/cards 查找 XVF3800 声卡号 (Linux)。"""
    try:
        with open("/proc/asound/cards") as f:
            for line in f:
                if DEVICE_KEYWORD in line:
                    m = re.match(r"\s*(\d+)\s+", line)
                    if m:
                        return int(m.group(1))
    except FileNotFoundError:
        pass
    return None


def _check_audio_permission(card_num: int) -> bool:
    """检查当前用户是否有权限访问声卡设备。"""
    dev_path = f"/dev/snd/pcmC{card_num}D0c"
    return os.access(dev_path, os.R_OK | os.W_OK)


def _set_mixer_max(card_num: int):
    """将 XVF3800 的 PCM Playback / Headset Capture 音量设为最大。

    XVF3800 的 USB mixer 默认 PCM 音量是 62% (-23dB)，Linux 下需手动拉满，
    否则录制/播放声音会显著偏小（macOS 默认自动拉满）。
    """
    import subprocess
    for ctrl in ("PCM", "Headset"):
        subprocess.run(
            ["amixer", "-c", str(card_num), "sset", ctrl, "100%"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _reinit_with_alsa_hw(card_num: int) -> pyaudio.PyAudio:
    """生成临时 ALSA 配置，绕过 PipeWire 直接访问 hw 设备。"""
    global _alsa_config_file

    alsa_conf = f"""\
pcm.xvf3800 {{
    type plug
    slave {{
        pcm "hw:{card_num},0"
    }}
}}
pcm.!default xvf3800
ctl.!default {{
    type hw
    card {card_num}
}}
"""
    _alsa_config_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".conf", prefix="asound_xvf_", delete=False
    )
    _alsa_config_file.write(alsa_conf)
    _alsa_config_file.flush()
    os.environ["ALSA_CONFIG_PATH"] = _alsa_config_file.name
    return pyaudio.PyAudio()


def _init_linux(pa: pyaudio.PyAudio) -> pyaudio.PyAudio:
    """Linux 上尝试定位 XVF3800 并重新初始化 PyAudio。

    返回可能重新初始化的 pa 实例。
    """
    card = _find_card_from_proc()
    if card is None:
        return pa

    if not _check_audio_permission(card):
        try:
            in_audio = "audio" in os.popen("groups").read()
        except Exception:
            in_audio = False
        print(f"警告: 没有访问声卡 {card} 的权限")
        if not in_audio:
            print(f"  请将用户加入 audio 组: sudo usermod -aG audio {os.environ.get('USER', 'USERNAME')}")
            print(f"  然后重新登录生效")
        return pa

    _set_mixer_max(card)
    pa.terminate()
    return _reinit_with_alsa_hw(card)


def _find_default(pa: pyaudio.PyAudio, direction: str) -> int | None:
    """查找 default 设备作为后备。"""
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if direction == "input" and info["maxInputChannels"] > 0:
            return i
        if direction == "output" and info["maxOutputChannels"] > 0:
            return i
    return None


def _linux_preflight():
    """Linux 上查找声卡并修复 USB mixer 音量 (XVF3800 默认 PCM 播放 -23dB)。"""
    card = _find_card_from_proc()
    if card is not None and _check_audio_permission(card):
        _set_mixer_max(card)
    return card


def find_input(pa: pyaudio.PyAudio) -> tuple[pyaudio.PyAudio, int | None]:
    """查找 XVF3800 输入设备。返回 (pa, device_index)，pa 可能被重新初始化。"""
    if sys.platform == "linux":
        _linux_preflight()

    idx = _find_by_name(pa, "input")
    if idx is not None:
        return pa, idx

    if sys.platform == "linux":
        pa = _init_linux(pa)
        idx = _find_by_name(pa, "input") or _find_default(pa, "input")
        if idx is not None:
            return pa, idx

    return pa, None


def find_output(pa: pyaudio.PyAudio) -> tuple[pyaudio.PyAudio, int | None]:
    """查找 XVF3800 输出设备。返回 (pa, device_index)，pa 可能被重新初始化。"""
    if sys.platform == "linux":
        _linux_preflight()

    idx = _find_by_name(pa, "output")
    if idx is not None:
        return pa, idx

    if sys.platform == "linux":
        pa = _init_linux(pa)
        idx = _find_by_name(pa, "output") or _find_default(pa, "output")
        if idx is not None:
            return pa, idx

    return pa, None


def find_both(pa: pyaudio.PyAudio) -> tuple[pyaudio.PyAudio, int | None, int | None]:
    """同时查找输入和输出设备。返回 (pa, input_index, output_index)。"""
    if sys.platform == "linux":
        _linux_preflight()

    in_idx = _find_by_name(pa, "input")
    out_idx = _find_by_name(pa, "output")
    if in_idx is not None and out_idx is not None:
        return pa, in_idx, out_idx

    if sys.platform == "linux":
        pa = _init_linux(pa)
        in_idx = _find_by_name(pa, "input") or _find_default(pa, "input")
        out_idx = _find_by_name(pa, "output") or _find_default(pa, "output")

    return pa, in_idx, out_idx


def list_inputs(pa: pyaudio.PyAudio):
    """列出所有输入设备。"""
    print("可用输入设备:")
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            marker = " <-- XVF3800" if DEVICE_KEYWORD in info["name"] else ""
            print(
                f"  [{i}] {info['name']} "
                f"(channels={info['maxInputChannels']}, "
                f"rate={int(info['defaultSampleRate'])}){marker}"
            )


def list_outputs(pa: pyaudio.PyAudio):
    """列出所有输出设备。"""
    print("可用输出设备:")
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxOutputChannels"] > 0:
            marker = " <-- XVF3800" if DEVICE_KEYWORD in info["name"] else ""
            print(
                f"  [{i}] {info['name']} "
                f"(channels={info['maxOutputChannels']}, "
                f"rate={int(info['defaultSampleRate'])}){marker}"
            )
