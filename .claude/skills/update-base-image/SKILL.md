---
name: update-base-image
description: Bump the calibre-web-automated add-on to a new upstream calibre-web-nextgen base image tag. Re-diffs every file this add-on overrides in the image and re-verifies the upstream contracts the add-on depends on, so silent upstream drift (especially in the overridden s6 run script) is caught at bump time instead of at runtime.
---

# Update the CWA base image

Bump `calibre-web-automated/` to a new upstream tag (call it `<TAG>`, e.g. `v4.1.41`).
The add-on rebases the upstream image and **overrides files inside it**, so a bump is
never just a version edit — every override must be re-diffed and every upstream
contract re-verified.

The weekly **Base image** workflow (`.github/workflows/base-image.yaml`) opens
these bumps as PRs from `deps/base-image`. It does step 2's pins (not
`version:`, which is left to the Bump workflow) and the changelog line, and its
PR body lists which upstream files from steps 3 and 4 changed between the two tags
(`.github/scripts/base-image-drift.py`). When reviewing such a PR, work on that
branch and verify the listed files; the rest are unchanged upstream. Keep the
script's `WATCHED` list in step with steps 3 and 4, and its `NOTES` with the
"verified against vX" comments step 5 bumps (the workflow moves a note itself
when the upstream files it covers are unchanged).

## 1. Get the upstream source at the new tag

```bash
git clone --depth 1 --branch <TAG> \
    https://github.com/new-usemame/calibre-web-nextgen.git /tmp/cwa-upstream
```

(Lowercase `v` tags; `git ls-remote --tags` to confirm. NextGen is the fork of
crocodilestick/Calibre-Web-Automated this add-on moved to at v4.1.40.)

## 2. Bump the pins

- `calibre-web-automated/build.yaml` — `build_from` tags for both arches.
- `calibre-web-automated/Dockerfile` — `ARG BUILD_FROM` default.
- `calibre-web-automated/config.yaml` — `version:`. Convention: 4th segment is
  add-on-level (`4.1.40.0` → `4.1.40.1`); on an upstream bump restart it at the new
  upstream version (`4.1.41.0`).

## 3. Re-diff overridden files (CRITICAL)

For each file the add-on ships on top of the image, diff our copy against the new
upstream and re-apply our delta onto upstream's new content — never keep our old copy
blindly:

| Ours (under `calibre-web-automated/`) | Upstream path | Our delta |
| --- | --- | --- |
| `rootfs/etc/s6-overlay/s6-rc.d/svc-calibre-web-automated/run` | `root/etc/s6-overlay/s6-rc.d/svc-calibre-web-automated/run` | adds optional `-i $CWA_BIND_ADDRESS` (via `BIND_ARGS`) on the `cwa-as-abc python3 -P -m cps` exec line so Cloudflare Access mode pins CWA to loopback. Security-critical: without it the auth header is spoofable. |
| `rootfs/app/calibre-web-automated/cps/metadata_provider/arxiv.py` | `cps/metadata_provider/arxiv.py` | full replacement (arXiv provider). Check the `cps.services.Metadata` contract it implements hasn't changed. |
| `apparmor.txt` | Docker's `docker-default` profile (moby `profiles/apparmor/template.go`) | adds mount rules for the bind mounts and the CIFS mount made by `init-cwa-paths`. If the new image adds a service that mounts anything, signals or ptraces across processes, or writes under `/proc/sys` or `/sys`, the profile must allow it or the add-on breaks only on AppArmor hosts (HAOS). |

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
- `user` + `settings` schema — NextGen has no seeded `empty_library/app.db`;
  `cwa-init` creates it on first boot via `python3 -P -m cps -d`, fully
  migrated. Compare the `User`/`_Settings` models and migrations in
  `cps/ub.py` / `cps/config_sql.py` against the fixtures in
  `tests/test_access_users.py`.
- Migration-added user columns (`theme`, `hardcover_token`, …):
  `grep -n "ALTER TABLE user ADD" cps/ub.py` — update the optional-column list in
  `rootfs/opt/cwa-access/setup_access.py` and the migrated fixture in the tests.
- Metadata provider discovery: `cps/search_metadata.py` still imports every
  file in `cps/metadata_provider/` (`os.listdir` + `importlib`) and picks up
  `cps.services.Metadata` subclasses. `install_providers.py` relies on this to
  add `metadata_providers_path` files; also confirm none of the new built-in
  provider names is one users are likely to have used for a custom file.
- `cwa-init` is still the service every CWA service waits on: the add-on makes
  it depend on `init-cwa-metadata-providers` so providers are installed before
  anything imports them (`ls root/etc/s6-overlay/s6-rc.d/*/dependencies.d`).
- SQLite files CWA keeps in `/config` and the library: backups rely on
  `rootfs/opt/cwa-backup/db_snapshot.py` snapshotting every `*.db` under
  `/data` and `/addon_config` (`backup_pre`). A new database with another
  extension (`grep -rhoE "/config/[A-Za-z0-9_./-]*\.(db|sqlite[0-9]?)" cps
  scripts root`) would be backed up torn — extend the script if one appears.
- Split library mode (`books_path` / `metadata_db_export`,
  `rootfs/opt/cwa-split-library/`): the add-on writes `config_calibre_split`
  and `config_calibre_split_dir` into app.db's `settings` and relies on
  upstream honouring them everywhere book files are touched. Check:
  `grep -n "config_calibre_split" cps/config_sql.py` (columns and
  `get_book_path()`), `grep -n "CALIBRE_OVERRIDE_DATABASE_PATH\|split_library" scripts/ingest_processor.py`
  (ingest hands Calibre the local metadata.db and writes files to the split
  dir), and `grep -rLn "split\|get_book_path\|OVERRIDE_DATABASE" $(grep -rl "metadata.db\|calibre_library_dir" scripts cps/tasks cps/services)`
  for new code that reads book files from the library dir without it. Also
  that `scripts/auto_library.py` still only looks for metadata.db under
  `/calibre-library` (it must not adopt the exported copy in `/calibre-books`),
  that the oneshot is still called `cwa-auto-library` (our
  `init-cwa-split-library` depends on it), and how `cps/content_server.py`
  handles split mode (`grep -n split cps/content_server.py`; the add-on only
  warns).
- `/lsiopy` venv still exists and ships `cryptography` + `werkzeug`
  (`grep -n lsiopy Dockerfile`, `grep -in "cryptography\|werkzeug" pyproject.toml`
  in the upstream clone) — the Dockerfile installs the add-on's own
  `pyproject.toml` / `uv.lock` dependencies (PyJWT) into it with uv, and
  `setup_access.py`/`verifier.py` run on it.

## 5. Update docs and changelog

- `CHANGELOG.md`: new `## [X.Y.Z]` section (Keep a Changelog).
- Mentions of the old version in comments (`tests/test_arxiv.py`, the svc run
  override header) — bump them. If the image's `/lsiopy` moved `cryptography`
  or `werkzeug` (`/lsiopy/bin/pip list` in the new image), move the `test`
  group pins in `calibre-web-automated/pyproject.toml` to match and run
  `uv lock --project calibre-web-automated`.

## 6. Gate

```bash
prek run --all-files
uv run --project calibre-web-automated --frozen --group test pytest calibre-web-automated/tests/ -v
docker build --build-arg BUILD_ARCH=amd64 calibre-web-automated/
apparmor_parser -Q -K -S -M /etc/apparmor.d/abi/4.0 calibre-web-automated/apparmor.txt > /dev/null
```

After the build, sanity-check the image: nginx has `http_auth_request_module`
(`nginx -V`), `/lsiopy/bin/python3 -c "import jwt, cryptography, werkzeug"`, and the
overridden run script matches what you re-diffed.
