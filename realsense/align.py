"""测试 depth→color 对齐 (rs.align)。

保存三组对照图:
    color_raw.png                原始彩色
    depth_raw_colorized.png      原始深度 (深度相机视角)
    depth_aligned_colorized.png  对齐到彩色画面的深度
    overlay_raw.png              彩色 + 原始深度叠加 (不对齐)
    overlay_aligned.png          彩色 + 对齐深度叠加 (应与物体边缘重合)
"""

import argparse
import sys

import cv2
import numpy as np
import pyrealsense2 as rs

from device import clean_exit, output_dir, require_device, timestamped


def parse_args():
    p = argparse.ArgumentParser(description="RealSense 深度对齐测试")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--warmup", type=int, default=30)
    p.add_argument("--alpha", type=float, default=0.5, help="深度叠加透明度 (0~1)")
    return p.parse_args()


def colorize(depth_frame: rs.depth_frame, colorizer: rs.colorizer) -> np.ndarray:
    return np.asanyarray(colorizer.colorize(depth_frame).get_data())


def overlay(color_bgr: np.ndarray, depth_colored: np.ndarray, alpha: float) -> np.ndarray:
    if color_bgr.shape[:2] != depth_colored.shape[:2]:
        depth_colored = cv2.resize(
            depth_colored, (color_bgr.shape[1], color_bgr.shape[0])
        )
    return cv2.addWeighted(color_bgr, 1 - alpha, depth_colored, alpha, 0)


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
        print(f"[错误] 启动失败: {e}", file=sys.stderr)
        sys.exit(1)

    align = rs.align(rs.stream.color)
    colorizer = rs.colorizer()
    out = output_dir("align")
    ts = timestamped("", "").strip("_.")

    try:
        for _ in range(args.warmup):
            pipeline.wait_for_frames()

        frames = pipeline.wait_for_frames()
        color = frames.get_color_frame()
        depth = frames.get_depth_frame()
        if not color or not depth:
            print("[错误] 未收到帧", file=sys.stderr)
            sys.exit(1)

        color_img = np.asanyarray(color.get_data())
        depth_raw_color = colorize(depth, colorizer)

        aligned = align.process(frames)
        color_a = aligned.get_color_frame()
        depth_a = aligned.get_depth_frame()
        if not color_a or not depth_a:
            print("[错误] 对齐后未收到帧", file=sys.stderr)
            sys.exit(1)

        color_a_img = np.asanyarray(color_a.get_data())
        depth_a_color = colorize(depth_a, colorizer)

        # overlay 前的原始对不齐 (强行同尺寸以做可视化)
        overlay_raw = overlay(color_img, depth_raw_color, args.alpha)
        overlay_aligned = overlay(color_a_img, depth_a_color, args.alpha)

        files = {
            f"color_raw_{ts}.png": color_img,
            f"depth_raw_colorized_{ts}.png": depth_raw_color,
            f"depth_aligned_colorized_{ts}.png": depth_a_color,
            f"overlay_raw_{ts}.png": overlay_raw,
            f"overlay_aligned_{ts}.png": overlay_aligned,
        }
        for name, img in files.items():
            cv2.imwrite(str(out / name), img)

        # 简单量化: 对齐前后，深度图有效像素覆盖的区域差异
        depth_raw_arr = np.asanyarray(depth.get_data())
        depth_a_arr = np.asanyarray(depth_a.get_data())
        raw_valid = float((depth_raw_arr > 0).mean())
        a_valid = float((depth_a_arr > 0).mean())

        print(f"\n[输出] {out}")
        for name in files:
            print(f"  - {name}")
        print(f"\n原始深度  尺寸: {depth_raw_arr.shape}, 有效像素: {raw_valid*100:.1f}%")
        print(f"对齐深度  尺寸: {depth_a_arr.shape}, 有效像素: {a_valid*100:.1f}%")
        print("\n查看 overlay_aligned_*.png: 深度色带应贴合物体边缘；")
        print("对比 overlay_raw_*.png: 未对齐时深度会整体偏移或尺度不同。")

    finally:
        pipeline.stop()


if __name__ == "__main__":
    main()
    clean_exit(0)
