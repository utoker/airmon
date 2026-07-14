import serial

READ_CO2 = bytes([0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])


class MHZ19BError(Exception):
    pass


def _checksum(frame: bytes) -> int:
    return (0xFF - (sum(frame[1:8]) & 0xFF) + 1) & 0xFF


def read_co2_ppm(device: str) -> int:
    with serial.Serial(device, 9600, timeout=1.0) as s:
        s.reset_input_buffer()
        s.write(READ_CO2)
        resp = s.read(9)
    if len(resp) != 9:
        raise MHZ19BError(f"short response: got {len(resp)} bytes, wanted 9 (raw={resp.hex()})")
    if resp[0] != 0xFF or resp[1] != 0x86:
        raise MHZ19BError(f"bad header (raw={resp.hex()})")
    if _checksum(resp) != resp[8]:
        raise MHZ19BError(f"checksum failed (raw={resp.hex()})")
    return resp[2] * 256 + resp[3]
