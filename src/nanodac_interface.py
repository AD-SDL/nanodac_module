"""Driver to communicate with a Eurotherm nanodac temperature controller over Modbus/TCP.

Confirmed against nanodac v5.50, slave id 1, over Modbus/TCP (default port 502).

nanodac Modbus notes (learned the hard way on this firmware):
  * The canonical "Loop.1 PV at register 1" is WRONG here - Loop.1.Main starts at
    base address 512 (Loop.2 at 640, +128 apart). Verified via iTools.
  * REAL (float) parameters are read/written in native IEEE-float form at
    (scaled_int_address * 2) + 0x8000, two 16-bit registers, big-endian, high
    word first (per HA030554 section 5.3). NOTE the *2: it is NOT scaled+0x8000 -
    that lands on a different parameter (e.g. Channel.1 instead of Loop.1).
  * Bool/enum params (AutoMan, Inhibit, IntHold) are plain 1-register int reads;
    their float mirror is garbage, so read them as ints.
"""

import struct
from typing import Optional

from pymodbus.client import ModbusTcpClient

FLOAT_MIRROR = 0x8000

LOOP_BASE = {1: 512, 2: 640}  # Loop.2 is +128 from Loop.1
PARAM_OFFSET = {
    "PV": 0,
    "AutoMan": 1,
    "TargetSP": 2,
    "WorkingSP": 3,
    "ActiveOut": 4,
    "Inhibit": 5,
    "IntHold": 6,
}
REAL_PARAMS = {"PV", "TargetSP", "WorkingSP", "ActiveOut"}


class Nanodac:
    """Python interface for remote get/set of a Eurotherm nanodac over Modbus/TCP."""

    def __init__(self, host: str, port: int = 502, unit_id: int = 1, timeout: float = 2.0) -> None:
        """Store connection parameters and open the Modbus/TCP connection."""
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self.connection: Optional[ModbusTcpClient] = None
        self.status_msg = ""
        self.connect()

    def connect(self) -> None:
        """Open the Modbus/TCP connection to the nanodac."""
        self.connection = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout)
        if not self.connection.connect():
            raise ConnectionError(f"Could not connect to nanodac at {self.host}:{self.port}")

    def disconnect(self) -> None:
        """Close the Modbus/TCP connection."""
        if self.connection is not None:
            self.connection.close()

    # --- low-level Modbus access (the register-device equivalent of send_command) ---

    def _read_registers(self, address: int, count: int) -> list:
        """Read holding registers, tolerating the pymodbus device_id/slave rename."""
        try:
            rr = self.connection.read_holding_registers(address=address, count=count, device_id=self.unit_id)
        except TypeError:
            rr = self.connection.read_holding_registers(address=address, count=count, slave=self.unit_id)
        if rr.isError():
            raise IOError(f"Modbus read error @ {address}: {rr}")
        return rr.registers

    def _write_registers(self, address: int, values: list) -> None:
        """Write holding registers, tolerating the pymodbus device_id/slave rename."""
        try:
            wr = self.connection.write_registers(address=address, values=values, device_id=self.unit_id)
        except TypeError:
            wr = self.connection.write_registers(address=address, values=values, slave=self.unit_id)
        if wr.isError():
            raise IOError(f"Modbus write error @ {address}: {wr}")

    @staticmethod
    def _decode_float(regs: list) -> float:
        """Decode a nanodac IEEE-float register pair (big-endian, high word first)."""
        hi, lo = regs
        return struct.unpack(">f", struct.pack(">HH", hi, lo))[0]

    @staticmethod
    def _encode_float(value: float) -> list:
        """Encode a float into the nanodac's two-register big-word-first layout."""
        hi, lo = struct.unpack(">HH", struct.pack(">f", float(value)))
        return [hi, lo]

    def _address(self, param: str, loop: int) -> int:
        """Resolve the scaled-integer Modbus address of a loop parameter."""
        return LOOP_BASE[loop] + PARAM_OFFSET[param]

    @staticmethod
    def _native(scaled_addr: int) -> int:
        """Native (IEEE float32) address for a scaled-integer address.

        Per HA030554 section 5.3: native address = (scaled integer address * 2) + 0x8000.
        """
        return scaled_addr * 2 + FLOAT_MIRROR

    def read_parameter(self, param: str, loop: int = 1):
        """Read a loop parameter (native float for REAL params, scaled int otherwise)."""
        addr = self._address(param, loop)
        if param in REAL_PARAMS:
            return self._decode_float(self._read_registers(self._native(addr), 2))
        return self._read_registers(addr, 1)[0]

    def write_parameter(self, param: str, value: float, loop: int = 1) -> None:
        """Write a REAL loop parameter as a native IEEE float."""
        if param not in REAL_PARAMS:
            raise ValueError(f"{param} is not a writable REAL parameter")
        self._write_registers(self._native(self._address(param, loop)), self._encode_float(value))

    # --- high-level temperature API ---

    def get_temperature(self, loop: int = 1) -> Optional[float]:
        """Return the current process value (measured temperature)."""
        return self.read_parameter("PV", loop)

    def get_target_temperature(self, loop: int = 1) -> Optional[float]:
        """Return the target setpoint (None if never written)."""
        return self.read_parameter("TargetSP", loop)

    def get_working_setpoint(self, loop: int = 1) -> Optional[float]:
        """Return the working setpoint (the value actively used, may ramp toward the target)."""
        return self.read_parameter("WorkingSP", loop)

    def get_output(self, loop: int = 1) -> Optional[float]:
        """Return the active control output (%)."""
        return self.read_parameter("ActiveOut", loop)

    def get_mode(self, loop: int = 1) -> str:
        """Return the loop control mode ('Auto' or 'Manual')."""
        return "Manual" if self.read_parameter("AutoMan", loop) else "Auto"

    def set_temperature(self, value: float, loop: int = 1) -> None:
        """Set the loop target setpoint. NOTE: physically drives the controller.

        Writes TargetSP as a native IEEE float at (scaled*2)+0x8000 per HA030554.
        The applied setpoint is subject to the loop's SP limits (Loop.n.SP.SPHighLimit /
        SPLowLimit), active-SP selection (SPSelect), and rate limit (SP.Rate).
        """
        self.write_parameter("TargetSP", value, loop)

    def get_status(self, loop: int = 1) -> dict:
        """Return a snapshot of the loop state (used by the node's state handler)."""
        status = {
            "mode": self.get_mode(loop),
            "process_value": self.get_temperature(loop),
            "target_setpoint": self.get_target_temperature(loop),
            "working_setpoint": self.get_working_setpoint(loop),
            "output": self.get_output(loop),
        }
        self.status_msg = "READY"
        return status


if __name__ == "__main__":
    """Smoke test: connect and print Loop.1 status."""
    nanodac = Nanodac("192.168.1.100")  # replace with your controller's IP
    print(nanodac.get_status())
    nanodac.disconnect()
