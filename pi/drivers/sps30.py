import struct
import time

import serial

ADR = 0x00
CMD_START = 0x00
CMD_STOP = 0x01
CMD_READ = 0x03

_STUFF = {
    0x7E: bytes([0x7D, 0x5E]),
    0x7D: bytes([0x7D, 0x5D]),
    0x11: bytes([0x7D, 0x31]),
    0x13: bytes([0x7D, 0x33]),
}
_UNSTUFF = {v[1]: k for k, v in _STUFF.items()}


class SPS30Error(Exception):
    pass


def _stuff(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        chunk = _STUFF.get(b)
        if chunk is None:
            out.append(b)
        else:
            out += chunk
    return bytes(out)


def _unstuff(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == 0x7D:
            i += 1
            if i >= len(data):
                raise SPS30Error("dangling escape byte")
            resolved = _UNSTUFF.get(data[i])
            if resolved is None:
                raise SPS30Error(f"invalid escape 7D {data[i]:02X}")
            out.append(resolved)
        else:
            out.append(b)
        i += 1
    return bytes(out)


def _checksum(payload: bytes) -> int:
    return (~sum(payload)) & 0xFF


def _build_frame(cmd: int, data: bytes = b"") -> bytes:
    payload = bytes([ADR, cmd, len(data)]) + data
    return b"\x7E" + _stuff(payload + bytes([_checksum(payload)])) + b"\x7E"


class SPS30:
    def __init__(self, device: str, timeout: float = 2.0):
        self._ser = serial.Serial(device, 115200, timeout=timeout)

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "SPS30":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _read_frame(self) -> tuple[int, int, bytes]:
        while True:
            b = self._ser.read(1)
            if not b:
                raise SPS30Error("timeout waiting for start delimiter")
            if b == b"\x7E":
                break
        buf = bytearray()
        while True:
            b = self._ser.read(1)
            if not b:
                raise SPS30Error("timeout reading frame body")
            if b == b"\x7E":
                break
            buf += b
        inner = _unstuff(bytes(buf))
        if len(inner) < 5:
            raise SPS30Error(f"frame too short: {inner.hex()}")
        adr, cmd, state, length = inner[0], inner[1], inner[2], inner[3]
        data = inner[4 : 4 + length]
        chk = inner[4 + length]
        if _checksum(bytes([adr, cmd, state, length]) + data) != chk:
            raise SPS30Error(f"reply checksum mismatch: {inner.hex()}")
        return cmd, state, data

    def _txn(self, cmd: int, data: bytes = b"") -> bytes:
        self._ser.reset_input_buffer()
        self._ser.write(_build_frame(cmd, data))
        self._ser.flush()
        rcmd, state, rdata = self._read_frame()
        if rcmd != cmd:
            raise SPS30Error(f"reply cmd 0x{rcmd:02X} != request 0x{cmd:02X}")
        if state != 0:
            raise SPS30Error(f"device state 0x{state:02X} on cmd 0x{cmd:02X}")
        return rdata

    def start(self) -> None:
        self._txn(CMD_START, bytes([0x01, 0x03]))

    def stop(self) -> None:
        self._txn(CMD_STOP)

    def read(self) -> dict:
        data = self._txn(CMD_READ)
        if len(data) != 40:
            raise SPS30Error(f"expected 40 bytes of data, got {len(data)}")
        f = struct.unpack(">10f", data)
        return {
            "pm1_0_ug_m3":     f[0],
            "pm2_5_ug_m3":     f[1],
            "pm4_0_ug_m3":     f[2],
            "pm10_ug_m3":      f[3],
            "nc0_5_per_cm3":   f[4],
            "nc1_0_per_cm3":   f[5],
            "nc2_5_per_cm3":   f[6],
            "nc4_0_per_cm3":   f[7],
            "nc10_per_cm3":    f[8],
            "typical_size_um": f[9],
        }
