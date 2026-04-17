"""导出 color-depth 融合点云为 PLY 文件。

默认: 保存 ./out/pointcloud/<ts>.ply 并打印统计信息
--view: 若安装了 open3d 则弹出 3D 窗口预览
"""

import argparse
import sys

import numpy as np
import pyrealsense2 as rs

from device import clean_exit, has_display, output_dir, require_device, timestamped


def parse_args():
    p = argparse.ArgumentParser(description="RealSense 点云导出")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--warmup", type=int, default=30)
    p.add_argument("--view", action="store_true", help="如安装 open3d 则预览")
    return p.parse_args()


def try_view_ply(ply_path: str):
    try:
        import open3d as o3d
    except ImportError:
        print("  [跳过预览] 未安装 open3d  (uv add open3d 可启用)")
        return
    if not has_display():
        print("  [跳过预览] 无图形会话")
        return
    pcd = o3d.io.read_point_cloud(ply_path)
    print(f"  Open3D 加载: {pcd}")
    o3d.visualization.draw_geometries([pcd])


def main():
    args = parse_args()
    _, dev_info = require_device()
    print(f"[设备] {dev_info['name']} (SN: {dev_info['serial']})")

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    config.enable_stream(rs.stream.depth, args.width, args.height, rs.format.z16, args.fps)

    try:
        profile = pipeline.start(config)
    except RuntimeError as e:
        print(f"[错误] 启动失败: {e}", file=sys.stderr)
        sys.exit(1)

    depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
    align = rs.align(rs.stream.color)
    pc = rs.pointcloud()

    try:
        for _ in range(args.warmup):
            pipeline.wait_for_frames()

        frames = align.process(pipeline.wait_for_frames())
        color = frames.get_color_frame()
        depth = frames.get_depth_frame()
        if not color or not depth:
            print("[错误] 未收到对齐帧", file=sys.stderr)
            sys.exit(1)

        pc.map_to(color)
        points = pc.calculate(depth)

        out = output_dir("pointcloud")
        ts = timestamped("", "").strip("_.")
        ply_path = out / f"pointcloud_{ts}.ply"
        points.export_to_ply(str(ply_path), color)

        # 统计点云
        vtx = np.asanyarray(points.get_vertices()).view(np.float32).reshape(-1, 3)
        valid = vtx[vtx[:, 2] > 0]
        depth_arr = np.asanyarray(depth.get_data()) * depth_scale  # 米

        print(f"\n[输出] {ply_path}")
        print(f"  总顶点数   : {len(vtx):,}")
        print(f"  有效点 (z>0): {len(valid):,}  ({len(valid)/max(len(vtx),1)*100:.1f}%)")
        if len(valid) > 0:
            print(f"  Z 范围     : {valid[:,2].min():.3f} ~ {valid[:,2].max():.3f} m")
            print(f"  Z 中位数   : {np.median(valid[:,2]):.3f} m")

        valid_depth = depth_arr[depth_arr > 0]
        if len(valid_depth) > 0:
            print(f"  深度有效率 : {len(valid_depth)/depth_arr.size*100:.1f}%")

        if args.view:
            print("\n[预览]")
            try_view_ply(str(ply_path))
        else:
            print("\n提示: 用 `uv run pointcloud.py --view` (需 open3d) 可在 3D 窗口查看。")
            print("      或用 MeshLab / CloudCompare 打开 PLY。")

    finally:
        pipeline.stop()


if __name__ == "__main__":
    main()
    clean_exit(0)
