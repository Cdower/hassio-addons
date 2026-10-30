"""Check that Tailscale tarballs were signed by Tailscale (distsign).

Usage: verify-tailscale.py ROOTS_DIR SIGNING_KEYS PACKAGE...

ROOTS_DIR holds Tailscale's committed root public keys (*.pem).
SIGNING_KEYS is a downloaded distsign.pub; its signature must be beside it as
distsign.pub.sig and must validate with one of the root keys. Each PACKAGE
must have its signature beside it as PACKAGE.sig and validate with one of the
signing keys. The signed message is the package's BLAKE2s-256 hash followed by
its length as a little-endian uint64. See .github/tailscale/README.md.

Ed25519 checks run through the openssl CLI, so this needs only the standard
library and nothing installed from a package index. Exits non-zero on the
first failure. Used by .github/workflows/tailscale.yaml.
"""

import base64
import glob
import hashlib
import os
import struct
import subprocess
import sys
import tempfile

# DER prefix of an Ed25519 SubjectPublicKeyInfo; the 32 raw key bytes follow.
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def parse_keys(text, label, source):
    """Return the raw Ed25519 keys in every PEM block of the given label."""
    keys = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != f"-----BEGIN {label}-----":
            continue
        body = []
        for following in lines[i + 1 :]:
            if following.strip() == f"-----END {label}-----":
                break
            body.append(following.strip())
        else:
            sys.exit(f"::error::Unterminated {label} block in {source}")
        raw = base64.b64decode("".join(body), validate=True)
        if len(raw) != 32:
            sys.exit(f"::error::{source} has a {label} that is not 32 bytes")
        keys.append(raw)
    if not keys:
        sys.exit(f"::error::No {label} found in {source}")
    return keys


def verify_any(keys, message, signature, workdir):
    """True if any key in keys made signature over message."""
    if len(signature) != 64:
        return False
    msg_path = os.path.join(workdir, "msg")
    sig_path = os.path.join(workdir, "sig")
    key_path = os.path.join(workdir, "key.der")
    with open(msg_path, "wb") as handle:
        handle.write(message)
    with open(sig_path, "wb") as handle:
        handle.write(signature)
    for key in keys:
        with open(key_path, "wb") as handle:
            handle.write(ED25519_SPKI_PREFIX + key)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                key_path,
                "-keyform",
                "DER",
                "-rawin",
                "-in",
                msg_path,
                "-sigfile",
                sig_path,
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return True
    return False


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    roots_dir, signing_keys, *packages = sys.argv[1:]

    roots = []
    for path in sorted(glob.glob(os.path.join(roots_dir, "*.pem"))):
        roots += parse_keys(read(path).decode(), "ROOT PUBLIC KEY", path)
    if not roots:
        sys.exit(f"::error::No root keys in {roots_dir}")

    with tempfile.TemporaryDirectory() as workdir:
        bundle = read(signing_keys)
        if not verify_any(roots, bundle, read(signing_keys + ".sig"), workdir):
            sys.exit(
                f"::error::{signing_keys} does not validate with any root"
                f" key in {roots_dir}. Either the download was tampered"
                " with or Tailscale rotated its root keys; see"
                " .github/tailscale/README.md."
            )
        signing = parse_keys(bundle.decode(), "SIGNING PUBLIC KEY", signing_keys)
        print(
            f"{os.path.basename(signing_keys)}: {len(signing)} signing"
            " key(s), signed by a committed root key"
        )

        for package in packages:
            data = read(package)
            message = hashlib.blake2s(data).digest() + struct.pack("<Q", len(data))
            if not verify_any(signing, message, read(package + ".sig"), workdir):
                sys.exit(
                    f"::error::{os.path.basename(package)} is not signed"
                    " by a current Tailscale signing key"
                )
            print(f"{os.path.basename(package)}: signature OK")


if __name__ == "__main__":
    main()
