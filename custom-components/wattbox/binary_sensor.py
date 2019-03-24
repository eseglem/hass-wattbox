"""Binary sensor platform for blueprint."""
from homeassistant.components.binary_sensor import BinarySensorDevice
from homeassistant.const import (
    CONF_RESOURCES, 
)
from . import update_data
from .const import (
    DOMAIN_DATA,
)

# TODO: Device Classes
SENSOR_TYPES = {
    'audible_alarm': ['Audible Alarm', ''],
    'auto_reboot': ['Auto Reboot', ''],
    'battery_health': ['Battery Health', ''],
    'battery_test': ['Battery Test', ''],
    'cloud_status': ['Cloud Status', ''],
    'has_ups': ['Has UPS', ''],
    'mute': ['Mute', ''],
    'power_lost': ['Power Lost', ''],
    'safe_voltage_status': ['Safe Voltage Status', ''],
}

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):  # pylint: disable=unused-argument
    """Setup binary_sensor platform."""
    # TODO: Loop
    async_add_entities([WattBoxBinarySensor(hass, discovery_info)], True)


class WattBoxBinarySensor(BinarySensorDevice):
    """blueprint binary_sensor class."""

    def __init__(self, hass, sensor_type):
        self.hass = hass
        self.attr = {}
        self.type = sensor_type
        self._status = False
        self._name = SENSOR_TYPES[sensor_type][0]

    async def async_update(self):
        """Update the sensor."""
        # Send update "signal" to the component
        await update_data(self.hass)

        # Get new data (if any)
        updated = self.hass.data[DOMAIN_DATA]

        # Check the data and update the value.
        self._state = getattr(updated, self.type)

    @property
    def name(self):
        """Return the name of the binary_sensor."""
        return self._name

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return SENSOR_TYPES[self.type][1]

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return self._status

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self.attr