---
name: update-base-image
description: Bump the calibre-web-automated add-on to a new upstream crocodilestick/calibre-web-automated base image tag. Re-diffs every file this add-on overrides in the image and re-verifies the upstream contracts the add-on depends on, so silent upstream drift (especially in the overridden s6 run script) is caught at bump time instead of at runtime.
---

# Update the CWA base image

Bump `calibre-web-automated/` to a new upstream tag (call it `<TAG>`, e.g. `v4.0.7`).
The add-on rebases the upstream image and **overrides files inside it**, so a bump is
never just a version edit — every override must be re-diffed and every upstream
contract re-verified.

## 1. Get the upstream source at the new tag

```bash
git clone --depth 1 --branch <TAG> \
    https://github.com/crocodilestick/Calibre-Web-Automated.git /tmp/cwa-upstream
```

(Tags are lowercase `v` since 4.x; `git ls-remote --tags` to confirm.)

## 2. Bump the pins

- `calibre-web-automated/build.yaml` — `build_from` tags for both arches.
- `calibre-web-automated/Dockerfile` — `ARG BUILD_FROM` default.
- `calibre-web-automated/config.yaml` — `version:`. Convention: 4th segment is
  add-on-level (`4.0.6.10` → `4.0.6.11`); on an upstream bump restart it at the new
  upstream version (`4.0.7.0`).

## 3. Re-diff overridden files (CRITICAL)

For each file the add-on ships on top of the image, diff our copy against the new
upstream and re-apply our delta onto upstream's new content — never keep our old copy
blindly:

| Ours (under `calibre-web-automated/`) | Upstream path | Our delta |
| --- | --- | --- |
| `rootfs/etc/s6-overlay/s6-rc.d/svc-calibre-web-automated/run` | `root/etc/s6-overlay/s6-rc.d/svc-calibre-web-automated/run` | adds optional `-i $CWA_BIND_ADDRESS` (via `BIND_ARGS`) so Cloudflare Access mode pins CWA to loopback. Security-critical: without it the auth header is spoofable. |
| `rootfs/app/calibre-web-automated/cps/metadata_provider/arxiv.py` | `cps/metadata_provider/arxiv.py` | full replacement (arXiv provider). Check the `cps.services.Metadata` contract it implements hasn't changed. |

```bash
diff /tmp/cwa-upstream/root/etc/s6-overlay/s6-rc.d/svc-calibre-web-automated/run \
     calibre-web-automated/rootfs/etc/s6-overlay/s6-rc.d/svc-calibre-web-automated/run
```

## 4. Re-verify upstream contracts the add-on depends on

Grep the new upstream source; if any of these moved or changed semantics, the
corresponding add-on code/tests must be updated:

- `CWA_PORT_OVERRIDE` env → listen port: `grep -n CWA_PORT_OVERRIDE cps/constants.py`
- `-i <ip>` CLI flag → bind address: `grep -n "'-i'" cps/cli.py`
- `TRUSTED_PROXY_COUNT` env → ProxyFix: `grep -n TRUSTED_PROXY_COUNT cps/__init__.py`
- Reverse-proxy header login settings:
  `grep -n reverse_proxy cps/config_sql.py cps/usermanagement.py`
  (`config_allow_reverse_proxy_header_login`, `config_reverse_proxy_login_header_name`,
  `create_authenticated_user()` defaults that `setup_access.py` mirrors)
- `user` + `settings` schema in the seeded db — compare against the fixtures in
  `tests/test_access_users.py`:

  ```bash
  python3 -c "import sqlite3; con = sqlite3.connect('/tmp/cwa-upstream/empty_library/app.db'); \
  [print(r) for r in con.execute('PRAGMA table_info(user)')]"
  ```

- Migration-added user columns (`theme`, `hardcover_token`, …):
  `grep -n "ALTER TABLE user ADD" cps/ub.py` — update the optional-column list in
  `rootfs/opt/cwa-access/setup_access.py` and the migrated fixture in the tests.
- `/lsiopy` venv still exists and ships `cryptography` + `werkzeug`
  (`grep -n lsiopy Dockerfile`, `grep -in "cryptography\|werkzeug" requirements.txt`
  in the upstream clone) — the Dockerfile pip-installs PyJWT into it and
  `setup_access.py`/`verifier.py` run on it.

## 5. Update docs and changelog

- `CHANGELOG.md`: new `## [X.Y.Z]` section (Keep a Changelog).
- Mentions of the old version in comments (`tests/test_arxiv.py`,
  `tests/test_access_users.py`, the svc run override header) — bump them.

## 6. Gate

```bash
prek run --all-files
pytest calibre-web-automated/tests/ -v
docker build --build-arg BUILD_ARCH=amd64 calibre-web-automated/
```

After the build, sanity-check the image: nginx has `http_auth_request_module`
(`nginx -V`), `/lsiopy/bin/python3 -c "import jwt, cryptography, werkzeug"`, and the
overridden run script matches what you re-diffed.
