"""Wire protocol spoken by the AC Pro smart communicating control.

The control (AC Pro SKU 85432 / OEM model WK-010WD1) is a Gree-family Wi-Fi
module: it listens for JSON datagrams on UDP/7000 and answers on the source
port.  Every datagram carries an encrypted ``pack`` member; the surrounding
envelope is plaintext.

Two encryption schemes exist in the wild and the control may use either
depending on its firmware:

``v1``
    AES-128-ECB with PKCS#7 padding, base64 encoded.  Discovery and binding
    use a fixed key shared by every device; afterwards each device issues a
    per-device key during binding.

``v2``
    AES-128-GCM with a fixed IV and associated data.  The authentication tag
    travels next to ``pack`` in a ``tag`` member.

Both schemes are implemented and :func:`decrypt_any` picks whichever one
actually decodes, so the add-on does not have to be told up front.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher as _Cipher
from cryptography.hazmat.primitives.ciphers import algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_LOGGER = logging.getLogger(__name__)

#: Default UDP port the control listens on.
DEFAULT_PORT = 7000

#: Shared key used until the control hands out a per-device key (v1 devices).
GENERIC_KEY_V1 = b"a3K8Bx%2r8Y7#xDh"

#: Shared key used until the control hands out a per-device key (v2 devices).
GENERIC_KEY_V2 = b"{yxAHAY_Lm6pbC/<"

#: Fixed IV and associated data baked into the v2 firmware.
GCM_IV = bytes.fromhex("5440784449675a516c5e6313")
GCM_AAD = b"qualcomm-test"

_BLOCK_SIZE = 16


class ProtocolError(Exception):
    """Raised when a datagram cannot be decoded or the control reports failure."""


def _pad(data: bytes) -> bytes:
    """Apply PKCS#7 padding to a full block boundary."""
    padding = _BLOCK_SIZE - (len(data) % _BLOCK_SIZE)
    return data + bytes([padding]) * padding


def _unpad(data: bytes) -> bytes:
    """Strip PKCS#7 padding, rejecting anything malformed."""
    if not data or len(data) % _BLOCK_SIZE:
        raise ProtocolError("Ciphertext is not a whole number of AES blocks")
    padding = data[-1]
    if not 1 <= padding <= _BLOCK_SIZE or data[-padding:] != bytes([padding]) * padding:
        raise ProtocolError("Invalid PKCS#7 padding")
    return data[:-padding]


class Cipher:
    """Encrypts and decrypts the ``pack`` member of a datagram."""

    version: int

    def __init__(self, key: bytes) -> None:
        if len(key) != _BLOCK_SIZE:
            raise ValueError(f"Key must be {_BLOCK_SIZE} bytes, got {len(key)}")
        self.key = key

    def encrypt(self, payload: dict[str, Any]) -> tuple[str, str | None]:
        """Return the base64 ``pack`` and, for v2, its base64 ``tag``."""
        raise NotImplementedError

    def decrypt(self, pack: str, tag: str | None = None) -> dict[str, Any]:
        """Return the decoded JSON object carried by ``pack``."""
        raise NotImplementedError

    @staticmethod
    def _to_json(plaintext: bytes) -> dict[str, Any]:
        try:
            decoded = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ProtocolError(f"Decrypted pack is not JSON: {err}") from err
        if not isinstance(decoded, dict):
            raise ProtocolError("Decrypted pack is not a JSON object")
        return decoded

    @staticmethod
    def _b64decode(value: str, what: str) -> bytes:
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError, TypeError) as err:
            raise ProtocolError(f"{what} is not valid base64: {err}") from err


class CipherV1(Cipher):
    """AES-128-ECB with PKCS#7 padding."""

    version = 1

    def encrypt(self, payload: dict[str, Any]) -> tuple[str, str | None]:
        encryptor = _Cipher(algorithms.AES(self.key), modes.ECB()).encryptor()
        raw = _pad(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        return base64.b64encode(encryptor.update(raw) + encryptor.finalize()).decode(), None

    def decrypt(self, pack: str, tag: str | None = None) -> dict[str, Any]:
        decryptor = _Cipher(algorithms.AES(self.key), modes.ECB()).decryptor()
        raw = self._b64decode(pack, "pack")
        return self._to_json(_unpad(decryptor.update(raw) + decryptor.finalize()))


class CipherV2(Cipher):
    """AES-128-GCM with the fixed IV and associated data used by the firmware."""

    version = 2

    def encrypt(self, payload: dict[str, Any]) -> tuple[str, str | None]:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        sealed = AESGCM(self.key).encrypt(GCM_IV, raw, GCM_AAD)
        ciphertext, tag = sealed[:-16], sealed[-16:]
        return base64.b64encode(ciphertext).decode(), base64.b64encode(tag).decode()

    def decrypt(self, pack: str, tag: str | None = None) -> dict[str, Any]:
        if not tag:
            raise ProtocolError("v2 datagram is missing its authentication tag")
        sealed = self._b64decode(pack, "pack") + self._b64decode(tag, "tag")
        try:
            plaintext = AESGCM(self.key).decrypt(GCM_IV, sealed, GCM_AAD)
        except InvalidTag as err:
            raise ProtocolError("v2 authentication tag does not verify") from err
        return self._to_json(plaintext)


def make_cipher(key: bytes | str, version: int) -> Cipher:
    """Build the cipher for ``version`` (1 or 2)."""
    if isinstance(key, str):
        key = key.encode("utf-8")
    if version == 1:
        return CipherV1(key)
    if version == 2:
        return CipherV2(key)
    raise ValueError(f"Unknown encryption version {version}")


def generic_cipher(version: int) -> Cipher:
    """Build the pre-binding cipher for ``version``, which uses the shared key."""
    return make_cipher(GENERIC_KEY_V1 if version == 1 else GENERIC_KEY_V2, version)


def decrypt_any(
    envelope: dict[str, Any],
    ciphers: dict[int, Cipher],
) -> tuple[dict[str, Any], int]:
    """Decrypt ``envelope`` with whichever of ``ciphers`` works.

    Returns the decoded pack and the encryption version that succeeded, so the
    caller can pin every later exchange to the same scheme.
    """
    pack = envelope.get("pack")
    if not isinstance(pack, str):
        raise ProtocolError("Datagram has no pack member")
    tag = envelope.get("tag")

    # A v2 datagram always carries a tag, so try that scheme first when one is
    # present and the v1 scheme first when one is not.
    preferred = [2, 1] if tag else [1, 2]
    order = [version for version in preferred if version in ciphers]

    errors: list[str] = []
    for version in order:
        try:
            return ciphers[version].decrypt(pack, tag), version
        except ProtocolError as err:
            errors.append(f"v{version}: {err}")
    raise ProtocolError(f"Could not decrypt datagram ({'; '.join(errors)})")


def build_datagram(
    cipher: Cipher,
    payload: dict[str, Any],
    *,
    tcid: str = "",
    i: int = 0,
) -> bytes:
    """Wrap ``payload`` in an encrypted envelope ready to put on the wire.

    ``i`` is 1 for the pre-binding handshake (the control answers with the
    shared key) and 0 once a per-device key is in use.
    """
    pack, tag = cipher.encrypt(payload)
    envelope: dict[str, Any] = {
        "cid": "app",
        "i": i,
        "t": "pack",
        "uid": 0,
        "tcid": tcid,
        "pack": pack,
    }
    if tag is not None:
        envelope["tag"] = tag
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")


def parse_envelope(raw: bytes) -> dict[str, Any]:
    """Decode the plaintext envelope of a received datagram."""
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ProtocolError(f"Datagram is not JSON: {err}") from err
    if not isinstance(envelope, dict):
        raise ProtocolError("Datagram is not a JSON object")
    return envelope


#: Plaintext discovery probe.  Broadcast it and every control on the segment
#: answers with an envelope encrypted under the shared key.
SCAN_DATAGRAM = json.dumps({"t": "scan"}, separators=(",", ":")).encode("utf-8")
