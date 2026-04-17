"""降噪效果测试。

先录一段静音环境作为底噪基准，再录一段有人说话的音频，对比信噪比。

用法:
    uv run noise_test.py              # 默认各录 5 秒
    uv run noise_test.py --duration 3  # 各录 3 秒
"""

import argparse
import math
import struct
import wave

import pyaudio

RATE = 16000
CHANNELS = 2
FORMAT = pyaudio.paInt16
CHUNK = 1600  # 100ms
DEVICE_KEYWORD = "XVF3800"


def find_device(pa: pyaudio.PyAudio) -> int | None:
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if DEVICE_KEYWORD in info["name"] and info["maxInputChannels"] > 0:
            return i
    return None


def record_segment(pa: pyaudio.PyAudio, idx: int, duration: int, label: str) -> list[bytes]:
    stream = pa.open(
        format=FORMAT, channels=CHANNELS, rate=RATE,
        input=True, input_device_index=idx,
        frames_per_buffer=CHUNK,
    )
    print(f"  录制中 ({label})...")
    frames = []
    chunks_total = RATE // CHUNK * duration
    for i in range(chunks_total):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
        progress = (i + 1) / chunks_total
        bar = "█" * int(progress * 20)
        print(f"\r  [{bar:<20s}] {progress:.0%}", end="", flush=True)
    print()
    stream.stop_stream()
    stream.close()
    return frames


def calc_rms(frames: list[bytes]) -> float:
    all_data = b"".join(frames)
    samples = struct.unpack(f"<{len(all_data) // 2}h", all_data)
    ch0 = samples[0::CHANNELS]
    return math.sqrt(sum(s * s for s in ch0) / len(ch0))


def calc_rms_chunks(frames: list[bytes]) -> list[float]:
    """计算每个 chunk 的 RMS。"""
    result = []
    for frame in frames:
        samples = struct.unpack(f"<{len(frame) // 2}h", frame)
        ch0 = samples[0::CHANNELS]
        result.append(math.sqrt(sum(s * s for s in ch0) / len(ch0)))
    return result


def save_wav(frames: list[bytes], filename: str, pa: pyaudio.PyAudio):
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(pa.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))


def run_test(duration: int):
    pa = pyaudio.PyAudio()
    try:
        idx = find_device(pa)
        if idx is None:
            print(f"错误: 未找到 {DEVICE_KEYWORD} 设备")
            return

        info = pa.get_device_info_by_index(idx)
        print(f"使用设备: [{idx}] {info['name']}\n")

        # 第一段: 静音底噪
        print(f"第 1 步: 请保持安静 {duration} 秒，录制底噪...")
        input("按回车开始 > ")
        noise_frames = record_segment(pa, idx, duration, "底噪")
        save_wav(noise_frames, "noise_floor.wav", pa)

        # 第二段: 说话
        print(f"\n第 2 步: 请正常说话 {duration} 秒，录制语音...")
        input("按回车开始 > ")
        speech_frames = record_segment(pa, idx, duration, "语音")
        save_wav(speech_frames, "noise_speech.wav", pa)

        # 分析
        noise_rms = calc_rms(noise_frames)
        speech_rms = calc_rms(speech_frames)
        snr = 20 * math.log10(speech_rms / noise_rms) if noise_rms > 0 else float("inf")

        noise_chunks = calc_rms_chunks(noise_frames)
        speech_chunks = calc_rms_chunks(speech_frames)

        print(f"\n=== 降噪分析结果 ===")
        print(f"  底噪 RMS: {noise_rms:.1f} (max={max(noise_chunks):.1f}, min={min(noise_chunks):.1f})")
        print(f"  语音 RMS: {speech_rms:.1f} (max={max(speech_chunks):.1f}, min={min(speech_chunks):.1f})")
        print(f"  信噪比 SNR: {snr:.1f} dB")

        if snr > 30:
            print(f"  结论: 降噪效果优秀，底噪极低")
        elif snr > 20:
            print(f"  结论: 降噪效果良好")
        elif snr > 10:
            print(f"  结论: 降噪效果一般，底噪偏高")
        else:
            print(f"  结论: 降噪效果差，信噪比过低")

        print(f"\n  录音已保存: noise_floor.wav, noise_speech.wav")
    finally:
        pa.terminate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReSpeaker XVF3800 降噪效果测试")
    parser.add_argument("--duration", type=int, default=5, help="每段录制时长秒 (默认 5)")
    args = parser.parse_args()

    run_test(args.duration)
