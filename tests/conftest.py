"""Real Home Assistant fixtures; all network/device responses remain synthetic."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations_enabled(enable_custom_integrations):
    """Permit loading this repository's integration in the real HA fixture."""
    yield


@pytest.fixture(autouse=True)
def event_loop_debug_enabled(request):
    """Make the plugin's async autouse fixture safe for synchronous tests.

    The upstream Home Assistant test plugin declares
    ``enable_event_loop_debug`` as an *async* autouse fixture. pytest 9 raises
    ``PytestRemovedIn9Warning`` when a synchronous test depends on an async
    fixture that no plugin handled, which fails the whole session before any
    test body runs.

    That fixture only enables event-loop debug mode, so it is replaced with a
    synchronous no-op for the duration of each test. Event-loop debug mode is
    not required by this integration's assertions.
    """
    for fixturedef in request._fixturemanager.getfixturedefs(
        "enable_event_loop_debug", request._pyfuncitem
    ) or []:
        fixturedef.func = lambda *args, **kwargs: None
    yield
