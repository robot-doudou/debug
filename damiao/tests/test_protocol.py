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
