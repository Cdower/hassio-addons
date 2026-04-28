# Home Assistant Add-on: Calibre-Web Automated

## Installation

1. Add this repository (`https://github.com/Cdower/hassio-addons`) to Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Install **Calibre-Web Automated** from the store.
3. Start the add-on. The Web UI is available via the sidebar (Ingress) or at `http://<host>:8083`.

## Configuration options

| Option                | Default                  | Description                                                                                                              |
| --------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `library_path`        | `/share/calibre/library` | Where the Calibre library (`metadata.db` + book folders) lives.                                                          |
| `ingest_path`         | `/share/calibre/ingest`  | Drop EPUB/PDF/MOBI/etc. here for automatic ingest. Files are deleted after processing.                                   |
| `config_path`         | _(empty)_                | Where CWA's `/config` (app database, user accounts, settings) lives. Empty = `/data` (HA-managed, local). Set to a `/share/...` path to host `/config` on a network share. |
| `plugins_path`        | _(empty)_                | Optional Calibre plugins folder. See "Plugins" below.                                                                    |
| `network_share_mode`  | `false`                  | Set `true` when the library or `config_path` lives on NFS/SMB. Disables SQLite WAL on `metadata.db`/`app.db` and switches the ingest watcher to polling. |
| `hardcover_token`     | _(empty)_                | API token for [Hardcover](https://hardcover.app) metadata enrichment.                                                    |
| `trusted_proxy_count` | `1`                      | Number of reverse proxies in front of CWA. `1` covers HA Ingress. Increase to `2` if you front HA with Cloudflare/nginx. |
| `log_level`           | `info`                   | One of `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`.                                                  |

## Setup paths

### Local-volume setup (recommended for new users)

Leave the defaults. The add-on creates `/share/calibre/library` and `/share/calibre/ingest` on first start. Mount your `share/` over Samba or use the File Editor add-on to drop books in.

### Network-share setup (NAS users / migrating from existing CWA)

1. **Mount your NAS** to `/share/<name>` using the Home Assistant Samba/NFS client (Settings → System → Storage → Add network storage). Or use the Network Storage helper in HAOS to mount under `/share/`.
2. **Set the paths** in this add-on's config to point inside that mount:
   - `library_path: /share/nas/calibre/library`
   - `ingest_path: /share/nas/calibre/ingest`
   - (optional) `config_path: /share/nas/calibre/config` — host CWA's app database, user accounts, and settings on the share too. Leave empty to keep `/config` on HA's local `/data`.
   - (optional) `plugins_path: /share/nas/calibre/plugins`
3. **Set `network_share_mode: true`** — required for SMB/NFS to disable SQLite WAL (which corrupts on network shares) on both `metadata.db` and CWA's `app.db`, and to switch the ingest watcher from inotify to polling.
4. **Migrating from an existing CWA install**:
   - Stop your old container.
   - Copy `metadata.db` and the book folders to the new `library_path`.
   - To preserve user accounts and CWA's app database, you have two options:
     - **HA-local `/config`** (default): the add-on keeps `/config` on its private `/data` directory, which isn't reachable from Samba. Either set `config_path` to a `/share/...` path so you can copy files in directly, or use the SSH/Terminal add-on and copy your old CWA `/config` contents into `/data` (path inside this add-on's container).
     - **Network-share `/config`**: copy your old CWA `/config` contents into the directory you set as `config_path` (e.g. `/share/nas/calibre/config`).
   - Delete the sentinel from wherever `/config` lives: `rm <config_path>/.cwa-initialized` (or `rm /data/.cwa-initialized` for the default) so the add-on doesn't think it's already initialized.
   - Restart the add-on.

> Switching `config_path` after the add-on has run reseeds the new target from whatever `/config` points to at startup. On a brand-new install that's the image defaults; on an existing install it's typically your previous persistent `/config`. If the config you want to keep is *not* what `/config` points to when the add-on starts, copy it into the new target manually *before* restarting.

## Plugins (`customize.py.json` gotcha)

If you set `plugins_path`, you also need a `customize.py.json` file at `/config/.config/calibre/customize.py.json` (i.e. one level above `plugins/`) for Calibre to load the plugins. The add-on logs a warning if this is missing. See the [upstream README plugins section](https://github.com/crocodilestick/Calibre-Web-Automated#plugins) for the file's format.

## Known issues

- **Kobo sync URLs**: CWA generates absolute URLs for Kobo sync. With `trusted_proxy_count: 1` and HA Ingress, this should Just Work. If your Kobo can't reach the sync URL, check that you're accessing HA via the same hostname that's in the URL CWA generated (open Settings → Server → Server URLs in CWA). If CWA is fronted by Cloudflare or nginx-proxy-manager, bump `trusted_proxy_count` to `2`.
- **File ownership**: Files written to `/share` are owned by uid/gid 1000 (LSIO base default). If you also access the share over Samba and need different ownership, change it on the host or via Samba's `force user` option.
- **Backups**: CWA's verbose `cwa.log` and the temporary `processed_books/` directory are excluded from HA backups (see `backup_exclude` in `config.yaml`). Library files in `/share` are not in HA backups by design — back those up separately.

## Persistence

By default the add-on stores CWA's app database, user accounts, and settings in HA's per-add-on `/data` directory, which survives add-on upgrades and uninstalls. Set `config_path` to relocate that state to a `/share/...` path (typically a NAS mount) — useful if you want the CWA config on the same share as the library, or shared with another CWA instance. Library files in `library_path` (e.g. under `/share`) are always independent of the add-on lifecycle.

## Upgrades

When upstream releases a new version:

1. The add-on bumps the pinned tag in `build.yaml` and `version:` in `config.yaml`.
2. HA shows an upgrade in the Add-on Store.
3. Click upgrade. The container is rebuilt; `/data` is preserved.

If you self-build, click **Rebuild** in the add-on's three-dot menu.

## Support

<https://github.com/Cdower/hassio-addons/issues>
