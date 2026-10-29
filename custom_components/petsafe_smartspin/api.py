"""TinyTuya 3.5 status-only transport. No device control APIs are exposed."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import tinytuya

_IN_STATUS_WORKER: ContextVar[bool] = ContextVar(
    "smartspin_status_worker", default=False
)


class _WorkerPrivacyFilter(logging.Filter):
    """Drop SDK records only in our worker; leave other SDK users untouched."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not _IN_STATUS_WORKER.get()


_PRIVACY_FILTER = _WorkerPrivacyFilter()


def _guard_sdk_loggers() -> None:
    # Logger filters do not propagate to children. Attach to each SDK logger.
    # TinyTuya 1.20.0 eagerly imports its core modules before any device exists.
    for name in ("tinytuya", *tuple(logging.Logger.manager.loggerDict)):
        if name == "tinytuya" or name.startswith("tinytuya."):
            logging.getLogger(name).addFilter(_PRIVACY_FILTER)


@dataclass(frozen=True)
class Snapshot:
    """Validated values, not inferred appliance events."""

    status: str
    fault: int
    clean_control_state: str
    history_record: str
    visits_today: int
    last_seen: datetime


class StatusReadError(Exception):
    """Sanitized local transport or response failure."""


def parse_status(response: Any) -> Snapshot:
    """Reject malformed/partial status and SDK error dictionaries."""
    if not isinstance(response, Mapping) or any(
        k in response for k in ("Error", "Err", "error")
    ):
        raise StatusReadError("Invalid status response")
    dps = response.get("dps")
    if not isinstance(dps, Mapping):
        raise StatusReadError("Missing data points")
    values = {str(k): v for k, v in dps.items()}
    for key in ("7", "22"):
        if type(values.get(key)) is not int or values[key] < 0:
            raise StatusReadError("Invalid numeric data point")
    for key in ("24", "106", "107"):
        if not isinstance(values.get(key), str) or not values[key]:
            raise StatusReadError("Invalid state data point")
    return Snapshot(
        status=values["24"],
        fault=values["22"],
        clean_control_state=values["106"],
        history_record=values["107"],
        visits_today=values["7"],
        last_seen=datetime.now(UTC),
    )


class StatusDevice(tinytuya.Device):
    """Allow exactly one initial socket attempt with zero request retries.

    TinyTuya 1.20.0 shares socketRetryLimit between its initial connect loop
    (requires >=1) and request retry loop (must be 0). Restore it before the
    request loop processes any error. Do not override protocol commands.
    """

    def _get_socket(self, renew: bool) -> Any:
        retry_limit = self.socketRetryLimit
        self.socketRetryLimit = 1
        try:
            return super()._get_socket(renew)
        finally:
            self.socketRetryLimit = retry_limit


def poll_status(device_id: str, host: str, local_key: str) -> Snapshot:
    """Connect, read status once, close even on error; never leak SDK text."""
    _guard_sdk_loggers()
    token = _IN_STATUS_WORKER.set(True)
    device = None
    try:
        device = StatusDevice(
            device_id,
            address=host,
            local_key=local_key,
            version=3.5,
            connection_timeout=5,
            connection_retry_limit=0,
            persist=False,
        )
        return parse_status(device.status())
    except Exception:
        raise StatusReadError("SmartSpin local status read failed") from None
    finally:
        try:
            if device is not None:
                device.close()
        except Exception:
            # Cleanup must not leak SDK exception text or mask a valid response.
            pass
        finally:
            _IN_STATUS_WORKER.reset(token)
