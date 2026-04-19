"""DM v4 协议帧编解码测试 (纯位操作, 无硬件)。

测试向量按官方 SDK float_to_uint (C 风格截断) 推导, 细节见 device.py 注释。
"""
import pytest
from device import float_to_uint, uint_to_float, pack_mit_cmd


def test_float_to_uint_mid_point_truncates():
    # pos=0, p_max=12.5, 16-bit: 应为 0x7FFF (截断非四舍五入)
    assert float_to_uint(0.0, -12.5, 12.5, 16) == 0x7FFF


def test_float_to_uint_max_endpoint():
    assert float_to_uint(12.5, -12.5, 12.5, 16) == 0xFFFF


def test_float_to_uint_min_endpoint():
    assert float_to_uint(-12.5, -12.5, 12.5, 16) == 0


def test_float_to_uint_clips_above_max():
    # 超过 max 截到最大值 (保险不溢出)
    assert float_to_uint(20.0, -12.5, 12.5, 16) == 0xFFFF


def test_float_to_uint_clips_below_min():
    assert float_to_uint(-20.0, -12.5, 12.5, 16) == 0


def test_uint_to_float_roundtrip_endpoints():
    assert uint_to_float(0xFFFF, -12.5, 12.5, 16) == pytest.approx(12.5, rel=1e-4)
    assert uint_to_float(0, -12.5, 12.5, 16) == pytest.approx(-12.5, rel=1e-4)


def test_pack_mit_cmd_all_zero_mid():
    # 全零输入 (pos=vel=kp=kd=tau=0) 期望: 7F FF 7F F0 00 00 07 FF
    data = pack_mit_cmd(pos=0.0, vel=0.0, kp=0.0, kd=0.0, tau=0.0,
                        p_max=12.5, v_max=30.0, t_max=7.0)
    assert data == bytes([0x7F, 0xFF, 0x7F, 0xF0, 0x00, 0x00, 0x07, 0xFF])


def test_pack_mit_cmd_max_pos():
    # pos=12.5 → pos_int=0xFFFF, 其余零
    data = pack_mit_cmd(pos=12.5, vel=0.0, kp=0.0, kd=0.0, tau=0.0,
                        p_max=12.5, v_max=30.0, t_max=7.0)
    assert data[0] == 0xFF  # pos_high
    assert data[1] == 0xFF  # pos_low


def test_pack_mit_cmd_min_pos():
    data = pack_mit_cmd(pos=-12.5, vel=0.0, kp=0.0, kd=0.0, tau=0.0,
                        p_max=12.5, v_max=30.0, t_max=7.0)
    assert data[0] == 0x00
    assert data[1] == 0x00


def test_pack_mit_cmd_kp_max_500():
    # kp=500 → kp_int=0xFFF; byte 3 低 4 bit = kp_int[11:8] = 0xF
    data = pack_mit_cmd(pos=0.0, vel=0.0, kp=500.0, kd=0.0, tau=0.0,
                        p_max=12.5, v_max=30.0, t_max=7.0)
    assert data[3] & 0x0F == 0x0F
    assert data[4] == 0xFF


def test_pack_mit_cmd_returns_8_bytes():
    data = pack_mit_cmd(pos=1.0, vel=0.5, kp=10.0, kd=0.5, tau=0.2,
                        p_max=12.5, v_max=30.0, t_max=7.0)
    assert len(data) == 8


from device import MotorState, parse_mit_feedback


def test_parse_mit_feedback_zero_mid():
    # 对应 pack 全零的反馈逆过程: 7F FF 7F F? ?? T_mos T_rotor
    # byte 0: err=1(Enable), id=0x01 → 0x11
    # pos=0x7FFF, vel=0x7FF, tau=0x7FF
    data = bytes([0x11, 0x7F, 0xFF, 0x7F, 0xF7, 0xFF, 0x19, 0x23])  # T_mos=25, T_rotor=35
    state = parse_mit_feedback(data, p_max=12.5, v_max=30.0, t_max=7.0)
    assert state.motor_id == 0x01
    assert state.err_code == 1
    assert state.pos == pytest.approx(0.0, abs=1e-3)
    assert state.vel == pytest.approx(0.0, abs=1e-2)
    assert state.tau == pytest.approx(0.0, abs=1e-2)
    assert state.t_mos == 25
    assert state.t_rotor == 35


def test_parse_mit_feedback_err_code_extracted():
    # err=0xA (Overcurrent), id=0x02 → byte0 = 0xA2
    data = bytes([0xA2, 0x80, 0x00, 0x80, 0x08, 0x00, 0x00, 0x00])
    state = parse_mit_feedback(data, p_max=12.5, v_max=30.0, t_max=7.0)
    assert state.motor_id == 0x02
    assert state.err_code == 0xA


def test_parse_mit_feedback_wrong_length():
    with pytest.raises(ValueError):
        parse_mit_feedback(bytes(7), p_max=12.5, v_max=30.0, t_max=7.0)


from device import CMD_ENABLE, CMD_DISABLE, CMD_SET_ZERO, CMD_CLEAR_ERROR


def test_cmd_enable_bytes():
    assert CMD_ENABLE == bytes([0xFF]*7 + [0xFC])


def test_cmd_disable_bytes():
    assert CMD_DISABLE == bytes([0xFF]*7 + [0xFD])


def test_cmd_set_zero_bytes():
    assert CMD_SET_ZERO == bytes([0xFF]*7 + [0xFE])


def test_cmd_clear_error_bytes():
    assert CMD_CLEAR_ERROR == bytes([0xFF]*7 + [0xFB])


import struct
from device import (
    servo_pos_frame, servo_speed_frame,
    param_read_frame, param_write_frame, param_save_frame,
)


def test_servo_pos_frame():
    can_id, data = servo_pos_frame(motor_id=0x01, pos=1.5, vel=2.0)
    assert can_id == 0x101
    expected = struct.pack("<ff", 1.5, 2.0)
    assert data == expected


def test_servo_speed_frame():
    can_id, data = servo_speed_frame(motor_id=0x02, vel=3.14)
    assert can_id == 0x202
    # 官方 SDK 发 8 字节 (float + 4B 补零)
    assert data == struct.pack("<f", 3.14) + bytes(4)
    assert len(data) == 8


def test_param_read_frame():
    can_id, data = param_read_frame(motor_id=0x01, reg_id=0x07)  # 0x07 = PMAX
    assert can_id == 0x7FF
    assert data[0] == 0x01  # motor_id lo
    assert data[1] == 0x00  # motor_id hi
    assert data[2] == 0x33  # 读
    assert data[3] == 0x07
    assert data[4:8] == bytes(4)


def test_param_write_frame_float():
    can_id, data = param_write_frame(motor_id=0x01, reg_id=0x07, value=12.5)
    assert can_id == 0x7FF
    assert data[2] == 0x55  # 写
    assert data[3] == 0x07
    assert data[4:8] == struct.pack("<f", 12.5)


def test_param_save_frame():
    can_id, data = param_save_frame(motor_id=0x01)
    assert can_id == 0x7FF
    assert data[2] == 0xAA  # 保存
