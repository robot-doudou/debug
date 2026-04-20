"""达妙电机参数寄存器读写 + 改 ID + 零点 + 清错 + 保存到 Flash。

敏感操作:
  --change-id: 改完立即失联, 必须拔电重上; 需要 --confirm-id-change flag
  --save:      写入 Flash 永久生效
"""
from __future__ import annotations

import argparse
import sys

import struct

from device import DMMotor, open_bus, add_id_args, resolve_ids

# 权威来源: cmjang/DM_Control_Python (DM_variable enum) +
#           cmjang/DM_Motor_Control (DM_REG enum in damiao.h)
# 两份独立实现映射完全一致, 已在 DM4310-P V4 固件上实测核对.
REG_TABLE = {
    # reg_id: (name, is_float)
    0x00: ("UV_Value", True),     # 欠压阈值 V
    0x01: ("KT_Value", True),     # 扭矩系数
    0x02: ("OT_Value", True),     # 过温阈值 °C
    0x03: ("OC_Value", True),     # 过流阈值 A
    0x04: ("ACC", True),          # 加速度
    0x05: ("DEC", True),          # 减速度
    0x06: ("MAX_SPD", True),      # 速度上限
    0x07: ("MST_ID", False),      # 主机反馈帧 CAN ID (uint32)
    0x08: ("ESC_ID", False),      # 电机自身 CAN ID = "CAN_ID" (uint32)
    0x09: ("TIMEOUT", False),     # 通讯超时 (uint32)
    0x0A: ("CTRL_MODE", False),   # 1=MIT, 2=POS_VEL, 3=VEL, 4=Torque_Pos
    0x0B: ("Damp", True),         # 阻尼
    0x0C: ("Inertia", True),      # 惯量
    0x0D: ("hw_ver", False),
    0x0E: ("sw_ver", False),
    0x0F: ("SN", False),          # 序列号
    0x10: ("NPP", False),         # 极对数 (4310P = 14)
    0x11: ("Rs", True),           # 定子电阻 Ω
    0x12: ("LS", True),           # 定子电感
    0x13: ("Flux", True),         # 磁链
    0x14: ("Gr", True),           # 减速比
    0x15: ("PMAX", True),         # 位置缩放上限 rad
    0x16: ("VMAX", True),         # 速度缩放上限 rad/s
    0x17: ("TMAX", True),         # 扭矩缩放上限 N·m
    0x18: ("I_BW", True),         # 电流环带宽
    0x19: ("KP_ASR", True),       # 速度环 Kp
    0x1A: ("KI_ASR", True),       # 速度环 Ki
    0x1B: ("KP_APR", True),       # 位置环 Kp
    0x1C: ("KI_APR", True),       # 位置环 Ki
    0x1D: ("OV_Value", True),     # 过压阈值
    0x1E: ("GREF", True),
    0x1F: ("Deta", True),
    # 高级校准参数 (日常调试不用动, 列全方便 --list / --get 全量查询)
    0x20: ("V_BW", True),
    0x21: ("IQ_c1", True),
    0x22: ("VL_c1", True),
    0x23: ("can_br", False),      # uint
    0x24: ("sub_ver", False),     # uint
    0x32: ("u_off", True),
    0x33: ("v_off", True),
    0x34: ("k1", True),
    0x35: ("k2", True),
    0x36: ("m_off", True),
    0x37: ("dir", False),         # uint 旋转方向
    0x50: ("p_m", True),
    0x51: ("xout", True),
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


def decode_value(reg_id: int, raw: bytes):
    """按 REG_TABLE 的 is_float 类型把 4 字节原始数据解成 float 或 int。"""
    is_float = REG_TABLE.get(reg_id, (None, True))[1]
    if is_float:
        return struct.unpack("<f", raw)[0]
    return struct.unpack("<I", raw)[0]


def fmt_value(reg_id: int, value) -> str:
    is_float = REG_TABLE.get(reg_id, (None, True))[1]
    if not is_float:
        return f"{value} (0x{value:02X})"
    return f"{value:.6f}"


def main():
    p = argparse.ArgumentParser(description="达妙电机参数读写")
    add_id_args(p)

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
    resolve_ids(p, args)

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
                raw = motor.read_param_raw(args.get, timeout=0.3)
                if raw is None:
                    print(f"[fail] 读 0x{args.get:02X} 超时"); sys.exit(1)
                val = decode_value(args.get, raw)
                name = REG_TABLE.get(args.get, (f"REG_{args.get:02X}",))[0]
                print(f"  {name} (0x{args.get:02X}) = {fmt_value(args.get, val)}")

            elif args.set is not None:
                reg = parse_reg(args.set[0])
                is_float = REG_TABLE.get(reg, (None, True))[1]
                if is_float:
                    val = float(args.set[1])
                    motor.write_param(reg, val)
                    print(f"  写 0x{reg:02X} = {val} (float, 未保存到 Flash, --save 固化)")
                else:
                    val = int(args.set[1], 0)
                    motor.write_param_uint(reg, val)
                    print(f"  写 0x{reg:02X} = {val} (uint32, 未保存到 Flash, --save 固化)")

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
                # 注意顺序: 先写 MST_ID (用旧 motor_id 能匹配到电机),
                # 再写 ESC_ID (写入瞬间电机切到新 ID, 之后 save 必须用新 ID).
                print(f"  写 MST_ID = 0x{new_mst:02X} (旧 motor_id=0x{args.motor_id:02X})")
                motor.write_param_uint(0x07, new_mst)
                print(f"  写 ESC_ID (CAN_ID) = 0x{new_can:02X} (电机此时切到新 ID)")
                motor.write_param_uint(0x08, new_can)

                # ESC_ID 写入后电机立即切到新 ID, save 命令的 motor_id 字段必须跟新值.
                # 另外 master_id 也同步到新 MST_ID, 保证 save 的回复能被收到 (虽然目前没读 save 回复).
                motor.motor_id = new_can
                motor.master_id = new_mst
                print("  保存到 Flash (使用新 motor_id)")
                motor.save_to_flash()
                print(f"  [ok] 请拔电重上, 新参数: --motor-id 0x{new_can:02X} "
                      f"--master-id 0x{new_mst:02X}")

    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
