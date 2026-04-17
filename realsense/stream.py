"""实时查看 color + depth 流。

- 有图形会话 (macOS / Linux 带 DISPLAY) 时弹出 OpenCV 窗口并排显示
- 否则进入 headless 模式，统计 FPS 并定期保存样本帧到 ./out/stream_frames/
"""

import argparse
import sys
import time

import cv2
import numpy as np
import pyrealsense2 as rs

from device import clean_exit, has_display, output_dir, require_device, timestamped


def parse_args():
    p = argparse.ArgumentParser(description="RealSense 实时流预览")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--duration", type=float, default=30.0, help="headless 模式运行时长(秒)")
    p.add_argument("--sample-interval", type=float, default=5.0, help="headless 模式保存样本帧的间隔(秒)")
    p.add_argument("--headless", action="store_true", help="强制 headless 模式")
    return p.parse_args()


def run_gui(pipeline: rs.pipeline, colorizer: rs.colorizer):
    """显示 color | colorized-depth 并排预览，按 q 或 ESC 退出，s 保存当前帧。"""
    window = "RealSense (q/ESC=退出, s=保存当前帧)"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)

    t0 = time.time()
    frame_count = 0
    last_fps_report = t0

    try:
        while True:
            frames = pipeline.wait_for_frames()
            color = frames.get_color_frame()
            depth = frames.get_depth_frame()
            if not color or not depth:
                continue

            color_img = np.asanyarray(color.get_data())
            depth_colored = np.asanyarray(colorizer.colorize(depth).get_data())

            # 对齐两张图的高度再水平拼接
            if color_img.shape[:2] != depth_colored.shape[:2]:
                depth_colored = cv2.resize(depth_colored, (color_img.shape[1], color_img.shape[0]))
            combined = np.hstack((color_img, depth_colored))

            # FPS 覆盖文字
            frame_count += 1
            now = time.time()
            fps = frame_count / (now - t0)
            cv2.putText(
                combined,
                f"{fps:5.1f} fps",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )

            cv2.imshow(window, combined)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("s"):
                out = output_dir("stream_frames")
                ts = timestamped("", "").strip("_.")
                cv2.imwrite(str(out / f"color_{ts}.png"), color_img)
                cv2.imwrite(str(out / f"depth_{ts}.png"), np.asanyarray(depth.get_data()))
                cv2.imwrite(str(out / f"depth_{ts}_colorized.png"), depth_colored)
                print(f"[保存] {out}/*_{ts}.png")

            if now - last_fps_report > 2.0:
                print(f"[FPS] 实测 {fps:.2f}")
                last_fps_report = now
    finally:
        cv2.destroyAllWindows()


def run_headless(
    pipeline: rs.pipeline,
    colorizer: rs.colorizer,
    duration: float,
    sample_interval: float,
):
    """无 GUI: 计时采集 FPS，周期性保存样本帧。"""
    out = output_dir("stream_frames")
    print(f"[headless] 运行 {duration:.0f}s，样本帧保存到 {out}")

    t0 = time.time()
    last_sample = t0
    frame_count = 0
    last_fps_report = t0
    saved = 0

    while True:
        frames = pipeline.wait_for_frames()
        color = frames.get_color_frame()
        depth = frames.get_depth_frame()
        if not color or not depth:
            continue

        frame_count += 1
        now = time.time()

        if now - last_fps_report > 2.0:
            fps = frame_count / (now - t0)
            print(f"  t={now-t0:5.1f}s  frames={frame_count}  fps={fps:.2f}")
            last_fps_report = now

        if now - last_sample >= sample_interval:
            ts = timestamped("", "").strip("_.")
            cv2.imwrite(str(out / f"color_{ts}.png"), np.asanyarray(color.get_data()))
            cv2.imwrite(
                str(out / f"depth_{ts}_colorized.png"),
                np.asanyarray(colorizer.colorize(depth).get_data()),
            )
            saved += 1
            last_sample = now

        if now - t0 >= duration:
            break

    total = time.time() - t0
    print(f"\n[完成] 总帧数 {frame_count}, 平均 FPS {frame_count/total:.2f}, 保存样本 {saved} 帧")


def main():
    args = parse_args()
    _, dev_info = require_device()
    print(f"[设备] {dev_info['name']} (SN: {dev_info['serial']})")

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    config.enable_stream(rs.stream.depth, args.width, args.height, rs.format.z16, args.fps)

    try:
        pipeline.start(config)
    except RuntimeError as e:
        print(f"[错误] 无法开启流: {e}", file=sys.stderr)
        sys.exit(1)

    colorizer = rs.colorizer()
    use_gui = has_display() and not args.headless

    try:
        if use_gui:
            print("[GUI] OpenCV 窗口已打开。按 q/ESC 退出，s 保存当前帧。")
            run_gui(pipeline, colorizer)
        else:
            if args.headless:
                reason = "--headless 已指定"
            else:
                reason = "未检测到图形会话 (DISPLAY/WAYLAND_DISPLAY)"
            print(f"[headless] {reason}")
            run_headless(pipeline, colorizer, args.duration, args.sample_interval)
    finally:
        pipeline.stop()


if __name__ == "__main__":
    main()
    clean_exit(0)
