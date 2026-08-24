# Changelog

All notable changes to this add-on will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [4.1.40.0] - 2026-08-24

### Added

- Calibre plugin loading is now on by default (`CWA_CALIBRE_USER_PLUGINS=1`), which is what makes the `plugins_path` option work. Drop a plugin `.zip` (DeDRM and friends) into `plugins_path` and the add-on registers it with `calibre-customize -a` during startup — nothing loads unless you put it there.
- Optional embedded Tailscale: when `tailscale_authkey` is set, the add-on joins the tailnet as its own node (separate identity from the HA host) and `tailscale serve` exposes the CWA UI at `https://<tailscale_hostname>.<tailnet>.ts.net`. Runs `tailscaled` in userspace networking mode so no `/dev/net/tun`, `NET_ADMIN`, or `NET_RAW` is required, and the existing 8083/tcp Web UI mapping is unchanged. State persists under `/data/tailscaled/` so node identity survives add-on upgrades and HA backups. New options: `tailscale_authkey`, `tailscale_hostname`, `tailscale_serve`, `tailscale_funnel`, `tailscale_extra_args`. Funnel additionally requires admin-console opt-in.
- `config_path` option to host CWA's `/config` (app database, user accounts, settings) on a network share. Clearing it keeps `/config` on HA's local `/data` as before; pair a `/share/...` value with `network_share_mode: true` so SQLite WAL is disabled on `app.db`.

### Changed

- Base image moved from `crocodilestick/calibre-web-automated:v4.0.6` to `ghcr.io/new-usemame/calibre-web-nextgen:v4.1.40`. NextGen is a fork of CWA taken at v4.0.6 — the tag this add-on had been pinning since April — and upstream has not published a release since. It is a strict superset: the same LinuxServer/s6 layout, the same `/config`, `/calibre-library` and `/cwa-book-ingest` volumes, the same on-disk format, so the add-on's own `rootfs` overlay, `PUID`/`PGID` pin and Tailscale layer are unchanged and the add-on's persistent state is carried over as-is. What it adds on top of v4.0.6 includes an auth check on 14 admin routes that previously had none, working cover saves from Hardcover/Google Books/iTunes/Open Library, an end to the infinite ingest loop under `network_share_mode: true`, Hardcover finally recognising `HARDCOVER_TOKEN`, reverse-proxy sub-path fixes relevant to `trusted_proxy_count`, and a `cwa-ingest-service` that acknowledges `SIGTERM` instead of letting every add-on stop run out the full grace period and end in `SIGKILL`.
- Add-on version scheme continues to track the base image: `<base image version>.<add-on revision>`.
- Sidebar now opens CWA in a new tab (via `webui`) instead of in an iframe (Ingress). Root cause: CWA emits absolute redirects (e.g. `Location: /login`) without an Ingress URL prefix, because HA Ingress doesn't add `X-Script-Name`/`X-Forwarded-Prefix` to forwarded requests and CWA has no env var for `SCRIPT_NAME` / `APPLICATION_ROOT`. Result was a 404 on `/login` after the sidebar redirect. Direct port access (`http://<host>:8083`) sidesteps the prefix problem entirely.

### Fixed

- Misspelled `CALIBRE_CONFIG_DIR` environment variable. CWA v4.0.6's image exported `CALIBRE_CONFIG_DIR=/config/.config/calibre`; Calibre reads `CALIBRE_CONFIG_DIRECTORY` and has never recognised that name, so the setting was inert and Calibre resolved its configuration — and therefore its plugin directory — from `HOME` instead. The add-on now sets the correctly-spelled `CALIBRE_CONFIG_DIRECTORY`, pointing at the same directory `plugins_path` is bind-mounted over.
- `plugins_path` no longer requires a hand-written `customize.py.json` at `/config/.config/calibre/`, and the start-up warning telling you to write one is gone.
- Supervisor log spam `missing API permission for /supervisor/info` / `Invalid token for access /supervisor/info` on every start. Root cause: the init script called `bashio::supervisor.timezone`, which hits `/supervisor/info` and requires `hassio_api: true` (not granted). The Supervisor already passes `TZ` as a container env var, so the script reads that directly instead.
- Permission-denied errors writing to `library_path`, `ingest_path`, or a `/share`-hosted `config_path`. Root cause: the LSIO base ran as uid/gid 911 by default, but HA's Supervisor owns `/share` and `/media` as 1000:1000. The image now sets `PUID=1000` / `PGID=1000` so LSIO remaps its `abc` user to match, and the init script chowns the directories it creates so a brand-new install isn't left with root-owned bind-mount sources.
- Startup failure `rm: cannot remove '/config': Device or resource busy`. Root cause: the upstream image declares `VOLUME /config`, so `/config` is always a Docker mount point at runtime and `rm -rf /config` (used to replace it with a symlink) cannot succeed. The init script now bind-mounts the target (`/data` or `config_path`) over `/config`, which requires `privileged: [SYS_ADMIN]` and `apparmor: false` — Home Assistant flags add-ons with elevated capabilities, but they still run.
- Startup failure `ln: /config/.config/calibre/plugins: cannot overwrite directory` when `plugins_path` was set. Root cause: `ln -sfn` only replaces existing symlinks, not directories, and the upstream image's `/config` seed populates `.config/calibre/plugins` as a real directory. `library_path`, `ingest_path`, and `plugins_path` are now bind-mounted (instead of symlinked) over `/calibre-library`, `/cwa-book-ingest`, and `/config/.config/calibre/plugins` respectively, which works regardless of whether the targets are pre-populated.

## [4.0.6] - 2026-04-27

### Added

- Initial release. Wraps `crocodilestick/calibre-web-automated:v4.0.6` for Home Assistant.
- Home Assistant Ingress on port 8083.
- User-configurable `library_path`, `ingest_path`, `plugins_path`.
- `network_share_mode` toggle for NAS users.
- `hardcover_token` and `trusted_proxy_count` passthroughs.
- `/data` ↔ `/config` pivot so CWA state survives add-on upgrades.

[4.0.6]: https://github.com/Cdower/hassio-addons/releases/tag/v4.0.6
