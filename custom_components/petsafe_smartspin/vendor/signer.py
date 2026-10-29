"""Pure-Python reimplementation of Tuya's ``thing_security`` mobile signer.

Implements the Tuya mobile signing scheme:
computes three things, and all three are plain HMAC-SHA256 / SHA256 over ASCII
inputs — there is no whitebox cipher and no native dependency. This lets any
Tuya *mobile* app's API be called with no external signer, no qemu, and no
native blobs.

Everything hangs off one "global key material" string::

    G = package + "_" + colon_hex(cert) + "_" + app_key + "_" + app_secret

Primitives (ASCII in/out):

* ``channel_key()`` -> ``HMAC_SHA256(app_id, package + "_" + colon_hex(cert)).hex()[8:16]``
* ``derive_key(request_id, ecode)`` -> 16-byte AES key = ASCII of
  ``HMAC_SHA256(request_id, G [+ "_" + ecode]).hex()[:16]``
* ``sign(canonical)`` -> ``HMAC_SHA256(SHA256(G), canonical).hex()``

The signer is **parameterized by the app's Tuya application credentials**
(``app_id``, ``app_secret``, ``cert_sha256_hex``, ``app_key``, ``package``).
These are constant per app (extracted from that app's APK) and are the only
app-specific inputs — the algorithm itself is generic across Tuya apps.
"""
from __future__ import annotations

import hashlib
import hmac


class NativeSignerError(RuntimeError):
    """A configured external signer failed or returned invalid output."""


def colon_hex(cert_sha256_hex: str) -> str:
    """Render a cert SHA-256 as uppercase, colon-separated hex (Android style)."""
    h = cert_sha256_hex.replace(":", "").strip()
    return ":".join(h[i : i + 2] for i in range(0, len(h), 2)).upper()


class PurePythonTuyaSigner:
    """Drop-in ``thing_security`` signer implemented in pure Python."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        cert_sha256_hex: str,
        app_key: str,
        package: str,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.cert_sha256_hex = cert_sha256_hex
        self.app_key = app_key
        self.package = package

    # -- internal helpers ------------------------------------------------
    def cert_msg(self) -> str:
        return f"{self.package}_{colon_hex(self.cert_sha256_hex)}"

    def global_material(self) -> str:
        """The shared "global key material" string G."""
        return f"{self.cert_msg()}_{self.app_key}_{self.app_secret}"

    def _signing_key(self) -> bytes:
        return hashlib.sha256(self.global_material().encode()).digest()

    # -- public interface ------------------------------------------------
    def sign(self, canonical: str) -> str:
        """Sign a canonical request string -> lowercase hex HMAC-SHA256."""
        return hmac.new(
            self._signing_key(), canonical.encode(), hashlib.sha256
        ).hexdigest()

    def derive_key(self, request_id: str, ecode: str | None) -> bytes:
        """Return the 16-byte per-request AES key."""
        g = self.global_material()
        message = g if not ecode else f"{g}_{ecode}"
        digest = hmac.new(
            request_id.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        return digest[:16].encode()

    def channel_key(self) -> str:
        """Return the account/app-global channel key (chKey)."""
        return hmac.new(
            self.app_id.encode(), self.cert_msg().encode(), hashlib.sha256
        ).hexdigest()[8:16]


