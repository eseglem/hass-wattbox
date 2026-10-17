[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[![Discord][discord-shield]][discord]
[![Community Forum][forum-shield]][forum]

# hass-wattbox

[Home Assistant](home-assistant) Custom Component to integrate with [WattBox][wattbox].

Easiest way to install this component is through [HACS][hacs].

## Configuration

### UI Configuration (Recommended)

1. Go to **Settings → Devices & services**
2. Click **Add Integration** and search for **WattBox**
3. Enter your WattBox connection details:
   - **Host**: IP address of your WattBox
   - **Connection type**: how to talk to it (see below)
   - **Username** / **Password**: the WattBox's own login (default: `wattbox` / `wattbox`)
   - **Name**: friendly name for the device and its entities
   - **Skip outlets matching** (optional): a regular expression for outlets that must never get a switch or reset button, such as the one powering your router
   - **Per-outlet metering** (optional, telnet/SSH only): power, current and voltage sensors for each outlet

| Series | Connection type | Notes |
| --- | --- | --- |
| 800 (WB-800-IPVM, WB-800VPS-IPVM, …) | **Telnet** (port 23) | The 800 series has no HTTP API: it rejects every HTTP login with `401`. Its SSH port is reserved for OvrC and normally rejects the device's own credentials. |
| 150, 250, 300, 700 | **HTTP** (port 80) | Reports power for the unit as a whole, not per outlet. |

Each WattBox appears as a **device** in Home Assistant with all of its entities grouped under it. Telnet and SSH connections push outlet changes to Home Assistant as the WattBox reports them, without waiting for the next poll.

### YAML Configuration (Legacy)

Configuration through `configuration.yaml` is still supported for backward compatibility.

Example Config:

```yaml
wattbox:
- name: WattBox-HTTP
  host: !secret wattbox1_ip
  port: 80
  username: !secret wattbox1_username
  password: !secret wattbox1_password
  name_regexp: "^Fixed Prefix (.*)$"
  skip_regexp: "SKIP"
  scan_interval: 00:00:10
- name: WattBox-SSH
  host: !secret wattbox2_ip
  port: 22
  username: !secret wattbox2_username
  password: !secret wattbox2_password
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

- **`host`**: Host IP of the WattBox (Required)
- **`name`**: Name for the WattBox (Default WattBox)
- **`port`**: `80` for HTTP, `23` for telnet, `22` for SSH (Default 80)
- **`username`**: Username for authentication (Default wattbox)
- **`password`**: Password for authentication (Default wattbox)
- **`scan_interval`**: A time interval run updates at (Default 30s, format HH:MM:SS)
- **`resources`**: A list of resources to enable (Default all of them)
- **`name_regexp`**: A regexp to extract the name to use for the outlet instead of just the index. If there is a match group, it is used, else the whole match is used.
- **`skip_regexp`**: A regexp to use that, if the outlet name matches, the outlet is not added as a switch entity.

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

Be careful, if the WattBox controls the power to its own networking equipment you can turn it off and not have remote access until you fix it. You may even have to plug it in elsewhere to get back online and turn that outlet back on in HA. You can use the `skip_regexp` option for those outlets.

Master switch will turn on / off all the switches that the physical switch on the box does. You can config that through the UI on the wattbox directly. If ALL of the switches controlled by Master are on, then Master will be on. Otherwise it will be off. If any outlets on a wattbox are skipped via `skip_regexp` then
the master switch for that wattbox will also not be added as an entity.

## Troubleshooting

- **"The WattBox rejected the login: … answered 401"** on an 800-series unit: pick **Telnet**. The 800 series has no HTTP API.
- **"… closed the connection before logging in"**: the WattBox already has as many sessions open as it allows. This integration keeps one session per device and closes it on reload and shutdown. If other systems (Control4, OvrC, scripts) also connect, close those or wait for the device to time them out.
- **"… answered, but not with the WattBox status data"**: the HTTP interface served a page that is not its data, which almost always means the credentials were not accepted.
- When reporting a bug, enable debug logging and attach the **diagnostics** download from the device page (credentials, host and serial number are redacted):

  ```yaml
  logger:
    logs:
      custom_components.wattbox: debug
  ```

## Development

The integration talks to the WattBox through its own small client in `custom_components/wattbox/api/`, which has no Home Assistant imports. It replaced [pywattbox](https://github.com/eseglem/pywattbox), whose IP driver was built on scrapli and stopped importing once scrapli 2 was released.

```shell
scripts/setup                 # install requirements.txt
python -m pytest tests        # unit and Home Assistant tests, against simulated WattBoxes
python -m tests.simulator     # a simulated 800 (telnet, port 2323) and 300 (HTTP, port 8080)
sudo python scripts/e2e.py    # boots a real Home Assistant against the simulators
```

`tests/simulator.py` is modelled on wire captures from real hardware (see #55 and #66). It is not a substitute for testing on a real WattBox before a release.

Based on: [ludeeus/integration_blueprint][blueprint]

<!---->

---

[wattbox]: https://www.snapav.com/shop/en/snapav/wattbox
[hacs]: https://hacs.xyz/
[blueprint]: https://github.com/ludeeus/integration_blueprint
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
[home-assistant]: https://github.com/home-assistant/core
