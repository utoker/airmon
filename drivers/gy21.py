import time

from smbus2 import SMBus, i2c_msg

ADDR = 0x40
CMD_RESET = 0xFE
CMD_TEMP_NOHOLD = 0xF3
CMD_RH_NOHOLD = 0xF5

_MEASURE_WAIT_S = 0.06


class GY21Error(Exception):
    pass


def _read_word(bus_num: int, cmd: int) -> int:
    with SMBus(bus_num) as bus:
        bus.write_byte(ADDR, cmd)
        time.sleep(_MEASURE_WAIT_S)
        read = i2c_msg.read(ADDR, 3)
        bus.i2c_rdwr(read)
        data = bytes(read)
    if len(data) != 3:
        raise GY21Error(f"expected 3 bytes, got {len(data)}")
    raw = (data[0] << 8) | data[1]
    return raw & 0xFFFC


def soft_reset(bus_num: int = 1) -> None:
    with SMBus(bus_num) as bus:
        bus.write_byte(ADDR, CMD_RESET)
    time.sleep(0.02)


def read_temperature_c(bus_num: int = 1) -> float:
    raw = _read_word(bus_num, CMD_TEMP_NOHOLD)
    return -46.85 + 175.72 * raw / 65536.0


def read_humidity_pct(bus_num: int = 1) -> float:
    raw = _read_word(bus_num, CMD_RH_NOHOLD)
    return -6.0 + 125.0 * raw / 65536.0
