"""Lumped thermal model for simulation tests."""

from __future__ import annotations


class RoomModel:
    """
    Simple lumped-capacitance room thermal model.

    Models a room as a single thermal mass exchanging heat with
    the outdoors and receiving heat from underfloor heating.
    """

    def __init__(
        self,
        thermal_mass: float,
        heat_loss_coeff: float,
        heating_power: float,
        outdoor_temp: float,
        initial_temp: float | None = None,
    ) -> None:
        """
        Initialize the room model.

        Args:
            thermal_mass: Room thermal mass in kJ/°C.
            heat_loss_coeff: Heat loss coefficient in W/°C.
            heating_power: UFH heating power in W.
            outdoor_temp: Outdoor temperature in °C.
            initial_temp: Initial room temperature (defaults to outdoor + 2°C).

        """
        self.thermal_mass = thermal_mass
        self.heat_loss_coeff = heat_loss_coeff
        self.heating_power = heating_power
        self.outdoor_temp = outdoor_temp
        self.temp = initial_temp if initial_temp is not None else outdoor_temp + 2.0

    def step(self, dt: float, heating_on: bool) -> float:
        """
        Advance the thermal model by dt seconds.

        Args:
            dt: Time step in seconds.
            heating_on: Whether the heating system is delivering heat.

        Returns:
            New room temperature after the time step.

        """
        q_loss = self.heat_loss_coeff * (self.temp - self.outdoor_temp)
        q_gain = self.heating_power if heating_on else 0.0
        self.temp += (q_gain - q_loss) * dt / (self.thermal_mass * 1000)
        return self.temp
