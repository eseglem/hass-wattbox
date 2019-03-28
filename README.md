# hass-wattbox
Home Assistant WattBox Component

Configuration:

* *host*: Host IP of the WattBox (Required)
* *port*: Port of the HTTP interface (Default 80)
* *username*: Username for authentication (Default wattbox)
* *password*: Password for authentication (Default wattbox)
* *name*: Name for the WattBox (Default wattbox)
* *resources*: A list of resources to enable (Default all of them)

Resources:
* audible_alarm
* auto_reboot
* battery_health
* battery_test
* cloud_status
* has_ups
* mute
* power_lost
* safe_voltage_status
* battery_charge
* battery_load
* current_value
* est_run_time
* power_value
* voltage_value

Based on the Blueprint found at: https://github.com/custom-components/blueprint
And the apcupsd component at: https://github.com/home-assistant/home-assistant/tree/dev/homeassistant/components/apcupsd
