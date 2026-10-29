"""Real Home Assistant fixtures; all network/device responses remain synthetic."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations_enabled(enable_custom_integrations):
    """Permit loading this repository's integration in the real HA fixture."""
    yield
