#!/usr/bin/env python3
"""Statically derive a PRIVATE OEM profile from a user-supplied Companion APK.

No application or vendor native code is executed. Requires the optional tools
requirements, not the Home Assistant runtime requirements. No signing constants
are bundled with this script. A valid APK signature is not proof of publisher
identity: the caller must trust/corroborate the source and certificate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import zipfile
from fractions import Fraction
from pathlib import Path

PACKAGE = "net.petsafe.petsafelitterbox"


def decode_signer_token(blob: bytes, app_id: str) -> str:
    """Decode the BMP coefficient format using rational interpolation at zero."""
    if len(blob) < 54 or blob[:2] != b"BM":
        raise ValueError("Unsupported signing-resource format")
    offset = struct.unpack_from("<I", blob, 10)[0]
    if offset < 54 or offset >= len(blob):
        raise ValueError("Invalid signing-resource pixel offset")
    pixels = blob[offset:]
    size = len(pixels)
    java_hash = 0
    for character in app_id:
        java_hash = (31 * java_hash + ord(character)) & 0xFFFFFFFF
    if java_hash >= 2**31:
        java_hash -= 2**32
    start = abs(java_hash) % size // 2

    def read(at: int, length: int) -> bytes:
        return bytes(pixels[(at + index) % size] for index in range(length))

    keys = pixels[(start + 1) % size]
    coefficients = pixels[(start + 2) % size]
    if keys != 1 or not 1 <= coefficients <= 64:
        raise ValueError("Unsupported signing-resource coefficients or application ID")
    location = start ^ int.from_bytes(read(start + 3, 4), "big")
    points = []
    for _ in range(coefficients):
        first = location % size
        x_length = pixels[first]
        if not 1 <= x_length <= 128:
            raise ValueError("Invalid signing-resource point")
        x = int.from_bytes(read(first + 1, x_length), "big")
        second = (first + x_length + 1) % size
        y_length = pixels[second]
        if not 1 <= y_length <= 128:
            raise ValueError("Invalid signing-resource point")
        y = int.from_bytes(read(second + 1, y_length), "big")
        following = (second + y_length + 1) % size
        location = first ^ int.from_bytes(read(following, 4), "big")
        points.append((x, y))
    if len({x for x, _ in points}) != len(points):
        raise ValueError("Duplicate signing-resource points")
    value = Fraction(0)
    for index, (x, y) in enumerate(points):
        term = Fraction(y)
        for other_index, (other_x, _) in enumerate(points):
            if index != other_index:
                term *= Fraction(-other_x, x - other_x)
        value += term
    if value.denominator != 1 or value.numerator <= 0:
        raise ValueError("Invalid signing-resource interpolation")
    number = value.numerator
    token = number.to_bytes((number.bit_length() + 7) // 8, "big").decode("ascii")
    if len(token) != 32:
        raise ValueError("Unsupported signing-token length")
    return token


def field_values(cls) -> dict:
    """Read encoded DEX constants; never run class initializers."""
    out = {}
    for field in cls.get_fields():
        initial = field.get_init_value()
        if initial is not None:
            value = initial.get_value()
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            out[field.get_name()] = value
    return out


def method_version(cls, name: str) -> str | None:
    for method in cls.get_methods():
        if method.get_name() != name:
            continue
        for instruction in method.get_instructions():
            if not instruction.get_name().startswith("const-string"):
                continue
            for operand in instruction.get_operands():
                for value in operand:
                    if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+", value):
                        return value
    return None


def verify_signature(apk_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "apksigtool", "verify", str(apk_path)],
        capture_output=True, text=True, timeout=90, check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode or not re.search(r"v[23] verified", output):
        raise ValueError("APK v2/v3 signature verification failed; no profile written")


def extract_profile(apk_path: Path, expected_certificate: str | None = None) -> dict:
    if apk_path.stat().st_size > 300 * 1024 * 1024:
        raise ValueError("APK exceeds the analysis size bound")
    with zipfile.ZipFile(apk_path) as archive:
        if "AndroidManifest.xml" not in archive.namelist():
            raise ValueError("A standalone APK is required, not an XAPK/APKS archive")
        if sum(info.file_size for info in archive.infolist()) > 1024 * 1024 * 1024:
            raise ValueError("Expanded APK exceeds the analysis size bound")
    verify_signature(apk_path)
    # Optional heavy dependencies are imported only for actual APK analysis.
    from loguru import logger
    logger.remove()
    from androguard.core.apk import APK
    from androguard.core.dex import DEX

    apk = APK(str(apk_path))
    if apk.get_package() != PACKAGE:
        raise ValueError("APK is not the expected Companion package")
    certificates = apk.get_certificates_der_v2() + apk.get_certificates_der_v3()
    hashes = {hashlib.sha256(cert).hexdigest() for cert in certificates}
    if len(hashes) != 1:
        raise ValueError("Expected one consistent APK signer certificate")
    certificate = next(iter(hashes))
    if expected_certificate:
        expected = expected_certificate.replace(":", "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or certificate != expected:
            raise ValueError("APK signer does not match the supplied trusted fingerprint")
    targets = {
        "Lcom/thingclips/sample/BuildConfig;": None,
        "Lcom/thingclips/sdk/devicecore/BuildConfig;": None,
        "Lcom/thingclips/smart/sdk/ThingSdk;": None,
    }
    app_fields = None
    device_fields = None
    sdk_version = None
    for blob in apk.get_all_dex():
        vm = DEX(blob)
        for cls in vm.get_classes():
            name = cls.get_name()
            if name == "Lcom/thingclips/sample/BuildConfig;":
                app_fields = field_values(cls)
                targets[name] = True
            elif name == "Lcom/thingclips/sdk/devicecore/BuildConfig;":
                device_fields = field_values(cls)
                targets[name] = True
            elif name == "Lcom/thingclips/smart/sdk/ThingSdk;":
                sdk_version = method_version(cls, "getSdkVersion")
                targets[name] = True
        if all(targets.values()):
            break
    if not app_fields or not device_fields or not sdk_version:
        raise ValueError("Unsupported application/SDK layout; required fields not found")
    app_id = app_fields.get("THING_SMART_APPKEY")
    secret = app_fields.get("THING_SMART_SECRET")
    ttid = app_fields.get("THING_SMART_TTID")
    core_version = device_fields.get("VERSION_NAME")
    if not all(isinstance(x, str) and x for x in (app_id, secret, ttid, core_version)):
        raise ValueError("Required production application constants are missing")
    if len(app_id) != 20 or len(secret) != 32:
        raise ValueError("Unsupported application identity format")
    token = decode_signer_token(apk.get_file("assets/t_s.bmp"), app_id)
    return {
        "name": f"User-supplied Companion {apk.get_androidversion_name()}",
        "app_id": app_id, "app_secret": secret, "cert_sha256_hex": certificate,
        "app_key": token, "package": PACKAGE,
        "app_version": apk.get_androidversion_name(), "ttid": ttid,
        "sdk_version": sdk_version, "device_core_version": core_version,
    }


def write_private_profile(output: Path, profile: dict) -> None:
    repository = Path(__file__).resolve().parents[1]
    if output.resolve().is_relative_to(repository):
        raise ValueError("Write the private profile outside this public repository")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(profile, stream, indent=2)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-certificate", help="Independently trusted SHA256 fingerprint")
    args = parser.parse_args()
    try:
        profile = extract_profile(args.apk, args.expected_certificate)
        write_private_profile(args.output, profile)
    except Exception:
        # Avoid putting resource/DEX strings or extracted values in a traceback.
        print("Static extraction failed; no profile was published. Check the APK source, "
              "layout, signature, optional dependencies, and output location.", file=sys.stderr)
        return 1
    print(f"Created private profile for {profile['package']} {profile['app_version']}; "
          "values were not printed. Keep the file private.")
    print("Signature checks passed; publisher authenticity still depends on trusted provenance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
