# Home Assistant Add-on: Calibre-Web Automated

Self-hosted ebook library with automatic ingest, format conversion, and metadata enrichment.

[Calibre-Web Automated][cwa] (CWA) wraps Calibre-Web with an ingest folder, automatic format conversion, KOReader/Kobo sync, and Hardcover metadata. This add-on rebases that image onto a Home Assistant wrapper, building on [Calibre-Web NextGen][nextgen] — a fork of CWA taken at v4.0.6, with the same data format and configuration.

## Quick start

1. **Install** this add-on from the Add-on Store.
2. **Start** it. Defaults create `/share/calibre/calibre-library` and `/share/calibre/cwa-book-ingest`.
3. **Drop EPUB/PDF/MOBI files** into `/share/calibre/cwa-book-ingest` (use the Samba or File Editor add-on). They'll be ingested, converted, and added to the library within a few seconds.
4. **Open the Web UI** via the sidebar (Ingress) or directly at port `8083`.

## Configuration

See [DOCS.md](DOCS.md) for full options, including network-share setup for NAS users and migration from an existing CWA install.

## Support

Issues and feature requests: <https://github.com/Cdower/hassio-addons/issues>

## License

This add-on (the wrapper) is MIT-licensed. Calibre-Web Automated and Calibre-Web NextGen are both GPL-3.0 — see <https://github.com/crocodilestick/Calibre-Web-Automated/blob/main/LICENSE> and <https://github.com/new-usemame/Calibre-Web-NextGen/blob/main/LICENSE>.

[cwa]: https://github.com/crocodilestick/Calibre-Web-Automated
[nextgen]: https://github.com/new-usemame/Calibre-Web-NextGen
