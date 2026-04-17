"""Intel RealSense D4xx 固件升级 (纯 pyrealsense2 实现)。

不依赖 rs-fw-update / apt 包。流程:
    1. check_firmware_compatibility(fw)  校验固件匹配
    2. 可选 create_flash_backup           备份当前固件到 out/
    3. updatable.enter_update_state()    设备进入 DFU, USB 重新枚举
    4. update_device.update(fw, cb)       烧录
    5. 等待设备回到普通模式，打印新版本

下载固件 (D435i 推荐 5.17.0.10):
    https://dev.realsenseai.com/docs/firmware-releases-d400/
"""

import argparse
import sys
import time
from pathlib import Path

import pyrealsense2 as rs

from device import clean_exit, output_dir


def _dev_summary(d: rs.device) -> str:
    if d.is_update_device():
        return f"{d.get_info(rs.camera_info.name)} [DFU/recovery]"
    try:
        sn = d.get_info(rs.camera_info.serial_number)
        fw = d.get_info(rs.camera_info.firmware_version)
        return f"{d.get_info(rs.camera_info.name)} SN={sn} FW={fw}"
    except Exception as e:
        return f"{d.get_info(rs.camera_info.name)} (info err: {e})"


def list_devices() -> list[rs.device]:
    ctx = rs.context()
    devs = list(ctx.query_devices())
    if not devs:
        print("  未发现设备")
    for d in devs:
        print(f"  - {_dev_summary(d)}")
    return devs


def _find_by_serial(serial: str) -> rs.device | None:
    for d in rs.context().query_devices():
        try:
            if d.get_info(rs.camera_info.serial_number) == serial:
                return d
        except Exception:
            pass
    return None


def _wait_dfu(timeout: float = 30.0) -> rs.device | None:
    """等任意 update_device 出现。单设备场景下够用。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for d in rs.context().query_devices():
            if d.is_update_device():
                return d
        time.sleep(0.3)
    return None


def _wait_normal(serial: str, timeout: float = 45.0) -> rs.device | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for d in rs.context().query_devices():
            if d.is_update_device():
                continue
            try:
                if d.get_info(rs.camera_info.serial_number) == serial:
                    return d
            except Exception:
                pass
        time.sleep(0.5)
    return None


def _progress(label: str):
    def cb(pct):
        p = pct * 100 if pct <= 1.0 else float(pct)
        end = "\n" if p >= 99.9 else ""
        print(f"\r  {label}: {p:5.1f}%", end=end, flush=True)

    return cb


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


def main():
    p = argparse.ArgumentParser(description="RealSense D4xx 固件升级")
    p.add_argument("firmware", nargs="?", help="签名固件文件 Signed_Image_UVC_*.bin")
    p.add_argument("-s", "--serial", help="多设备时指定目标 SN")
    p.add_argument("--backup", action="store_true", help="升级前备份当前固件到 out/")
    p.add_argument("-y", "--yes", action="store_true", help="跳过所有确认")
    p.add_argument("-l", "--list", action="store_true", help="仅列出设备")
    args = p.parse_args()

    print("=== 当前设备 ===")
    devs = list_devices()
    print()

    if args.list or not args.firmware:
        if not args.firmware:
            print("用法: uv run fw_update.py <Signed_Image_UVC_*.bin> [-s <SN>] [--backup] [-y]")
            print("下载: https://dev.realsenseai.com/docs/firmware-releases-d400/")
            print("      D435i 推荐 Signed_Image_UVC_5_17_0_10.bin")
        return

    # 选目标设备
    if args.serial:
        target = _find_by_serial(args.serial)
        if target is None:
            print(f"[错误] 找不到 SN={args.serial}", file=sys.stderr)
            sys.exit(1)
    else:
        normal = [d for d in devs if not d.is_update_device()]
        if len(normal) == 0:
            # 允许直接面向 recovery 模式的设备 (上次失败留下的)
            rec = [d for d in devs if d.is_update_device()]
            if len(rec) != 1:
                print("[错误] 没有可升级的普通设备，也不是唯一的 recovery 设备", file=sys.stderr)
                sys.exit(1)
            target = rec[0]
        elif len(normal) > 1:
            print("[错误] 多设备时需用 -s 指定 SN", file=sys.stderr)
            sys.exit(2)
        else:
            target = normal[0]

    # 读固件
    fw_path = Path(args.firmware)
    if not fw_path.is_file():
        print(f"[错误] 固件文件不存在: {fw_path}", file=sys.stderr)
        sys.exit(1)
    if not fw_path.name.startswith("Signed_Image_UVC"):
        print(f"[警告] 文件名不是 Signed_Image_UVC_*.bin: {fw_path.name}")
        if not _confirm("继续?", args.yes):
            sys.exit(0)
    fw_bytes = fw_path.read_bytes()
    # pyrealsense2 的 update() / check_firmware_compatibility() / update_unsigned()
    # 都要 list[int], 不接受 bytes/bytearray。转一次复用。
    fw = list(fw_bytes)
    print(f"固件:   {fw_path} ({len(fw_bytes)} bytes)")
    print(f"目标:   {_dev_summary(target)}")

    # 如果设备已经在 recovery 模式，跳过 DFU 步骤
    if target.is_update_device():
        print("\n[DFU] 设备已处于 recovery 模式 (可能是上次升级中断)")
        if not _confirm("直接写入固件恢复设备?", args.yes):
            print("已取消")
            return
        serial_for_wait = None
        dfu_dev = target
    else:
        updatable = target.as_updatable()
        serial_for_wait = target.get_info(rs.camera_info.serial_number)

        # 兼容性检查
        try:
            compat = updatable.check_firmware_compatibility(fw)
            if compat:
                print("兼容性: OK")
            else:
                print("[警告] check_firmware_compatibility 返回 False")
                if not _confirm("仍然继续?", args.yes):
                    sys.exit(0)
        except Exception as e:
            print(f"[警告] 兼容性检查失败 ({e})，跳过")

        print()
        if not _confirm("确认升级? 过程 1-2 分钟，不要拔线", args.yes):
            print("已取消")
            return

        # 可选备份
        if args.backup:
            print("\n[备份] 读取当前固件...")
            try:
                backup_bytes = updatable.create_flash_backup(_progress("backup"))
                backup_path = output_dir() / f"fw_backup_{serial_for_wait}_{int(time.time())}.bin"
                backup_path.write_bytes(bytes(backup_bytes))
                print(f"[备份] 已保存: {backup_path}")
            except Exception as e:
                print(f"[警告] 备份失败: {e}")
                if not _confirm("不备份继续?", args.yes):
                    sys.exit(1)

        # 进入 DFU
        print("\n[DFU] 进入更新模式, 设备将重新枚举...")
        updatable.enter_update_state()
        dfu_dev = _wait_dfu(timeout=30.0)
        if dfu_dev is None:
            print("[错误] 30s 内未发现 DFU 设备，拔插后重试", file=sys.stderr)
            sys.exit(1)
        print(f"[DFU] 已连接: {_dev_summary(dfu_dev)}")

    # 写入
    print("\n[写入] 开始烧录...")
    update_dev = dfu_dev.as_update_device()
    update_dev.update(fw, _progress("flash"))
    print("[写入] 完成")

    # 等待回普通模式
    if serial_for_wait:
        print("\n[等待] 设备回到普通模式...")
        final = _wait_normal(serial_for_wait, timeout=45.0)
        if final is None:
            print("[警告] 45s 内未检测到设备回到普通模式，可能需要拔插")
        else:
            new_fw = final.get_info(rs.camera_info.firmware_version)
            print(f"[完成] 新固件版本: {new_fw}")
    else:
        print("\n[完成] 从 recovery 模式升级完毕，拔插设备确认新版本")


if __name__ == "__main__":
    main()
    clean_exit(0)
