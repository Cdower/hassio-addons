# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
#
# Cloudflare Access JWT verifier for the Calibre-Web Automated add-on.
#
# nginx's Access listener (:8085) sends every request through auth_request to
# this daemon (127.0.0.1:8086). We validate the Cf-Access-Jwt-Assertion token
# against the Zero Trust team's JWKS and return 200 with the authenticated
# email in X-Verified-User, or 401. Only the signed JWT is trusted — never
# Cloudflare's plain Cf-Access-Authenticated-User-Email header, which anything
# on the docker network could forge.

import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
from jwt import PyJWKClient

TEAM_DOMAIN = os.environ["CF_TEAM_DOMAIN"]
ACCESS_AUD = os.environ["CF_ACCESS_AUD"]
ISSUER = f"https://{TEAM_DOMAIN}.cloudflareaccess.com"
CERTS_URL = f"{ISSUER}/cdn-cgi/access/certs"
LISTEN = ("127.0.0.1", 8086)

# The email becomes an HTTP response header and then CWA's login username.
# Printable ASCII only, no whitespace/CR/LF (header injection), no ':'
# (header syntax), and exactly one '@' (both character classes exclude it);
# RFC-ish length caps. Keep in sync with setup_access.py.
EMAIL_RE = re.compile(r"^[!-9;-?A-~]{1,64}@[!-9;-?A-~]{1,255}$")

_jwks_lock = threading.Lock()
_jwks_client = None


def _jwks():
    # Created lazily so the add-on can start with no internet; PyJWKClient
    # caches the fetched key set (default 5 min) which also absorbs
    # Cloudflare's signing-key rotation.
    global _jwks_client
    with _jwks_lock:
        if _jwks_client is None:
            _jwks_client = PyJWKClient(CERTS_URL, cache_keys=True, timeout=10)
        return _jwks_client


def verify_token(token):
    """Return the validated email claim, or raise on any check failure."""
    if not token:
        raise ValueError("missing Cf-Access-Jwt-Assertion header")
    signing_key = _jwks().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=ACCESS_AUD,
        issuer=ISSUER,
        options={"require": ["exp", "iat", "aud", "iss"]},
        leeway=30,
    )
    email = (claims.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("token has no usable email claim (service token?)")
    return email


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _verify(self):
        try:
            email = verify_token(self.headers.get("Cf-Access-Jwt-Assertion", ""))
        except Exception as exc:  # noqa: BLE001 - any failure means 401
            print(f"[cwa-access-verifier] DENY: {exc}", file=sys.stderr, flush=True)
            self._reply(401, None)
            return
        self._reply(200, email)

    # nginx's auth_request is configured with proxy_method GET, but answer
    # every method identically in case that ever changes.
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _verify

    def _reply(self, code, email):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        if email:
            self.send_header("X-Verified-User", email)
        self.end_headers()

    def log_message(self, *args):  # nginx already logs; keep stdout quiet
        pass


def main():
    server = ThreadingHTTPServer(LISTEN, Handler)
    print(
        f"[cwa-access-verifier] listening on {LISTEN[0]}:{LISTEN[1]} "
        f"(issuer={ISSUER}, aud={ACCESS_AUD[:8]}…)",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
