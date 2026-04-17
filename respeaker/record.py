"""从 ReSpeaker XVF3800 录制音频。

用法:
    uv run record.py              # 录制 5 秒
    uv run record.py --duration 10  # 录制 10 秒
    uv run record.py --list       # 列出所有输入设备
"""

import argparse
import wave

import pyaudio

RATE = 16000
CHANNELS = 2
FORMAT = pyaudio.paInt16
CHUNK = 1024
DEVICE_KEYWORD = "XVF3800"


def find_device(pa: pyaudio.PyAudio) -> int | None:
    """查找 XVF3800 输入设备索引。"""
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if DEVICE_KEYWORD in info["name"] and info["maxInputChannels"] > 0:
            return i
    return None


def list_devices(pa: pyaudio.PyAudio):
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


def record(duration: int, output: str):
    """录制音频并保存为 WAV 文件。"""
    pa = pyaudio.PyAudio()
    try:
        idx = find_device(pa)
        if idx is None:
            print(f"错误: 未找到包含 '{DEVICE_KEYWORD}' 的输入设备")
            list_devices(pa)
            return

        info = pa.get_device_info_by_index(idx)
        print(f"使用设备: [{idx}] {info['name']}")
        print(f"参数: {CHANNELS}ch, {RATE}Hz, {duration}s")

        stream = pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=idx,
            frames_per_buffer=CHUNK,
        )

        print("录制中...")
        frames = []
        for i in range(0, RATE // CHUNK * duration):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)

        stream.stop_stream()
        stream.close()

        with wave.open(output, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(pa.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b"".join(frames))

        print(f"已保存: {output}")
    finally:
        pa.terminate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReSpeaker XVF3800 录音测试")
    parser.add_argument("--duration", type=int, default=5, help="录制时长(秒)")
    parser.add_argument("--output", default="test_record.wav", help="输出文件名")
    parser.add_argument("--list", action="store_true", help="列出所有输入设备")
    args = parser.parse_args()

    pa = pyaudio.PyAudio()
    if args.list:
        list_devices(pa)
        pa.terminate()
    else:
        record(args.duration, args.output)
