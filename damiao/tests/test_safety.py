"""测试 SafetyLimits 钳制逻辑 (纯函数, 无硬件)。"""
import math
import pytest
from device import SafetyLimits, SAFE_DEFAULTS


def test_safe_defaults_values():
    assert SAFE_DEFAULTS.tau == 1.0
    assert SAFE_DEFAULTS.vel == 5.0
    assert math.isclose(SAFE_DEFAULTS.pos, 3.14)
    assert SAFE_DEFAULTS.kp == 20.0
    assert SAFE_DEFAULTS.kd == 1.0


def test_clamp_tau_saturates_positive():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_tau(5.0) == 1.0


def test_clamp_tau_saturates_negative():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_tau(-10.0) == -1.0


def test_clamp_tau_within_range_unchanged():
    limits = SafetyLimits(tau=2.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_tau(0.5) == 0.5


def test_clamp_vel_symmetric():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_vel(10.0) == 5.0
    assert limits.clamp_vel(-10.0) == -5.0


def test_clamp_pos_symmetric():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=1.0, kp=20.0, kd=1.0)
    assert limits.clamp_pos(2.0) == 1.0
    assert limits.clamp_pos(-2.0) == -1.0


def test_clamp_kp_nonnegative_upper_only():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_kp(100.0) == 20.0
    assert limits.clamp_kp(-5.0) == 0.0  # KP 不能为负


def test_clamp_kd_nonnegative_upper_only():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_kd(5.0) == 1.0
    assert limits.clamp_kd(-1.0) == 0.0
