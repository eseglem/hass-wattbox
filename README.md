[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[![Discord][discord-shield]][discord]
[![Community Forum][forum-shield]][forum]

# hass-wattbox

_Home Assistant Component to integrate with [WattBox][wattbox]._

Easiest way to install this component is through [HACS][hacs].

Configuration through `configuration.yaml`, not available in UI yet.

Example Config:

```
wattbox:
- host: 192.168.1.100
  name: wattbox1
  username: username1
  password: password1
  name_regexp: "^Fixed Prefix (.*)$"
  skip_regexp: "SKIP"
  scan_interval: 00:00:10
- host: 192.168.1.101
  name: wattbox2
  username: username2
  password: password2
  scan_interval: 00:00:20
  resources:
  - auto_reboot
  - mute
  - safe_voltage_status
  - current_value
  - power_value
  - voltage_value
```

Configuration Options:

- _host_: Host IP of the WattBox (Required)
- _port_: Port of the HTTP interface (Default 80)
- _username_: Username for authentication (Default wattbox)
- _password_: Password for authentication (Default wattbox)
- _name_: Name for the WattBox (Default wattbox)
- _resources_: A list of resources to enable (Default all of them)
- _scan_interval_: A time interval run updates at (Default 30s, format HH:MM:SS)
- _name_regexp_: A regexp to extract the name to use for the outlet instead of just the index. If there is a match group, it is used, else the whole match is used.
- _skip_regexp_: A regexp to use that, if the outlet name matches, the outlet is not added as a switch entity.

Resources:

- audible_alarm
- auto_reboot
- battery_health
- battery_test
- cloud_status
- has_ups
- mute
- power_lost
- safe_voltage_status
- battery_charge
- battery_load
- current_value
- est_run_time
- power_value
- voltage_value

Be careful, if the WattBox controls the power to its own networking equipment you can turn it off and not have remote access until you fix it. You may even have to plug it in elsewhere to get back online and turn that outlet back on in HA. Use the _skip_regexp_ option for those outlets.

Master switch will turn on / off all the switches that the physical switch on the box does. You can config that through the UI on the wattbox directly. If ALL of the switches controlled by Master are on, then Master will be on. Otherwise it will be off. If any outlets on a wattbox are skipped via _skip_regexp_ then
the master switch for that wattbox will also not be added as an entity.

You can use

Based on [custom-components/integration_blueprint][blueprint]

<!---->

---

[wattbox]: https://www.snapav.com/shop/en/snapav/wattbox
[hacs]: https://hacs.xyz/
[blueprint]: https://github.com/custom-components/integration_blueprint
[buymecoffee]: https://www.buymeacoffee.com/eseglem
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow
[commits-shield]: https://img.shields.io/github/last-commit/eseglem/hass-wattbox
[commits]: https://github.com/eseglem/hass-wattbox/commits/master
[discord]: https://discord.gg/Qa5fW2R
[discord-shield]: https://img.shields.io/discord/330944238910963714
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/eseglem/hass-wattbox
[maintenance-shield]: https://img.shields.io/badge/maintainer-Erik%20Seglem%20%40Bedon292-blue
[hacs]: https://github.com/custom-components/hacs
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange
