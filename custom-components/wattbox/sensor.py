import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_RESOURCES, 
    POWER_WATT,
)
from homeassistant.helpers.entity import Entity
from . import update_data
from .const import (
    DOMAIN_DATA,
)

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES = {
    'battery_charge': ['Battery Charge', '%', 'mdi:gauge'],
    'battery_load': ['Battery Load', '%', 'mdi:gauge'],
    'current_value': ['Current', 'A', 'mdi:current-ac'],
    'est_run_time': ['Estimated Run Time', 'min', 'mdi:update'],
    'power_value': ['Power', POWER_WATT, 'mdi:lightbulb-outline'],
    'voltage_value': ['Voltage', 'V', 'mdi:flash-circle'],
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_RESOURCES, default=[]): 
        vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES)]),
})

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):  # pylint: disable=unused-argument
    """Setup sensor platform."""
    entities = []

    for resource in config[CONF_RESOURCES]:
        sensor_type = resource.lower()

        if sensor_type not in SENSOR_TYPES:
            # How to only warn if in neither type?
            # _LOGGER.warning("Sensor type: %s is not a valid type.", sensor_type)
            continue

        entities.append(WattBoxSensor(hass, sensor_type))

    async_add_entities(entities, True)

class WattBoxSensor(Entity):
    """WattBox Sensor class."""

    def __init__(self, hass, sensor_type):
        self.hass = hass
        self.attr = {}
        self.type = sensor_type
        self._name = SENSOR_TYPES[self.type][0]
        self._state = None
        self._unit = SENSOR_TYPES[self.type][1]

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
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return SENSOR_TYPES[self.type][2]

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self.attr

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit