"""DMMotor 类测试 (使用 python-can virtual bus, 无物理 CAN)。"""
import pytest
import can
from device import DMMotor, SAFE_DEFAULTS, CMD_ENABLE, CMD_DISABLE


@pytest.fixture
def virtual_bus():
    bus = can.Bus(interface="virtual", channel="test", receive_own_messages=False)
    yield bus
    bus.shutdown()


@pytest.fixture
def listener_bus():
    bus = can.Bus(interface="virtual", channel="test", receive_own_messages=False)
    yield bus
    bus.shutdown()


def test_enable_sends_correct_frame(virtual_bus, listener_bus):
    motor = DMMotor(virtual_bus, motor_id=0x01, master_id=0x11,
                    auto_enable=False)
    motor.enable()
    msg = listener_bus.recv(timeout=1.0)
    assert msg is not None
    assert msg.arbitration_id == 0x01
    assert msg.data == CMD_ENABLE


def test_disable_sends_correct_frame(virtual_bus, listener_bus):
    motor = DMMotor(virtual_bus, motor_id=0x02, master_id=0x12,
                    auto_enable=False)
    motor.disable()
    msg = listener_bus.recv(timeout=1.0)
    assert msg is not None
    assert msg.arbitration_id == 0x02
    assert msg.data == CMD_DISABLE


def test_mit_cmd_clamps_to_safety(virtual_bus, listener_bus):
    # 固定 t_max=7.0 让测试向量稳定 (DMMotor 默认 t_max=12.5 与 4310P 实测一致,
    # 但测试向量 0x924 基于 t_max=7 手算得到, 保留作为协议编码参考)
    motor = DMMotor(virtual_bus, motor_id=0x01, master_id=0x11,
                    auto_enable=False, safety=SAFE_DEFAULTS, t_max=7.0)
    # 请求 tau=10, 但 SAFE_DEFAULTS.tau=1.0, 应该被钳制
    motor.mit_cmd(pos=0, vel=0, kp=0, kd=0, tau=10.0)
    msg = listener_bus.recv(timeout=1.0)
    assert msg is not None
    # tau 字段 (最后 12 bit) 应 ≤ 钳制后的最大值 (tau=1.0, t_max=7.0)
    # tau_int = (1.0 - (-7)) * 4095 / 14 = 2340 = 0x924
    tau_int = ((msg.data[6] & 0x0F) << 8) | msg.data[7]
    assert tau_int == 0x924


def test_context_manager_disables_on_exit(virtual_bus, listener_bus):
    with DMMotor(virtual_bus, motor_id=0x01, master_id=0x11,
                 auto_enable=True, ping_on_enter=False) as motor:
        pass
    # 退出后应收到 disable 帧 (最后一条)
    msgs = []
    while True:
        m = listener_bus.recv(timeout=0.1)
        if m is None:
            break
        msgs.append(m)
    assert any(m.data == CMD_DISABLE for m in msgs)


def test_context_manager_disables_on_exception(virtual_bus, listener_bus):
    with pytest.raises(RuntimeError):
        with DMMotor(virtual_bus, motor_id=0x01, master_id=0x11,
                     auto_enable=True, ping_on_enter=False):
            raise RuntimeError("test crash")
    msgs = []
    while True:
        m = listener_bus.recv(timeout=0.1)
        if m is None:
            break
        msgs.append(m)
    assert any(m.data == CMD_DISABLE for m in msgs)
