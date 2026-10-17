"""The Integration Protocol parsers, without any I/O."""

import pytest

from custom_components.wattbox.api.protocol import (
    DO,
    DONT,
    IAC,
    SB,
    SE,
    WILL,
    WONT,
    LineBuffer,
    Request,
    TelnetFilter,
    parse_outlet_names,
    parse_power_status,
    parse_ups_status,
    split_unsolicited,
)


@pytest.mark.parametrize(
    ("command", "line", "accepted"),
    [
        ("?Firmware", "?Firmware=2.10.0.0", True),
        ("?Firmware", "?Firmware", False),  # the echo over SSH
        ("?Firmware", "?Model=WB-800-IPVM-12", False),
        ("?Firmware", "#Error", True),
        ("?Firmware", "OK", False),
        ("?OutletPowerStatus=1", "?OutletPowerStatus=1", False),  # the echo
        ("?OutletPowerStatus=1", "?OutletPowerStatus=1,0.82,0.00,118.96", True),
        ("?OutletPowerStatus=1", "?OutletPowerStatus=10,0.82,0.00,118.96", False),
        ("?OutletPowerStatus=2", "?OutletPowerStatus=1,0.82,0.00,118.96", False),
        ("!OutletSet=1,OFF,0", "OK", True),
        ("!OutletSet=1,OFF,0", "!OutletSet=1,OFF,0", False),
        ("!OutletSet=1,OFF,0", "#Error", True),
        ("!OutletSet=1,OFF,0", "?OutletStatus=1,1", False),
    ],
)
def test_request_accepts(command: str, line: str, accepted: bool) -> None:
    assert Request(command).accepts(line) is accepted


def test_request_value() -> None:
    assert Request("?OutletName").value("?OutletName={A=B},{C}") == "{A=B},{C}"
    assert Request("!OutletSet=1,ON,0").value("OK") == "OK"


def test_outlet_names_keep_spaces_and_commas() -> None:
    value = "{Hue Sync Power 1 to 3},{Apple TV, Office},{},{Router (Main)}"
    assert parse_outlet_names(value) == [
        "Hue Sync Power 1 to 3",
        "Apple TV, Office",
        "",
        "Router (Main)",
    ]


def test_outlet_names_without_braces() -> None:
    assert parse_outlet_names("One,Two") == ["One", "Two"]
    assert parse_outlet_names("") == []


def test_power_status_safe_voltage_is_inverted() -> None:
    status = parse_power_status("3.13,398.48,118.96,0")
    assert (status.current, status.power, status.voltage) == (3.13, 398.48, 118.96)
    assert status.safe_voltage is True
    assert parse_power_status("3.13,398.48,140.0,1").safe_voltage is False


def test_ups_status_without_a_ups() -> None:
    ups = parse_ups_status("0,0,Good,False,0,False,False")
    assert ups.battery_health is True
    assert ups.power_lost is False
    assert ups.battery_charge == 0


def test_split_unsolicited() -> None:
    assert split_unsolicited("~OutletStatus=1,0") == ("OutletStatus", "1,0")
    assert split_unsolicited("?OutletStatus=1,0") is None


def test_line_buffer_holds_partial_lines() -> None:
    buffer = LineBuffer()
    assert buffer.feed(b"?OutletName={Media Bri") == []
    assert buffer.feed(b"dge}\r\n?Firm") == ["?OutletName={Media Bridge}"]
    assert buffer.feed(b"ware=2.10\n\n") == ["?Firmware=2.10"]


def test_telnet_filter_refuses_options() -> None:
    telnet = TelnetFilter()
    payload, replies = telnet.feed(bytes([IAC, DO, 1, IAC, WILL, 3]) + b"OK\n")
    assert payload == b"OK\n"
    assert replies == bytes([IAC, WONT, 1, IAC, DONT, 3])


def test_telnet_filter_across_reads() -> None:
    telnet = TelnetFilter()
    assert telnet.feed(b"A" + bytes([IAC])) == (b"A", b"")
    assert telnet.feed(bytes([DO])) == (b"", b"")
    assert telnet.feed(bytes([24]) + b"B") == (b"B", bytes([IAC, WONT, 24]))


def test_telnet_filter_subnegotiation_and_escapes() -> None:
    telnet = TelnetFilter()
    data = bytes([IAC, SB, 24, 1, IAC, SE]) + b"x" + bytes([IAC, IAC]) + b"y"
    assert telnet.feed(data) == (b"x\xffy", b"")
