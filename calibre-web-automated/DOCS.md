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
| `tailscale_authkey`   | _(empty)_                | Tailscale auth key (`tskey-auth-…`). Empty disables the embedded Tailscale entirely. See "Tailscale" below.              |
| `tailscale_hostname`  | _(empty, defaults `cwa`)_| Hostname this add-on registers in your tailnet.                                                                          |
| `tailscale_serve`     | `true`                   | When `true`, exposes CWA at `https://<tailscale_hostname>.<tailnet>.ts.net` via `tailscale serve` (auto HTTPS).            |
| `tailscale_funnel`    | `false`                  | When `true` (and `tailscale_serve: true`), additionally enables Tailscale Funnel so the same URL is reachable from the public internet. Requires Funnel to be enabled for your tailnet in the admin console. |
| `tailscale_extra_args`| _(empty)_                | Extra flags appended to `tailscale up`, e.g. `--advertise-tags=tag:calibre`.                                              |

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

## Plugins (`customize.py.json` gotcha)

If you set `plugins_path`, you also need a `customize.py.json` file at `/config/.config/calibre/customize.py.json` (i.e. one level above `plugins/`) for Calibre to load the plugins. The add-on logs a warning if this is missing. See the [upstream README plugins section](https://github.com/crocodilestick/Calibre-Web-Automated#plugins) for the file's format.

## Tailscale (optional)

The add-on can join your tailnet as its own node, separate from the Home Assistant host. This is useful if you want to ACL/tag CWA independently, or reach it remotely without putting the rest of HA on the tailnet. Leave `tailscale_authkey` empty to disable.

How it works: `tailscaled` runs as a second process inside the add-on's container in [userspace networking mode](https://tailscale.com/docs/concepts/userspace-networking) — no `/dev/net/tun`, no extra capabilities. `tailscale serve` proxies tailnet HTTPS traffic to CWA's local `127.0.0.1:8083`. Tailscale state is persisted under `/data/tailscaled/` so the node identity survives add-on upgrades and is included in HA backups. **Important:** this state includes the node's private keys and identity material, so any HA backup containing `/data/tailscaled/` should be treated as sensitive. Restoring that state onto another instance effectively clones the same Tailscale node identity unless you remove `/data/tailscaled/` and re-authenticate the node.

### Setup

1. In the [Tailscale admin console](https://login.tailscale.com/admin/), generate an auth key (Settings → Keys → Generate auth key). For unattended add-on restarts you typically want **Reusable** and a long expiry. If you also plan to advertise tags via `tailscale_extra_args`, set the key's **Tags** to those tags.
2. In this add-on's config, set `tailscale_authkey` and (optionally) `tailscale_hostname`. Restart the add-on.
3. Wait ~10 seconds, then look for the node in the admin console. CWA will be reachable from any other tailnet device at `https://<tailscale_hostname>.<your-tailnet>.ts.net`.

### Example: tagged CWA node + ACL

Add-on options:

```yaml
tailscale_authkey: "tskey-auth-XXXXXXXXXXXXXXXXX"
tailscale_hostname: "cwa"
tailscale_serve: true
tailscale_funnel: false
tailscale_extra_args: "--advertise-tags=tag:calibre"
```

Tailnet ACLs (admin console → Access controls):

```hujson
{
  "tagOwners": {
    "tag:calibre": ["autogroup:admin"]
  },
  "acls": [
    // Members can reach CWA on its HTTPS port
    {
      "action": "accept",
      "src":    ["autogroup:member"],
      "dst":    ["tag:calibre:443"]
    }
  ]
}
```

Equivalent to running, after the node is up:

```sh
tailscale serve --bg --https=443 http://127.0.0.1:8083
```

(which is exactly what the add-on's init script does on each restart). You can inspect the resulting JSON-form config from the add-on shell with `tailscale serve status --json`.

### Public exposure (Funnel)

`tailscale_funnel: true` makes the same `https://<hostname>.<tailnet>.ts.net` URL reachable from the public internet. Funnel must first be enabled for your tailnet in the admin console (Settings → Feature previews → Funnel). Use this carefully — it bypasses the tailnet ACL boundary, so anyone with the URL can reach CWA's login page.

### vs the standalone Tailscale add-on

If you just want remote access to your *whole* HA instance, the [official community Tailscale add-on](https://github.com/hassio-addons/app-tailscale) is simpler — it puts the entire HA host on the tailnet (every published port, including this add-on's `:8083`). Use the embedded option here when you want CWA to have a *separate* tailnet identity from the HA host.

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
