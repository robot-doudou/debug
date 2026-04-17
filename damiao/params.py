"""达妙电机参数寄存器读写 + 改 ID + 零点 + 清错 + 保存到 Flash。

敏感操作:
  --change-id: 改完立即失联, 必须拔电重上; 需要 --confirm-id-change flag
  --save:      写入 Flash 永久生效
"""
from __future__ import annotations

import argparse
import sys

from device import DMMotor, open_bus

REG_TABLE = {
    # reg_id: (name, is_float)
    0x00: ("UV_Value", True),
    0x01: ("KT_Value", True),
    0x02: ("OT_Value", True),
    0x03: ("OC_Value", True),
    0x07: ("PMAX", True),
    0x08: ("VMAX", True),
    0x09: ("TMAX", True),
    0x0A: ("I_BW", True),
    0x10: ("CAN_ID", False),
    0x11: ("MST_ID", False),
    0x12: ("TIMEOUT", True),
    0x13: ("CTRL_MODE", False),   # 1=MIT, 2=POS_VEL, 3=SPEED
    0x17: ("KP_APR", True),
    0x18: ("KI_APR", True),
    0x19: ("KP_ASR", True),
    0x1A: ("KI_ASR", True),
}


def parse_reg(s: str) -> int:
    """接受 reg_id (0x10) 或名字 (CAN_ID)。"""
    try:
        return int(s, 0)
    except ValueError:
        pass
    for reg_id, (name, _) in REG_TABLE.items():
        if name.upper() == s.upper():
            return reg_id
    raise argparse.ArgumentTypeError(f"未知寄存器: {s}")


def fmt_value(reg_id: int, value: float) -> str:
    if reg_id in REG_TABLE and not REG_TABLE[reg_id][1]:
        return f"{int(value)} (0x{int(value):02X})"
    return f"{value:.6f}"


def main():
    p = argparse.ArgumentParser(description="达妙电机参数读写")
    p.add_argument("--motor-id", type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--master-id", type=lambda x: int(x, 0), default=0x11)

    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="列出可识别寄存器")
    g.add_argument("--get", type=parse_reg, metavar="REG",
                   help="读寄存器 (ID 或名字)")
    g.add_argument("--set", nargs=2, metavar=("REG", "VAL"),
                   help="写寄存器")
    g.add_argument("--set-zero", action="store_true", help="设置当前位置为零点")
    g.add_argument("--clear-error", action="store_true", help="清除错误")
    g.add_argument("--save", action="store_true", help="保存参数到 Flash")
    g.add_argument("--change-id", nargs=2, type=lambda x: int(x, 0),
                   metavar=("NEW_CAN_ID", "NEW_MST_ID"),
                   help="改电机 ID 和 master ID (需 --confirm-id-change)")

    p.add_argument("--confirm-id-change", action="store_true")
    args = p.parse_args()

    if args.list:
        print(f"{'REG':>5}  {'NAME':<12}  TYPE")
        for reg_id, (name, is_float) in sorted(REG_TABLE.items()):
            print(f"  0x{reg_id:02X}  {name:<12}  {'float' if is_float else 'uint'}")
        return

    if args.change_id is not None and not args.confirm_id_change:
        print("[错误] --change-id 需同时加 --confirm-id-change 显式确认",
              file=sys.stderr)
        print("  改 ID 后立即失联, 必须拔电重上, 用新 ID 重连.",
              file=sys.stderr)
        sys.exit(2)

    bus = open_bus(channel="can0", bitrate=1_000_000)
    try:
        with DMMotor(bus, motor_id=args.motor_id, master_id=args.master_id,
                     auto_enable=False, ping_on_enter=False) as motor:
            if args.get is not None:
                val = motor.read_param(args.get, timeout=0.3)
                if val is None:
                    print(f"[fail] 读 0x{args.get:02X} 超时"); sys.exit(1)
                name = REG_TABLE.get(args.get, (f"REG_{args.get:02X}",))[0]
                print(f"  {name} (0x{args.get:02X}) = {fmt_value(args.get, val)}")

            elif args.set is not None:
                reg = parse_reg(args.set[0])
                val = float(args.set[1])
                motor.write_param(reg, val)
                print(f"  写 0x{reg:02X} = {val} (未保存到 Flash, 跑 --save 固化)")

            elif args.set_zero:
                motor.set_zero()
                print("  [ok] 当前位置已置零 (未固化, --save 保存)")

            elif args.clear_error:
                motor.clear_error()
                print("  [ok] 清错指令已发送")

            elif args.save:
                motor.save_to_flash()
                print("  [ok] 保存到 Flash 指令已发送")

            elif args.change_id is not None:
                new_can, new_mst = args.change_id
                print(f"  写 CAN_ID = 0x{new_can:02X}")
                motor.write_param(0x10, float(new_can))
                print(f"  写 MST_ID = 0x{new_mst:02X}")
                motor.write_param(0x11, float(new_mst))
                print("  保存到 Flash")
                motor.save_to_flash()
                print(f"  [ok] 请拔电重上, 新参数: --motor-id 0x{new_can:02X} "
                      f"--master-id 0x{new_mst:02X}")

    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
