# hass-wattbox
Home Assistant WattBox Component


Example Config:
```
wattbox:
- host: 192.168.1.100
  name: wattbox1
  username: username1
  password: password1
- host: 192.168.1.101
  name: wattbox2
  username: username2
  password: password2
  resources:
  - auto_reboot
  - mute
  - safe_voltage_status
  - current_value
  - power_value
  - voltage_value
```

Configuration Options:

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

Master switch will turn on / off all the switches that the physical switch on the box does. You can config that through the UI on the wattbox directly.

Be careful, if the WattBox controls the power to its own networking equipment you can turn it off and not have remote access until you fix it. You may even have to plug it in elsewhere to get back online and turn that outlet back on in HA.

Based on the Blueprint found at: https://github.com/custom-components/blueprint
And the apcupsd component at: https://github.com/home-assistant/home-assistant/tree/dev/homeassistant/components/apcupsd
