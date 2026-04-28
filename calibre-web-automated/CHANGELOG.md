# Changelog

All notable changes to this add-on will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `config_path` option to host CWA's `/config` (app database, user accounts, settings) on a network share. Empty (default) keeps `/config` on HA's local `/data` as before; pair a `/share/...` value with `network_share_mode: true` so SQLite WAL is disabled on `app.db`.

### Fixed

- Startup failure `rm: cannot remove '/config': Device or resource busy`. Root cause: the upstream image declares `VOLUME /config`, so `/config` is always a Docker mount point at runtime and `rm -rf /config` (used to replace it with a symlink) cannot succeed. The init script now bind-mounts the target (`/data` or `config_path`) over `/config`, which requires `privileged: [SYS_ADMIN]` and `apparmor: false` — Home Assistant flags add-ons with elevated capabilities, but they still run.

## [4.0.6] - 2026-04-27

### Added

- Initial release. Wraps `crocodilestick/calibre-web-automated:v4.0.6` for Home Assistant.
- Home Assistant Ingress on port 8083.
- User-configurable `library_path`, `ingest_path`, `plugins_path`.
- `network_share_mode` toggle for NAS users.
- `hardcover_token` and `trusted_proxy_count` passthroughs.
- `/data` ↔ `/config` pivot so CWA state survives add-on upgrades.

[4.0.6]: https://github.com/Cdower/hassio-addons/releases/tag/v4.0.6
