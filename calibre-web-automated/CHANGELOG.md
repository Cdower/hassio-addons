# Changelog

All notable changes to this add-on will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Saving the configuration failed with `Missing option 'metadata_db_export' in root` on an install that predates that option. Home Assistant validates the whole saved options set against the add-on's schema but never adds a newly introduced option to an existing install's options, so a required new option makes the configuration page unsaveable until the option is typed in by hand in YAML mode. `metadata_db_export`, `tailscale_serve`, `tailscale_funnel` and `access_users` are optional in the schema now (a list option carries the `?` on its element type, which is what the Supervisor checks a missing list option against), and a test keeps it that way. `tailscale_serve` still defaults to `true` when it is missing from an install's options, as documented, and `tailscale_hostname` and `tailscale_extra_args` no longer read a missing option as the literal string `null` — which named the tailnet node `null` and passed a stray `null` argument to `tailscale up`.

### Added

- `books_path` option: keep the book folders on the NAS while `metadata.db` stays on the add-on's local storage. It uses CWA's own split library mode, which the add-on now configures: `library_path` holds only `metadata.db`, and new books, conversions and edits write their files to `books_path`. SQLite then never runs over the network, so WAL stays on and `metadata.db` is part of the add-on's backups. On the first start with a new `books_path`, the add-on moves an existing `metadata.db` from that folder into `library_path` and renames the one left behind to `metadata.db.pre-split`; it refuses to start if both folders already hold a library with books. Changing only `library_path` later moves `metadata.db` over from the previous one (or, if that folder is gone, restores it from the `metadata_db_export` copy), instead of starting an empty library. Clearing `books_path` turns split library mode off again. The Calibre content server does not support split library mode.
- `metadata_db_export` option: with `books_path` set, keep a read-only copy of `metadata.db` in `books_path`, so the NAS folder stays a complete Calibre library for NAS backups and Calibre desktop. It is written with SQLite's backup API after changes settle (at least every 10 minutes while the library keeps changing) and once more when the add-on stops, and renamed into place so readers never see a partial file. The add-on now allows 30 seconds to stop (`timeout: 30`, and s6's `S6_SERVICES_GRACETIME` raised to 25 s) so that last copy can finish.

## [4.1.48.1] - 2026-10-19

### Fixed

- `smb_share` could not be mounted: every attempt failed with `Unable to apply new capability set` and the add-on stopped with `Could not mount //server/share`. `mount.cifs` drops its privileges on start and keeps `CAP_DAC_READ_SEARCH` while doing so, and the kernel refuses to hand a process a capability its container never had. The add-on now also requests `DAC_READ_SEARCH`, and its AppArmor profile denies using it, so the only thing that changes is that `mount.cifs` can start. Home Assistant's security rating is unchanged.

## [4.1.48.0] - 2026-10-19

### Changed

- Updated the base image from Calibre-Web NextGen v4.1.40 to [v4.1.48](https://github.com/new-usemame/calibre-web-nextgen/blob/v4.1.48/CHANGELOG.md). Upstream highlights include per-user "My Library" mode, per-device book scope for Kobo and KOReader, hierarchical tag browsing, bulk editing in the table view and a Catalan translation. Upstream now only believes `X-Forwarded-*` headers from loopback, private networks and Tailscale (`TRUSTED_PROXY_NETWORKS`); the add-on's own nginx front, Home Assistant's network and the cloudflared add-on all fall inside that default, so no change is needed.
- The CWA server override (`svc-calibre-web-automated/run`) was re-applied on top of upstream's new version, which also clears `PYTHONPATH` and user site-packages before starting the app. The `-i $CWA_BIND_ADDRESS` loopback pin for Cloudflare Access mode is unchanged.
- Accounts created for `access_users` now match upstream's defaults for new users: Kobo sync sends only selected shelves (`kobo_only_shelves_sync = 1`), and the instance's default UI fonts are copied onto the account.

## [4.1.40.2] - 2026-10-19

### Added

- `smb_share` option (with `smb_username`, `smb_password`, `smb_domain`, `smb_version`): the add-on mounts an SMB/CIFS share itself at `/mnt/smb`, with files owned by the user CWA runs as. Home Assistant's Network Storage mounts CIFS shares writable only by root, and has no option to change that. On such a mount CWA could read the library but every write failed, which on a `/share`-hosted `config_path` crash-looped the add-on with `attempt to write a readonly database`. Point `library_path` / `ingest_path` under `/mnt/smb`. With `library_path` on the share, `network_share_mode` is turned on automatically; with only `ingest_path` there, the ingest watcher just switches to polling.
- `metadata_providers_path` option: drop custom metadata provider `.py` files in that folder and they are installed next to CWA's built-in providers on start. A file named like a built-in provider is skipped, so built-ins are never overwritten; removing a file uninstalls it on the next restart.
- Consistent SQLite backups. Home Assistant backs add-ons up by copying their files while they run, which can capture a damaged or out-of-date copy of a database in use. A `backup_pre` hook now snapshots every SQLite database in `/data` and `/addon_config` (CWA's `app.db` and `cwa.db`, the library's `metadata.db`) with SQLite's backup API, and `backup_post` removes the snapshots. The snapshots are listed in `/data/.cwa-backup-snapshots`; when the add-on starts with that list present (a restored backup), the snapshots replace the copied database files before CWA opens them. A normal start finds no list and does no searching.
- A startup warning for each path option that is not part of the add-on's own backups (anything outside `/addon_config`, `/data` and the SMB share).
- Custom AppArmor profile (`apparmor.txt`) replacing `apparmor: false`. It is Docker's default container profile plus the specific mounts the add-on makes. Home Assistant's security rating goes from 3 to 5.

### Changed

- The default `library_path`, `ingest_path` and `plugins_path` moved from `/share/calibre/...` to the add-on's own config folder (`/addon_config/...`, `addon_configs/<id>_calibre-web-automated` on the host and over Samba), so they are part of the add-on's backups. An install that never changed these options and still has its data in the old `/share/calibre/...` folders keeps using them, with a warning in the log. Options you set yourself are not changed.
- CWA's `/config` (app database, users, settings) now always lives on the add-on's local `/data`, so only the library and ingest folders sit on network storage. SQLite's locking is not reliable over the network, and `/data` is part of Home Assistant backups. `config_path` is deprecated and no longer in the default options. On first start, the add-on imports CWA's config once from `config_path` (or from the old default `/share/calibre/config` if `config_path` was never saved), as long as `/data` has no `app.db` yet. The old copy is left in place.
- Updated the bundled Tailscale client from 1.96.4 to 1.102.3.

### Fixed

- Clearing an optional option in the UI (for example `config_path`, `plugins_path`, `cloudflare_team_domain` or `hardcover_token`) made the add-on read it as the literal string `null`. A cleared `config_path` then failed startup with `config_path must be an absolute path (got: null)`.
- Crash on start with `network_share_mode` on (set, or turned on because `library_path` is on `smb_share`): `app.db is not writable` followed by `sqlite3.OperationalError: attempt to write a readonly database` during migration. Root cause: upstream's `cwa-init` skips its `chown -R abc:abc /config` whenever `NETWORK_SHARE_MODE` is on, so state written under another uid stays unwritable — typically an `app.db` created by the 4.0.6-based add-on, which ran as uid 911 before this image pinned `PUID=1000`, and copied into `/data` by hand. With `network_share_mode` on, the add-on now re-owns anything under `/config` that isn't already `1000:1000` (except the Supervisor's `options.json` and Tailscale's state, which stay root-only), and if `app.db` is still not writable logs an error naming the cause instead of leaving it to a traceback.

## [4.1.40.1] - 2026-08-24

### Added

- Optional Cloudflare Access mode: set `cloudflare_team_domain` + `cloudflare_access_aud` (and list `access_users`) to let users sign in with Google/Apple via Cloudflare Zero Trust — no CWA passwords to manage. The Cloudflare Tunnel runs in the separate [cloudflared add-on](https://github.com/brenner-tobias/addon-cloudflared), pointed at this add-on's new (unmapped) port 8085. In this mode CWA is pinned to `127.0.0.1:8084` and nginx fronts it: the LAN listener on 8083 keeps password login and strips auth headers, while the 8085 listener validates the `Cf-Access-Jwt-Assertion` JWT (signature/audience/issuer/expiry against the team's JWKS — the bare `Cf-Access-Authenticated-User-Email` header is never trusted) and logs the user in through Calibre-Web's reverse-proxy header login. Each `access_users` email gets a pre-created CWA account with an unusable random password. No behavior change when the options are unset; disabling the feature turns header login back off automatically on the next start. New options: `cloudflare_team_domain`, `cloudflare_access_aud`, `access_users`.

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
