"""Lumped thermal model for simulation tests."""

from __future__ import annotations


class RoomModel:
    """
    Simple lumped-capacitance room thermal model.

    Models a room as a single thermal mass exchanging heat with
    the outdoors and receiving heat from underfloor heating.

    All thermal parameters are per unit floor area (W/m², kJ/(K·m²)).
    Area cancels identically in numerator (heat flows) and denominator
    (thermal capacity), so step() works directly with per-m² values.
    """

    def __init__(
        self,
        thermal_mass: float,
        heat_loss_coeff: float,
        heating_power: float,
        outdoor_temp: float,
        initial_temp: float,
    ) -> None:
        """
        Initialize the room model.

        Args:
            thermal_mass: Thermal mass in kJ/(K·m²).
            heat_loss_coeff: Heat loss coefficient in W/(K·m²).
            heating_power: UFH heating power in W/m².
            outdoor_temp: Outdoor temperature in °C.
            initial_temp: Initial room temperature in °C.

        """
        self.thermal_mass = thermal_mass
        self.heat_loss_coeff = heat_loss_coeff
        self.heating_power = heating_power
        self.outdoor_temp = outdoor_temp
        self.temp = initial_temp

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
