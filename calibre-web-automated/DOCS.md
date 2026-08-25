# Home Assistant Add-on: Calibre-Web Automated

## Installation

1. Add this repository (`https://github.com/Cdower/hassio-addons`) to Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Install **Calibre-Web Automated** from the store.
3. Start the add-on. The sidebar opens the direct Web UI URL in a new tab, and the app is also reachable directly at `http://<host>:8083`. Your browser/client must be able to reach `http(s)://<host>:8083`; if you access Home Assistant through a remote URL or reverse proxy that does not also expose port 8083 (for example HA Cloud), the sidebar link may not work.

## Configuration options

| Option                | Default                  | Description                                                                                                              |
| --------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `library_path`        | `/share/calibre/calibre-library` | Where the Calibre library (`metadata.db` + book folders) lives.                                                          |
| `ingest_path`         | `/share/calibre/cwa-book-ingest`  | Drop EPUB/PDF/MOBI/etc. here for automatic ingest. Files are deleted after processing.                                   |
| `config_path`         | `/share/calibre/config`  | Where CWA's `/config` (app database, user accounts, settings) lives. Clear it to fall back to `/data` (HA-managed, local); set a `/share/...` path to host `/config` on a network share. |
| `plugins_path`        | `/share/calibre/plugins` | Calibre plugins folder. Drop plugin `.zip` files here and they are registered on start; an empty folder loads nothing. Clear the option to disable the bind mount. See "Plugins" below. |
| `network_share_mode`  | `false`                  | Set `true` when the library or `config_path` lives on NFS/SMB. Disables SQLite WAL on `metadata.db`/`app.db` and switches the ingest watcher to polling. |
| `hardcover_token`     | _(empty)_                | API token for [Hardcover](https://hardcover.app) metadata enrichment.                                                    |
| `trusted_proxy_count` | `1`                      | Number of reverse proxies in front of CWA whose `X-Forwarded-*` headers should be trusted. Use `1` only when the add-on is behind exactly one reverse proxy (Cloudflare, nginx-proxy-manager, Traefik, etc.). Set higher for chained proxies. For direct access with no reverse proxy, use a lower value such as `0` if supported, rather than trusting forwarded headers from clients. |
| `log_level`           | `info`                   | One of `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`.                                                  |
| `tailscale_authkey`   | _(empty)_                | Tailscale auth key (`tskey-auth-…`). Empty disables the embedded Tailscale entirely. See "Tailscale" below.              |
| `tailscale_hostname`  | _(empty, defaults `cwa`)_| Hostname this add-on registers in your tailnet.                                                                          |
| `tailscale_serve`     | `true`                   | When `true`, exposes CWA at `https://<tailscale_hostname>.<tailnet>.ts.net` via `tailscale serve` (auto HTTPS).            |
| `tailscale_funnel`    | `false`                  | When `true` (and `tailscale_serve: true`), additionally enables Tailscale Funnel so the same URL is reachable from the public internet. Requires Funnel to be enabled for your tailnet in the admin console. |
| `tailscale_extra_args`| _(empty)_                | Extra flags appended to `tailscale up`, e.g. `--advertise-tags=tag:calibre`.                                              |
| `cloudflare_team_domain` | _(empty)_             | Your Cloudflare Zero Trust team domain (`myteam` or `myteam.cloudflareaccess.com`). Setting this together with `cloudflare_access_aud` enables Cloudflare Access mode. See "Cloudflare Access" below. |
| `cloudflare_access_aud`  | _(empty)_             | The **AUD tag** (Application Audience) of your Cloudflare Access application, from Zero Trust → Access → Applications → your app → Overview. |
| `access_users`           | `[]`                  | Emails allowed to sign in through Cloudflare. A CWA user (username = email, unusable random password) is created for each on startup. Also add the same emails to your Access policy. |

## Setup paths

### Local-volume setup (recommended for new users)

Leave the defaults. The add-on creates `/share/calibre/calibre-library`, `/share/calibre/cwa-book-ingest`, `/share/calibre/config` and `/share/calibre/plugins` on first start. Mount your `share/` over Samba or use the File Editor add-on to drop books in.

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
     - **Add-on-local `/data`-backed `/config`**: with `config_path` cleared the add-on keeps `/config` on its private `/data` directory, which isn't reachable from Samba. Either leave `config_path` on a `/share/...` path so you can copy files in directly, or use the SSH/Terminal add-on and copy your old CWA `/config` contents into `/data` (path inside this add-on's container).
     - **Network-share `/config`** (what the shipped `config_path` gives you): copy your old CWA `/config` contents into the directory `config_path` names (`/share/calibre/config` out of the box, or e.g. `/share/nas/calibre/config`).
   - Delete the sentinel from wherever `/config` lives: `rm <config_path>/.cwa-initialized`, or `rm /data/.cwa-initialized` if you cleared `config_path`, so the add-on doesn't think it's already initialized.
   - Restart the add-on.

> Switching `config_path` after the add-on has run reseeds the new target from whatever `/config` points to at startup. On a brand-new install that's the image defaults; on an existing install it's typically your previous persistent `/config`. If the config you want to keep is *not* what `/config` points to when the add-on starts, copy it into the new target manually *before* restarting.

## Plugins

Set `plugins_path` to a folder, drop your Calibre plugin `.zip` files in it (DeDRM, DeACSM, and so on) and restart the add-on. On start-up the add-on registers every `.zip` it finds with `calibre-customize -a`, and the ingest, conversion and metadata subprocesses run with that plugin directory as Calibre's configuration directory. The folder ships configured but empty, and an empty folder loads nothing — no third-party plugin code runs until you put a `.zip` in it.

Two details worth knowing:

- **Adding a plugin later.** Registration is skipped once Calibre's registry has entries, so a plugin dropped in after the first successful registration is not picked up by a plain restart. Register it from the add-on shell (SSH/Terminal add-on) with `calibre-customize -a /config/.config/calibre/plugins/<file>.zip`, or clear `/config/.config/calibre/customize.py.json` and restart to re-register everything.
- **Earlier versions.** Before v4.1.40.0 this needed a hand-written `customize.py.json`, because the base image exported a misspelled `CALIBRE_CONFIG_DIR` that Calibre ignored. That is fixed; if you wrote one by hand it is still valid and can be left alone.

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
tailscale serve --bg --service=svc:calibre --https=443 http://127.0.0.1:8083
```

(which is exactly what the add-on's init script does on each restart). You can inspect the resulting JSON-form config from the add-on shell with `tailscale serve status --json`.

### Public exposure (Funnel)

`tailscale_funnel: true` makes the same `https://<hostname>.<tailnet>.ts.net` URL reachable from the public internet. Funnel must first be enabled for your tailnet in the admin console (Settings → Feature previews → Funnel). Use this carefully — it bypasses the tailnet ACL boundary, so anyone with the URL can reach CWA's login page.

### vs the standalone Tailscale add-on

If you just want remote access to your *whole* HA instance, the [official community Tailscale add-on](https://github.com/hassio-addons/app-tailscale) is simpler — it puts the entire HA host on the tailnet (every published port, including this add-on's `:8083`). Use the embedded option here when you want CWA to have a *separate* tailnet identity from the HA host.

## Cloudflare Access — sign in with Google/Apple, no passwords (optional)

Let family and friends open your library at a public URL (e.g. `https://books.example.com`), sign in with their **Google or Apple** account via Cloudflare, and land in CWA already logged in — you never create or reset a password for them. Adding a person = adding their email in two places (Cloudflare's Access policy and this add-on's `access_users`).

How it works:

```
Browser ──► Cloudflare edge (Google/Apple sign-in, free ≤50 users)
        ──► Cloudflare Tunnel (the separate cloudflared add-on)
        ──► this add-on, port 8085 (nginx validates the signed Access JWT)
        ──► CWA, logged in as <email> via reverse-proxy header login
```

When enabled, CWA itself is pinned to `127.0.0.1` inside the container and nginx takes over: port `8083` (LAN) keeps working with normal password login exactly as before (with auth headers stripped so nobody on your LAN can impersonate a user), and port `8085` only accepts requests carrying a valid `Cf-Access-Jwt-Assertion` token — the token's signature, audience, issuer, and expiry are all verified in-container against your team's public keys. The plain `Cf-Access-Authenticated-User-Email` header is never trusted. When the options are unset, nothing changes at all.

### Setup

1. **Cloudflare Zero Trust team**: sign up at [one.dash.cloudflare.com](https://one.dash.cloudflare.com) (free plan covers 50 users). Note your team domain, e.g. `myteam.cloudflareaccess.com`. Your site's DNS must be on Cloudflare.
2. **Tunnel** — install the [cloudflared add-on](https://github.com/brenner-tobias/addon-cloudflared) and connect it with a remotely-managed tunnel token (Zero Trust → Networks → Tunnels).
3. **Public hostname** — in the tunnel's config, add a public hostname (e.g. `books.example.com`) with service `http://<container-hostname>:8085`. The exact URL to use is printed in **this add-on's log** at startup: `Point the cloudflared add-on at: http://39bd2704-calibre-web-automated:8085` (the hostname is Supervisor-assigned; yours will differ).
4. **Access application** — Zero Trust → Access → Applications → Add → Self-hosted, domain `books.example.com`.
   - **Login methods**: Google is built-in (Settings → Authentication → Login methods → Add → Google; needs a small Google Cloud Console OAuth app). For Apple users the simplest is **One-time PIN** (they get a code at their iCloud/any email — no Apple developer setup); generic OIDC with Sign in with Apple also works but is fiddly.
   - **Policy**: Allow → Include → Emails → list the same emails as `access_users`.
   - Copy the app's **AUD tag** from its Overview tab.
5. **This add-on's options**:

   ```yaml
   cloudflare_team_domain: "myteam"
   cloudflare_access_aud: "b53…64-hex…9d"
   access_users:
     - alice@gmail.com
     - bob@icloud.com
   trusted_proxy_count: 2   # Cloudflare edge + this add-on's nginx
   ```

   Restart the add-on. Each `access_users` email gets a CWA account (username = email, default role/sidebar — adjust per-user in CWA's admin page). Your existing `admin` account keeps working with its password on the LAN URL.

### Notes

- **Adding/removing a user**: add or remove the email in both the Access policy and `access_users`, restart the add-on. Removing from the Access policy alone blocks sign-in immediately; the CWA account is kept (delete it in CWA's admin page if you want it gone).
- **Alternative to listing every email**: CWA also has *Reverse Proxy Auto Create Users* in its admin settings — anyone your Access policy admits gets an account automatically. This add-on deliberately leaves that off so `access_users` stays the allowlist; enable it in CWA's UI if you prefer policy-only management.
- **Kobo sync / OPDS apps** can't complete Cloudflare's browser sign-in. Keep those on the LAN URL (`http://<host>:8083`) or Tailscale, or add a [service-token or bypass policy](https://developers.cloudflare.com/cloudflare-one/policies/access/) for those paths in Cloudflare (out of scope here).
- **Port 8085** is intentionally unmapped in the add-on's network config. Leave it that way — the cloudflared add-on reaches it over Home Assistant's internal docker network, and not mapping it keeps the JWT-gated listener off your LAN.
- **Tailscale** continues to work in this mode (it proxies to the LAN listener → password login).
- Turning the feature off (clearing the options) flips CWA's reverse-proxy header login back off automatically on the next start.

## Known issues

- **Kobo sync URLs**: CWA generates absolute URLs for Kobo sync based on the host it sees the request from. Make sure your Kobo can reach CWA at that host:port (open Settings → Server → Server URLs in CWA to inspect the URL it generated). If CWA is fronted by Cloudflare/nginx-proxy-manager/Traefik, bump `trusted_proxy_count` so CWA picks up the original host from `X-Forwarded-Host`.
- **File ownership**: The app runs as uid/gid 1000 to match HA's `/share` and `/media`, so files it writes there are owned 1000:1000. If you also access the share over Samba and need different ownership, change it on the host or via Samba's `force user` option.
- **Backups**: CWA's verbose `cwa.log` and the temporary `processed_books/` directory are excluded from HA backups (see `backup_exclude` in `config.yaml`). Library files in `/share` are not in HA backups by design — back those up separately.

## Persistence

CWA's app database, user accounts, and settings live wherever `config_path` points — `/share/calibre/config` as shipped, which keeps them on the same share as the library and reachable over Samba. Clear `config_path` to store them in HA's per-add-on `/data` directory instead, which survives add-on upgrades and uninstalls but isn't reachable from Samba. Library files in `library_path` (e.g. under `/share`) are always independent of the add-on lifecycle.

This add-on uses `privileged: [SYS_ADMIN]` and `apparmor: false` to bind-mount your chosen `/config` path over the base image's `VOLUME /config`. Home Assistant marks add-ons with elevated capabilities — that's expected here.

## Base image

The add-on is built on [Calibre-Web NextGen][nextgen], a fork of [Calibre-Web Automated][cwa] taken at CWA v4.0.6. It keeps CWA's data format, configuration and container layout, so switching between the two in either direction needs no migration. Versions before 4.1.40.0 of this add-on were built on `crocodilestick/calibre-web-automated:v4.0.6` directly; upgrading carries your library, users and settings over untouched.

## Upgrades

When a new base image is released:

1. The add-on bumps the pinned tag in `build.yaml` and `version:` in `config.yaml`. (Maintainers: follow `.claude/skills/update-base-image/SKILL.md` — the add-on overrides files inside the upstream image, notably the CWA s6 run script, which must be re-diffed on every bump.)
2. HA shows an upgrade in the Add-on Store.
3. Click upgrade. The container is rebuilt; `/data` is preserved.

If you self-build, click **Rebuild** in the add-on's three-dot menu.

## Support

<https://github.com/Cdower/hassio-addons/issues>

[cwa]: https://github.com/crocodilestick/Calibre-Web-Automated
[nextgen]: https://github.com/new-usemame/Calibre-Web-NextGen
