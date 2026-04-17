"""抓取一帧并保存 color / depth / IR 图像和相机内参。

输出 (默认写入 ./out/):
    color_<ts>.png            RGB
    depth_<ts>.png            16-bit 原始深度 (单位 毫米)
    depth_<ts>_colorized.png  彩色化可视深度
    ir_left_<ts>.png          左红外
    ir_right_<ts>.png         右红外
    intrinsics_<ts>.json      相机内参 / 基线 / 深度单位
"""

import argparse
import json
import sys

import cv2
import numpy as np
import pyrealsense2 as rs

from device import clean_exit, output_dir, require_device, timestamped


def parse_args():
    p = argparse.ArgumentParser(description="RealSense 单帧抓取")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument(
        "--warmup",
        type=int,
        default=30,
        help="丢弃前 N 帧让自动曝光稳定",
    )
    p.add_argument("--no-ir", action="store_true", help="不抓取 IR 流")
    return p.parse_args()


def stream_profile_summary(frames):
    lines = []
    for f in frames:
        prof = f.get_profile().as_video_stream_profile()
        name = str(f.get_profile().stream_type()).split(".")[-1]
        lines.append(f"{name}: {prof.width()}x{prof.height()} @ {prof.fps()}fps")
    return lines


def intrinsics_dict(profile: rs.stream_profile) -> dict:
    intr = profile.as_video_stream_profile().get_intrinsics()
    return {
        "width": intr.width,
        "height": intr.height,
        "fx": intr.fx,
        "fy": intr.fy,
        "ppx": intr.ppx,
        "ppy": intr.ppy,
        "model": str(intr.model).split(".")[-1],
        "coeffs": list(intr.coeffs),
    }


def main():
    args = parse_args()
    _, dev_info = require_device()
    print(f"[设备] {dev_info['name']} (SN: {dev_info['serial']}, FW: {dev_info['firmware']})")

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    config.enable_stream(rs.stream.depth, args.width, args.height, rs.format.z16, args.fps)
    if not args.no_ir:
        config.enable_stream(rs.stream.infrared, 1, args.width, args.height, rs.format.y8, args.fps)
        config.enable_stream(rs.stream.infrared, 2, args.width, args.height, rs.format.y8, args.fps)

    try:
        profile = pipeline.start(config)
    except RuntimeError as e:
        print(f"[错误] 无法开启指定流配置: {e}", file=sys.stderr)
        print("  尝试用 detect.py 查看设备支持的分辨率和帧率。", file=sys.stderr)
        sys.exit(1)

    try:
        # 丢弃预热帧
        for _ in range(args.warmup):
            pipeline.wait_for_frames()

        frames = pipeline.wait_for_frames()
        color = frames.get_color_frame()
        depth = frames.get_depth_frame()
        ir1 = frames.get_infrared_frame(1) if not args.no_ir else None
        ir2 = frames.get_infrared_frame(2) if not args.no_ir else None

        if not color or not depth:
            print("[错误] 未收到 color/depth 帧", file=sys.stderr)
            sys.exit(1)

        depth_sensor = profile.get_device().first_depth_sensor()
        depth_scale = depth_sensor.get_depth_scale()  # 米/单位，D4 系列通常 0.001

        out = output_dir()
        ts = timestamped("", "").strip("_.")

        color_img = np.asanyarray(color.get_data())
        depth_img = np.asanyarray(depth.get_data())  # uint16

        color_path = out / f"color_{ts}.png"
        depth_path = out / f"depth_{ts}.png"
        depth_color_path = out / f"depth_{ts}_colorized.png"

        cv2.imwrite(str(color_path), color_img)
        cv2.imwrite(str(depth_path), depth_img)  # 16-bit 保留原始值

        colorizer = rs.colorizer()
        colorized = colorizer.colorize(depth)
        cv2.imwrite(str(depth_color_path), np.asanyarray(colorized.get_data()))

        saved = [color_path.name, depth_path.name, depth_color_path.name]

        if ir1 and ir2:
            ir1_path = out / f"ir_left_{ts}.png"
            ir2_path = out / f"ir_right_{ts}.png"
            cv2.imwrite(str(ir1_path), np.asanyarray(ir1.get_data()))
            cv2.imwrite(str(ir2_path), np.asanyarray(ir2.get_data()))
            saved += [ir1_path.name, ir2_path.name]

        # 内参 + 外参
        color_profile = profile.get_stream(rs.stream.color)
        depth_profile = profile.get_stream(rs.stream.depth)
        extr = depth_profile.get_extrinsics_to(color_profile)

        # 中心像素深度读数，快速验证
        h, w = depth_img.shape
        cx, cy = w // 2, h // 2
        center_raw = int(depth_img[cy, cx])
        center_m = center_raw * depth_scale

        meta = {
            "device": dev_info,
            "depth_scale_m_per_unit": depth_scale,
            "depth_intrinsics": intrinsics_dict(depth_profile),
            "color_intrinsics": intrinsics_dict(color_profile),
            "depth_to_color_extrinsics": {
                "rotation": list(extr.rotation),
                "translation": list(extr.translation),
            },
            "center_pixel": {
                "xy": [cx, cy],
                "raw": center_raw,
                "meters": center_m,
            },
            "profiles": stream_profile_summary([color, depth] + ([ir1, ir2] if ir1 else [])),
        }
        meta_path = out / f"intrinsics_{ts}.json"
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        saved.append(meta_path.name)

        print(f"\n[抓帧成功] 输出目录: {out}")
        for name in saved:
            print(f"  - {name}")
        print(f"\n中心像素({cx},{cy}) 深度: {center_raw} 单位 = {center_m*1000:.1f} mm")

    finally:
        pipeline.stop()


if __name__ == "__main__":
    main()
    clean_exit(0)
