# Home Assistant Add-on: Calibre-Web Automated

## Installation

1. Add this repository (`https://github.com/Cdower/hassio-addons`) to Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Install **Calibre-Web Automated** from the store.
3. Start the add-on. The sidebar opens the direct Web UI URL in a new tab, and the app is also reachable directly at `http://<host>:8083`. Your browser/client must be able to reach `http(s)://<host>:8083`; if you access Home Assistant through a remote URL or reverse proxy that does not also expose port 8083 (for example HA Cloud), the sidebar link may not work.

## Configuration options

| Option                | Default                  | Description                                                                                                              |
| --------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `library_path`        | `/share/calibre/library` | Where the Calibre library (`metadata.db` + book folders) lives.                                                          |
| `ingest_path`         | `/share/calibre/ingest`  | Drop EPUB/PDF/MOBI/etc. here for automatic ingest. Files are deleted after processing.                                   |
| `config_path`         | _(empty)_                | Where CWA's `/config` (app database, user accounts, settings) lives. Empty = `/data` (HA-managed, local). Set to a `/share/...` path to host `/config` on a network share. |
| `plugins_path`        | _(empty)_                | Optional Calibre plugins folder. See "Plugins" below.                                                                    |
| `network_share_mode`  | `false`                  | Set `true` when the library or `config_path` lives on NFS/SMB. Disables SQLite WAL on `metadata.db`/`app.db` and switches the ingest watcher to polling. |
| `hardcover_token`     | _(empty)_                | API token for [Hardcover](https://hardcover.app) metadata enrichment.                                                    |
| `trusted_proxy_count` | `1`                      | Number of reverse proxies in front of CWA whose `X-Forwarded-*` headers should be trusted. Use `1` only when the add-on is behind exactly one reverse proxy (Cloudflare, nginx-proxy-manager, Traefik, etc.). Set higher for chained proxies. For direct access with no reverse proxy, use a lower value such as `0` if supported, rather than trusting forwarded headers from clients. |
| `log_level`           | `info`                   | One of `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`.                                                  |
| `tailscale_enabled`   | `false`                  | Run a Tailscale sidecar inside this add-on so CWA is reachable from your tailnet. See "Tailscale sidecar" below.         |
| `tailscale_hostname`  | `calibre`                | Hostname the add-on registers in your tailnet. With MagicDNS on, you reach CWA at `http://<hostname>/` from any tailnet device. |
| `tailscale_authkey`   | _(empty)_                | Tailscale auth key for first-time login. Leave empty to authenticate interactively (an auth URL is printed to the add-on log). After login, state persists in `/data/tailscale` and the key is no longer required. |
| `tailscale_serve`     | `http`                   | `http` (port 80, plain HTTP — recommended for the "type `calibre` in browser" use case), `https` (port 443, requires HTTPS certs enabled in your tailnet admin console), or `none` (skip serve; CWA is reachable at `http://<hostname>:8083`). |

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
     - **Add-on-local `/data`-backed `/config`** (default): the add-on keeps `/config` on its private `/data` directory, which isn't reachable from Samba. Either set `config_path` to a `/share/...` path so you can copy files in directly, or use the SSH/Terminal add-on and copy your old CWA `/config` contents into `/data` (path inside this add-on's container).
     - **Network-share `/config`**: copy your old CWA `/config` contents into the directory you set as `config_path` (e.g. `/share/nas/calibre/config`).
   - Delete the sentinel from wherever `/config` lives: `rm <config_path>/.cwa-initialized` (or `rm /data/.cwa-initialized` for the default) so the add-on doesn't think it's already initialized.
   - Restart the add-on.

> Switching `config_path` after the add-on has run reseeds the new target from whatever `/config` points to at startup. On a brand-new install that's the image defaults; on an existing install it's typically your previous persistent `/config`. If the config you want to keep is *not* what `/config` points to when the add-on starts, copy it into the new target manually *before* restarting.

## Tailscale sidecar

Optional. Enable this if you want CWA reachable from your [Tailscale](https://tailscale.com) tailnet — for example, typing `calibre` in your browser from any device on your tailnet and landing on the CWA UI.

This is a **sidecar**, not a host-level Tailscale install: the tailscaled process runs *inside* this add-on's container, in [userspace networking mode](https://tailscale.com/kb/1112/userspace-networking). That mode is intentional — it lets the tailnet reach CWA on this device, but CWA itself can't talk *out* to other tailnet machines via Tailscale. Enabling the sidecar exposes Calibre to the tailnet without granting Calibre a route into the rest of the tailnet, which is the property you want if you don't trust the upstream image to be on your private network.

Compare with the official [Tailscale add-on](https://github.com/hassio-addons/addon-tailscale): that one connects all of Home Assistant (and everything HA can reach on its LAN) to your tailnet. The sidecar here connects only the CWA service.

### Setup

1. **Generate an auth key** in the [Tailscale admin console](https://login.tailscale.com/admin/settings/keys). A reusable, non-ephemeral key is fine; it's only used once. Optional but recommended: tag the key (`tag:calibre`) so you can write ACLs that scope what the sidecar can do.
2. **Enable in the add-on config**:
   ```yaml
   tailscale_enabled: true
   tailscale_hostname: calibre        # or whatever name you want to type
   tailscale_authkey: tskey-auth-...  # paste the key here; remove after first start if you like
   tailscale_serve: http              # default: HTTP on port 80 of the tailnet device
   ```
3. **Restart** the add-on. On first start, the sidecar registers `calibre` with your tailnet using the auth key. State is persisted to `/data/tailscale` so subsequent restarts don't need the key.
4. **Visit** `http://calibre/` from any tailnet device. (With [MagicDNS](https://tailscale.com/kb/1081/magicdns) enabled — which it is by default for personal tailnets — short hostnames work; otherwise use the full `calibre.<tailnet>.ts.net`.)

If you leave `tailscale_authkey` empty, the add-on log will print an auth URL on first start; click it within ~5 minutes to log the device in interactively.

### Serve modes

- `http` (default): proxies the tailnet device's port 80 to CWA's `127.0.0.1:8083`. Plain HTTP, no certificates needed. Best fit for "type `calibre` in browser" — typing a bare hostname into a browser defaults to `http://`, and there's no cert hostname to mismatch.
- `https`: proxies the tailnet device's port 443 to CWA. Requires [HTTPS certificates](https://tailscale.com/kb/1153/enabling-https) enabled in your tailnet (admin console → DNS → HTTPS Certificates). The browser bar will show the full `https://calibre.<tailnet>.ts.net/` because the cert is for the FQDN.
- `none`: don't run `tailscale serve`. CWA is still reachable at `http://calibre:8083` (the raw port, since the device itself is on the tailnet). Use this if you want to manage `tailscale serve` / `tailscale funnel` manually.

### Tailscale services (advanced)

[Tailscale services](https://tailscale.com/docs/features/tailscale-services) let multiple devices back the same service name with shared ACLs (e.g. a CWA instance per HA box, all reachable as `calibre`). That requires admin-console configuration and a Premium tailnet plan; it's not auto-configured by this add-on. If you want it, set `tailscale_serve: none` to opt out of auto-serve and configure the service manually via `tailscale set` after first start.

### Caveats

- This add-on uses Tailscale's userspace networking, so the **CWA process cannot reach other tailnet hosts**. That's the point — but if you also want CWA to *fetch* from a tailnet resource, you need a different setup (run Tailscale on the host or in another container).
- Auth key persistence: once authenticated, you can clear `tailscale_authkey` from config; the saved state in `/data/tailscale` keeps the device logged in across restarts and add-on upgrades. Uninstalling the add-on wipes `/data` and removes the device from your tailnet on next admin-console expiry.
- The Tailscale binary is bundled in the image regardless of `tailscale_enabled`. When disabled, the sidecar service is held idle (no traffic, no auth, no tailnet presence).

## Plugins (`customize.py.json` gotcha)

If you set `plugins_path`, you also need a `customize.py.json` file at `/config/.config/calibre/customize.py.json` (i.e. one level above `plugins/`) for Calibre to load the plugins. The add-on logs a warning if this is missing. See the [upstream README plugins section](https://github.com/crocodilestick/Calibre-Web-Automated#plugins) for the file's format.

## Known issues

- **Kobo sync URLs**: CWA generates absolute URLs for Kobo sync based on the host it sees the request from. Make sure your Kobo can reach CWA at that host:port (open Settings → Server → Server URLs in CWA to inspect the URL it generated). If CWA is fronted by Cloudflare/nginx-proxy-manager/Traefik, bump `trusted_proxy_count` so CWA picks up the original host from `X-Forwarded-Host`.
- **File ownership**: The app runs as uid/gid 1000 to match HA's `/share` and `/media`, so files it writes there are owned 1000:1000. If you also access the share over Samba and need different ownership, change it on the host or via Samba's `force user` option.
- **Backups**: CWA's verbose `cwa.log` and the temporary `processed_books/` directory are excluded from HA backups (see `backup_exclude` in `config.yaml`). Library files in `/share` are not in HA backups by design — back those up separately.

## Persistence

By default the add-on stores CWA's app database, user accounts, and settings in HA's per-add-on `/data` directory, which survives add-on upgrades and uninstalls. Set `config_path` to relocate that state to a `/share/...` path (typically a NAS mount) — useful if you want the CWA config on the same share as the library, or shared with another CWA instance. Library files in `library_path` (e.g. under `/share`) are always independent of the add-on lifecycle.

This add-on uses `privileged: [SYS_ADMIN]` and `apparmor: false` to bind-mount your chosen `/config` path over the upstream image's `VOLUME /config`. Home Assistant marks add-ons with elevated capabilities — that's expected here.

## Upgrades

When upstream releases a new version:

1. The add-on bumps the pinned tag in `build.yaml` and `version:` in `config.yaml`.
2. HA shows an upgrade in the Add-on Store.
3. Click upgrade. The container is rebuilt; `/data` is preserved.

If you self-build, click **Rebuild** in the add-on's three-dot menu.

## Support

<https://github.com/Cdower/hassio-addons/issues>
