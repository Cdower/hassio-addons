"""Tests for the encrypted UDP protocol."""

from __future__ import annotations

import base64
import json

import pytest

from acpro_thermostat import protocol
from acpro_thermostat.protocol import ProtocolError


@pytest.mark.parametrize("version", [1, 2])
def test_encrypt_decrypt_round_trip(version: int) -> None:
    cipher = protocol.generic_cipher(version)
    payload = {"t": "status", "mac": "502cc6aabbcc", "cols": ["Pow", "Mod"]}

    pack, tag = cipher.encrypt(payload)

    assert cipher.decrypt(pack, tag) == payload


def test_v1_carries_no_tag_and_v2_does() -> None:
    assert protocol.generic_cipher(1).encrypt({"t": "scan"})[1] is None
    assert protocol.generic_cipher(2).encrypt({"t": "scan"})[1] is not None


def test_v1_uses_ecb_so_identical_blocks_repeat() -> None:
    """Guards the mode: ECB is what the firmware speaks, however dated it is."""
    cipher = protocol.generic_cipher(1)
    pack, _ = cipher.encrypt({"a": "0123456789abcdef0123456789abcdef"})
    raw = base64.b64decode(pack)

    assert len(raw) % 16 == 0


def test_v2_rejects_a_tampered_tag() -> None:
    cipher = protocol.generic_cipher(2)
    pack, tag = cipher.encrypt({"t": "status"})
    tampered = base64.b64encode(bytes(16)).decode()

    with pytest.raises(ProtocolError, match="tag does not verify"):
        cipher.decrypt(pack, tampered)


def test_v2_without_a_tag_is_rejected() -> None:
    cipher = protocol.generic_cipher(2)
    pack, _ = cipher.encrypt({"t": "status"})

    with pytest.raises(ProtocolError, match="missing its authentication tag"):
        cipher.decrypt(pack, None)


def test_v1_rejects_bad_padding() -> None:
    cipher = protocol.generic_cipher(1)

    with pytest.raises(ProtocolError):
        cipher.decrypt(base64.b64encode(bytes(16)).decode())


def test_decrypt_any_picks_the_scheme_that_works() -> None:
    ciphers = {version: protocol.generic_cipher(version) for version in (1, 2)}

    for version in (1, 2):
        pack, tag = ciphers[version].encrypt({"t": "dev", "mac": "abc"})
        envelope = {"pack": pack}
        if tag:
            envelope["tag"] = tag

        decoded, detected = protocol.decrypt_any(envelope, ciphers)

        assert detected == version
        assert decoded["mac"] == "abc"


def test_decrypt_any_reports_when_nothing_fits() -> None:
    ciphers = {1: protocol.generic_cipher(1)}

    with pytest.raises(ProtocolError, match="Could not decrypt"):
        protocol.decrypt_any({"pack": base64.b64encode(bytes(16)).decode()}, ciphers)


def test_decrypt_any_needs_a_pack() -> None:
    with pytest.raises(ProtocolError, match="no pack member"):
        protocol.decrypt_any({"t": "pack"}, {1: protocol.generic_cipher(1)})


def test_build_datagram_shape() -> None:
    cipher = protocol.generic_cipher(1)

    envelope = json.loads(
        protocol.build_datagram(cipher, {"t": "bind"}, tcid="502cc6aabbcc", i=1)
    )

    assert envelope["t"] == "pack"
    assert envelope["i"] == 1
    assert envelope["cid"] == "app"
    assert envelope["tcid"] == "502cc6aabbcc"
    assert "tag" not in envelope
    assert cipher.decrypt(envelope["pack"]) == {"t": "bind"}


def test_build_datagram_includes_the_v2_tag() -> None:
    envelope = json.loads(protocol.build_datagram(protocol.generic_cipher(2), {"t": "bind"}))

    assert "tag" in envelope


def test_parse_envelope_rejects_junk() -> None:
    with pytest.raises(ProtocolError, match="not JSON"):
        protocol.parse_envelope(b"\xff\xfe not json")

    with pytest.raises(ProtocolError, match="not a JSON object"):
        protocol.parse_envelope(b"[1, 2, 3]")


def test_scan_datagram_is_plaintext() -> None:
    assert json.loads(protocol.SCAN_DATAGRAM) == {"t": "scan"}


def test_keys_must_be_the_right_length() -> None:
    with pytest.raises(ValueError, match="16 bytes"):
        protocol.make_cipher(b"too-short", 1)


def test_unknown_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown encryption version"):
        protocol.make_cipher(protocol.GENERIC_KEY_V1, 3)
