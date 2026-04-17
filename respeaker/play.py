"""通过 ReSpeaker XVF3800 播放音频。

用法:
    uv run play.py                # 播放 1000Hz 测试音 3 秒
    uv run play.py test.wav       # 播放 WAV 文件
    uv run play.py --freq 440     # 播放 440Hz
    uv run play.py --duration 5   # 播放 5 秒
    uv run play.py --volume 0.5   # 50% 音量
    uv run play.py --list         # 列出所有输出设备
"""

import argparse
import math
import struct
import wave

import pyaudio

import device

RATE = 16000
CHANNELS = 2
FORMAT = pyaudio.paInt16
CHUNK = 1024


def generate_tone(freq: float, duration: int, volume: float) -> bytes:
    """生成正弦波测试音。"""
    n_samples = RATE * duration
    samples = []
    for i in range(n_samples):
        val = volume * 32767 * math.sin(2 * math.pi * freq * i / RATE)
        sample = int(val)
        # 双声道，左右相同
        samples.append(struct.pack("<hh", sample, sample))
    return b"".join(samples)


def adjust_volume(data: bytes, volume: float, sampwidth: int) -> bytes:
    """调整 PCM 数据音量。"""
    if volume == 1.0:
        return data
    fmt = "<" + {1: "b", 2: "h", 4: "i"}[sampwidth] * (len(data) // sampwidth)
    samples = struct.unpack(fmt, data)
    adjusted = [int(max(-32768, min(32767, s * volume)) if sampwidth == 2
                     else s * volume) for s in samples]
    return struct.pack(fmt, *adjusted)


def play_wav(filepath: str, volume: float = 1.0):
    """播放 WAV 文件。"""
    pa = pyaudio.PyAudio()
    try:
        pa, idx = device.find_output(pa)
        if idx is None:
            print("错误: 未找到 XVF3800 输出设备")
            device.list_outputs(pa)
            return

        with wave.open(filepath, "rb") as wf:
            info = pa.get_device_info_by_index(idx)
            print(f"使用设备: [{idx}] {info['name']}")
            vol_str = f", 音量 {volume*100:.0f}%" if volume != 1.0 else ""
            print(
                f"文件: {filepath} "
                f"({wf.getnchannels()}ch, {wf.getframerate()}Hz, "
                f"{wf.getnframes() / wf.getframerate():.1f}s{vol_str})"
            )

            stream = pa.open(
                format=pa.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True,
                output_device_index=idx,
                frames_per_buffer=CHUNK,
            )

            print("播放中...")
            while True:
                data = wf.readframes(CHUNK)
                if not data:
                    break
                stream.write(adjust_volume(data, volume, wf.getsampwidth()))

            stream.stop_stream()
            stream.close()
        print("播放完成")
    finally:
        pa.terminate()


def play_tone(freq: float, duration: int, volume: float):
    """播放生成的测试音。"""
    pa = pyaudio.PyAudio()
    try:
        pa, idx = device.find_output(pa)
        if idx is None:
            print("错误: 未找到 XVF3800 输出设备")
            device.list_outputs(pa)
            return

        info = pa.get_device_info_by_index(idx)
        print(f"使用设备: [{idx}] {info['name']}")
        print(f"参数: {CHANNELS}ch, {RATE}Hz, {freq}Hz, 音量 {volume*100:.0f}%")

        stream = pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            output=True,
            output_device_index=idx,
            frames_per_buffer=CHUNK,
        )

        print("播放中...")
        data = generate_tone(freq, duration, volume)
        stream.write(data)

        stream.stop_stream()
        stream.close()
        print("播放完成")
    finally:
        pa.terminate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReSpeaker XVF3800 播放测试")
    parser.add_argument("file", nargs="?", help="WAV 文件路径 (不指定则播放测试音)")
    parser.add_argument("--freq", type=float, default=1000, help="频率 Hz (默认 1000)")
    parser.add_argument("--duration", type=int, default=3, help="时长秒 (默认 3)")
    parser.add_argument("--volume", type=float, default=0.8, help="音量倍数 (默认 0.8, >1.0 为放大带削波)")
    parser.add_argument("--list", action="store_true", help="列出所有输出设备")
    args = parser.parse_args()

    if args.list:
        pa = pyaudio.PyAudio()
        device.list_outputs(pa)
        pa.terminate()
    elif args.file:
        play_wav(args.file, args.volume)
    else:
        play_tone(args.freq, args.duration, args.volume)
