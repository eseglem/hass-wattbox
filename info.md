[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[![Discord][discord-shield]][discord]
[![Community Forum][forum-shield]][forum]

_Component to integrate with [WattBox][wattbox]._

This component should work with or without a battery. It reports all values available in the API, and creates outlets for each plug based on the API return.

It also creates a master switch that should function the same as the master switch on the unit. It will turn on / off all the switches that the physical switch on the box does. You can config that through the UI on the wattbox directly. I have not found an API to control it yet.

Be careful, if the WattBox controls the power to its own networking equipment you can turn it off and not have remote access until you fix it. You may even have to plug it in elsewhere to get back online and turn that outlet back on in HA.


{% if not installed %}
## Installation

1. Click install.
1. Configure via `configuration.yaml`

```
wattbox:
- host: [IP ADDRESS OF WATTBOX]
  name: [OPTIONAL: Default wattbox]
  username: [OPTIONAL: Default wattbox]
  password: [OPTIONAL: Default wattbox]
```

{% endif %}

<!---->

***

[wattbox]: https://www.snapav.com/shop/en/snapav/wattbox
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
