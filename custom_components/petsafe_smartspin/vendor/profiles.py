"""No application identities are distributed with this integration."""

from enum import StrEnum


class TuyaMobileApp(StrEnum):
    """Compatibility placeholder; no bundled applications."""


def get_mobile_app_profile(application):
    raise ValueError("Bundled application profiles are not supported")


def _is_bundled_mobile_app_profile(profile):
    return False
