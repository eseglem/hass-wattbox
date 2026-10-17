"""Errors raised by the WattBox client.

Grouped by what the caller should do about them, not by transport: the
integration needs to tell "ask for new credentials" apart from "mark the
device unavailable and try again later", whichever interface failed.
"""

from __future__ import annotations


class WattBoxError(Exception):
    """Base class for every error this client raises."""


class WattBoxConnectionError(WattBoxError):
    """The device could not be reached, or stopped answering mid-exchange."""


class WattBoxAuthError(WattBoxError):
    """The device rejected the credentials."""


class WattBoxLoggedOut(WattBoxError):
    """An HTTP device served a page that is not its status data.

    Usually the login page, which the web UI serves with a ``200 OK`` instead
    of an error status. On a session that has been running for a while it
    tends to mean the device forgot the session, not that the credentials are
    wrong, so it is kept apart from :class:`WattBoxAuthError`.
    """


class WattBoxCommandError(WattBoxError):
    """The device answered a request with ``#Error``."""


class WattBoxProtocolError(WattBoxError):
    """The device answered with something this client cannot interpret."""
