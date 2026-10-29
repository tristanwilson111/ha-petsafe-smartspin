"""Repository-root pytest configuration.

Ensures the repository root is importable so tests can import
``custom_components.petsafe_smartspin`` directly, and keeps the Home Assistant
test plugin's async autouse fixture safe for synchronous tests.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
