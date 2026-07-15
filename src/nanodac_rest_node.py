"""MADSci REST node for the Eurotherm nanodac temperature controller (Modbus/TCP)."""

from typing import Annotated, Optional

from madsci.common.types.action_types import ActionFailed, ActionSucceeded
from madsci.common.types.node_types import RestNodeConfig
from madsci.node_module.helpers import action
from madsci.node_module.rest_node_module import RestNode
from pydantic import Field

from nanodac_interface import Nanodac


class NanodacNodeConfig(RestNodeConfig):
    """Configuration for the nanodac node module."""

    nanodac_ip: Optional[str] = Field(default=None, description="IP address of the nanodac controller (Modbus/TCP).")
    nanodac_port: int = Field(default=502, description="Modbus/TCP port, default 502.")
    unit_id: int = Field(default=1, description="Modbus slave/unit id, default 1.")
    loop: int = Field(default=1, description="Control loop exposed by default (1 or 2).")
    default_ramp_rate: Optional[float] = Field(
        default=None,
        description="Setpoint ramp-rate limit (eng units/min; 0 = instant) applied at startup. If unset, the driver's built-in default is used.",
    )


class NanodacNode(RestNode):
    """A MADSci REST node to read and control a Eurotherm nanodac temperature controller."""

    nanodac_interface: Nanodac = None
    config: NanodacNodeConfig = NanodacNodeConfig()
    config_model = NanodacNodeConfig

    def startup_handler(self) -> None:
        """Open the Modbus/TCP connection to the nanodac.

        Exceptions are logged and re-raised so the framework's ``_startup`` marks
        the node as errored instead of leaving it falsely "ready".
        """
        if self.config.nanodac_ip is None:
            raise ValueError("nanodac_ip is not set in the configuration.")
        try:
            kwargs = {
                "host": self.config.nanodac_ip,
                "port": self.config.nanodac_port,
                "unit_id": self.config.unit_id,
            }
            if self.config.default_ramp_rate is not None:
                kwargs["default_ramp_rate"] = self.config.default_ramp_rate
            self.nanodac_interface = Nanodac(**kwargs)
        except Exception as err:
            self.logger.log_error(f"Error starting the nanodac node: {err}")
            raise
        self.logger.log_info("nanodac node initialized!")

    def shutdown_handler(self) -> None:
        """Close the connection to the nanodac."""
        try:
            if self.nanodac_interface is not None:
                self.nanodac_interface.disconnect()
                self.nanodac_interface = None
        except Exception as err:
            self.logger.log_error(f"Error shutting down the nanodac node: {err}")
            raise

    def state_handler(self) -> None:
        """Periodically poll the loop and publish node state."""
        if self.nanodac_interface is None:
            return
        try:
            status = self.nanodac_interface.get_status(self.config.loop)
        except Exception as err:
            self.node_state = {"nanodac_status_code": "ERROR"}
            self.logger.log_error(f"nanodac state error: {err}")
            return
        self.node_state = {"nanodac_status_code": "READY", **status}

    @action(name="get_temperature", description="Read the current temperature (process value)")
    def get_temperature(self, loop: Annotated[Optional[int], "control loop (1 or 2)"] = None):
        """Return the measured temperature of the loop."""
        try:
            value = self.nanodac_interface.get_temperature(loop or self.config.loop)
        except Exception as err:
            return ActionFailed(errors=[str(err)])
        return ActionSucceeded(json_result={"temperature": value})

    @action(name="get_setpoint", description="Read the target temperature setpoint")
    def get_setpoint(self, loop: Annotated[Optional[int], "control loop (1 or 2)"] = None):
        """Return the target setpoint (None if never written)."""
        try:
            value = self.nanodac_interface.get_target_temperature(loop or self.config.loop)
        except Exception as err:
            return ActionFailed(errors=[str(err)])
        return ActionSucceeded(json_result={"setpoint": value})

    @action(name="set_temperature", description="Set the target temperature setpoint (drives the loop)")
    def set_temperature(
        self,
        temperature: Annotated[float, "target temperature in engineering units"],
        loop: Annotated[Optional[int], "control loop (1 or 2)"] = None,
        ramp_rate: Annotated[
            Optional[float], "setpoint ramp rate in units/min (0 = instant); omit to leave unchanged"
        ] = None,
    ):
        """Write the loop target setpoint, optionally ramping to it at ramp_rate."""
        try:
            self.nanodac_interface.set_temperature(temperature, loop or self.config.loop, ramp_rate=ramp_rate)
        except Exception as err:
            return ActionFailed(errors=[str(err)])
        return ActionSucceeded()

    @action(name="set_setpoint_rate", description="Set the setpoint ramp rate (units/min; 0 = instant)")
    def set_setpoint_rate(
        self,
        rate: Annotated[float, "setpoint ramp rate in engineering units per minute (0 = disable ramp)"],
        loop: Annotated[Optional[int], "control loop (1 or 2)"] = None,
    ):
        """Set the loop's setpoint ramp-rate limit for smooth setpoint changes."""
        try:
            self.nanodac_interface.set_setpoint_rate(rate, loop or self.config.loop)
        except Exception as err:
            return ActionFailed(errors=[str(err)])
        return ActionSucceeded()

    @action(name="get_output", description="Read the control output (%)")
    def get_output(self, loop: Annotated[Optional[int], "control loop (1 or 2)"] = None):
        """Return the active control output percentage of the loop."""
        try:
            value = self.nanodac_interface.get_output(loop or self.config.loop)
        except Exception as err:
            return ActionFailed(errors=[str(err)])
        return ActionSucceeded(json_result={"output": value})

    @action(name="get_setpoint_rate", description="Read the setpoint ramp rate (units/min; 0 = off)")
    def get_setpoint_rate(self, loop: Annotated[Optional[int], "control loop (1 or 2)"] = None):
        """Return the loop's setpoint ramp-rate limit."""
        try:
            value = self.nanodac_interface.get_setpoint_rate(loop or self.config.loop)
        except Exception as err:
            return ActionFailed(errors=[str(err)])
        return ActionSucceeded(json_result={"setpoint_rate": value})


if __name__ == "__main__":
    node = NanodacNode()
    node.start_node()
