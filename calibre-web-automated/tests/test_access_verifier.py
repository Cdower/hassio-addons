# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
#
# Offline tests for the Cloudflare Access JWT verifier
# (rootfs/opt/cwa-access/verifier.py).
#
# No network access: the JWKS client is replaced with a stub returning a
# locally generated RSA public key, and requests are made over a loopback
# server on an ephemeral port. Requires PyJWT + cryptography (see ci.yaml).
#
# Run directly:   python3 calibre-web-automated/tests/test_access_verifier.py
# Or via pytest:  pytest calibre-web-automated/tests/test_access_verifier.py

import datetime
import http.client
import importlib.util
import os
import threading
import unittest
from http.server import ThreadingHTTPServer

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.dirname(HERE)
VERIFIER_PATH = os.path.join(ADDON_ROOT, "rootfs", "opt", "cwa-access", "verifier.py")

TEAM = "testteam"
AUD = "a" * 64
ISSUER = f"https://{TEAM}.cloudflareaccess.com"


def _load_verifier():
    os.environ["CF_TEAM_DOMAIN"] = TEAM
    os.environ["CF_ACCESS_AUD"] = AUD
    spec = importlib.util.spec_from_file_location("cwa_access_verifier", VERIFIER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = _load_verifier()

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _StubSigningKey:
    key = KEY.public_key()


class _StubJWKClient:
    def get_signing_key_from_jwt(self, token):
        return _StubSigningKey()


def _claims(**overrides):
    now = datetime.datetime.now(datetime.timezone.utc)
    claims = {
        "aud": AUD,
        "iss": ISSUER,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=5),
        "email": "Alice@Gmail.com",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _token(signing_key=KEY, **overrides):
    return jwt.encode(_claims(**overrides), signing_key, algorithm="RS256")


class VerifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        verifier._jwks_client = _StubJWKClient()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), verifier.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _request(self, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if token is not None:
            headers["Cf-Access-Jwt-Assertion"] = token
        conn.request("GET", "/", headers=headers)
        response = conn.getresponse()
        response.read()
        result = (response.status, response.getheader("X-Verified-User"))
        conn.close()
        return result

    def test_valid_token_returns_lowercased_email(self):
        status, user = self._request(_token())
        self.assertEqual(status, 200)
        self.assertEqual(user, "alice@gmail.com")

    def test_missing_header_denied(self):
        status, user = self._request(None)
        self.assertEqual((status, user), (401, None))

    def test_bad_signature_denied(self):
        status, user = self._request(_token(signing_key=OTHER_KEY))
        self.assertEqual((status, user), (401, None))

    def test_wrong_audience_denied(self):
        status, user = self._request(_token(aud="b" * 64))
        self.assertEqual((status, user), (401, None))

    def test_wrong_issuer_denied(self):
        status, user = self._request(_token(iss="https://evil.cloudflareaccess.com"))
        self.assertEqual((status, user), (401, None))

    def test_expired_token_denied(self):
        past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        status, user = self._request(
            _token(iat=past, exp=past + datetime.timedelta(minutes=5))
        )
        self.assertEqual((status, user), (401, None))

    def test_missing_expiry_denied(self):
        status, user = self._request(_token(exp=None))
        self.assertEqual((status, user), (401, None))

    def test_missing_email_denied(self):
        # Service tokens authenticate without an email claim; there is no CWA
        # user to map them to, so they must be denied.
        status, user = self._request(_token(email=None))
        self.assertEqual((status, user), (401, None))

    def test_header_injection_email_denied(self):
        for evil in (
            "a@b.com\r\nX-Injected: 1",
            "a@b.com\nX-Injected: 1",
            "a b@c.com",
            "a@b:8080",
            "no-at-sign",
            "two@at@signs",
            "unicode@exämple.com",
        ):
            status, user = self._request(_token(email=evil))
            self.assertEqual((status, user), (401, None), msg=repr(evil))

    def test_alg_none_denied(self):
        token = jwt.encode(_claims(), key=None, algorithm="none")
        status, user = self._request(token)
        self.assertEqual((status, user), (401, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
