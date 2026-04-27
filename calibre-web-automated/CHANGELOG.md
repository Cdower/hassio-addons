# Changelog

All notable changes to this add-on will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.0.6] - 2026-04-27

### Added

- Initial release. Wraps `crocodilestick/calibre-web-automated:v4.0.6` for Home Assistant.
- Home Assistant Ingress on port 8083.
- User-configurable `library_path`, `ingest_path`, `plugins_path`.
- `network_share_mode` toggle for NAS users.
- `hardcover_token` and `trusted_proxy_count` passthroughs.
- `/data` ↔ `/config` pivot so CWA state survives add-on upgrades.

[4.0.6]: https://github.com/Cdower/hassio-addons/releases/tag/v4.0.6
