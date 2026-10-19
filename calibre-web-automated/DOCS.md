# Home Assistant Add-on: Calibre-Web Automated

## Installation

1. Add this repository (`https://github.com/Cdower/hassio-addons`) to Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Install **Calibre-Web Automated** from the store.
3. Start the add-on. The sidebar opens the direct Web UI URL in a new tab, and the app is also reachable directly at `http://<host>:8083`. Your browser/client must be able to reach `http(s)://<host>:8083`; if you access Home Assistant through a remote URL or reverse proxy that does not also expose port 8083 (for example HA Cloud), the sidebar link may not work.

## Configuration options

| Option                | Default                  | Description                                                                                                              |
| --------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `library_path`        | `/addon_config/calibre-library` | Where the Calibre library (`metadata.db` + book folders) lives.                                                          |
| `ingest_path`         | `/addon_config/cwa-book-ingest`  | Drop EPUB/PDF/MOBI/etc. here for automatic ingest. Files are deleted after processing.                                   |
| `config_path`         | _(empty)_                | **Deprecated.** CWA's `/config` (app database, user accounts, settings) now always lives on the add-on's local storage. If set, it is only used once, to import an existing config from that folder. See "Persistence" below. |
| `plugins_path`        | `/addon_config/plugins`  | Calibre plugins folder. Drop plugin `.zip` files here and they are registered on start; an empty folder loads nothing. Clear the option to disable the bind mount. See "Plugins" below. |
| `metadata_providers_path` | _(empty)_            | Folder of custom metadata provider `.py` files to add next to the built-in ones. See "Custom metadata providers" below. |
| `network_share_mode`  | `false`                  | Set `true` when the library lives on NFS/SMB. Disables SQLite WAL on `metadata.db`/`app.db` and switches the ingest watcher to polling. Turned on automatically when `library_path` is on `smb_share`. |
| `smb_share`           | _(empty)_                | An SMB/CIFS share for the add-on to mount itself at `/mnt/smb`, e.g. `//192.168.1.10/calibre`. See "SMB share" below. |
| `smb_username`        | _(empty)_                | Username for `smb_share`. Leave empty to connect as a guest.                                                             |
| `smb_password`        | _(empty)_                | Password for `smb_share`.                                                                                                |
| `smb_domain`          | _(empty)_                | Windows domain or workgroup for `smb_share`, if your NAS needs one.                                                      |
| `smb_version`         | _(empty, negotiated)_    | Force an SMB protocol version: `3.1.1`, `3.0` or `2.1`.                                                                  |
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

Leave the defaults. The add-on creates `calibre-library`, `cwa-book-ingest` and `plugins` in its own config folder, which it sees as `/addon_config`. On the Home Assistant host that folder is `/addon_configs/<id>_calibre-web-automated/`; the Samba add-on shares it as `addon_configs`, and the File Editor add-on can reach it too, so that is where you drop books in. Everything there is part of the add-on's own backups (see "Backups" below).

> Earlier versions shipped these defaults under `/share/calibre/`, which the add-on's backups don't include. An install that never changed these options keeps using its existing `/share/calibre/...` folders after the upgrade, and the log says so; move the folders into the add-on's config folder (and restart) to bring them into its backups.

### Network-share setup (NAS users / migrating from existing CWA)

Only the library and ingest folders (and, if you like, the plugins and metadata-provider folders) go on the NAS. CWA's own `/config` always stays on the add-on's local storage: SQLite's file locking is not reliable over the network.

1. **Make the share available to the add-on.** Either:
   - **SMB/CIFS: let the add-on mount it (recommended for SMB).** Set `smb_share`, `smb_username` and `smb_password`; the share appears at `/mnt/smb`. See "SMB share" below for why.
   - **NFS: use Home Assistant's Network Storage** (Settings → System → Storage → Add network storage), which mounts it under `/share/<name>`.
2. **Set the paths** in this add-on's config to point inside that mount:
   - `library_path: /mnt/smb/calibre-library` (or `/share/<name>/calibre-library` for NFS)
   - `ingest_path: /mnt/smb/cwa-book-ingest`
   - (optional) `plugins_path: /mnt/smb/plugins`
   - (optional) `metadata_providers_path: /mnt/smb/metadata-providers`
3. **Set `network_share_mode: true`** for NFS. It disables SQLite WAL (which corrupts on network shares) on `metadata.db` and switches the ingest watcher from inotify to polling. It is turned on automatically when `library_path` is on `smb_share`; if only the ingest folder is there, the add-on just switches the ingest watcher to polling.
4. **Migrating from an existing CWA install**:
   - Stop your old container.
   - Copy `metadata.db` and the book folders to the new `library_path`.
   - To keep user accounts and CWA's app database, copy your old CWA `/config` contents into a folder the add-on can see (e.g. `/share/calibre/config`), set `config_path` to that folder, and start the add-on. It imports the folder into its local storage once; then clear `config_path`. The import only happens while the local storage has no `app.db` yet — on an add-on that has already started without one, first delete the local `app.db` and the import marker with the SSH/Terminal add-on (`docker exec` into the add-on, then `rm /config/app.db /config/.cwa-config-imported`).
   - Restart the add-on.

### SMB share

Home Assistant's Network Storage mounts SMB/CIFS shares with every file owned by root and writable only by root, and it has no setting to change that. CWA runs as uid 1000, so on such a mount it can read your books but cannot write anything — ingest, metadata edits and `metadata.db` updates all fail. (NFS keeps the NAS's real file owners, so it does not have this problem.)

Setting `smb_share` makes the add-on mount the share itself, at `/mnt/smb`, with every file owned by the uid/gid CWA runs as:

```yaml
smb_share: "//192.168.1.10/calibre"
smb_username: "ha-calibre"
smb_password: "…"
library_path: /mnt/smb/calibre-library
ingest_path: /mnt/smb/cwa-book-ingest
```

- The mount exists only inside this add-on; Home Assistant's Storage page does not list it. You can keep the same share in Network Storage too if other add-ons use it.
- The add-on retries the mount for about 20 seconds (the NAS may still be waking up), then refuses to start rather than pointing CWA at empty folders.
- The password is passed to the mount through a temporary file that is deleted right after, so it does not show up in the mount table or process list. It is stored in the add-on's options like any other add-on password; use a NAS account that can reach only this share.
- `network_share_mode` is turned on automatically when `library_path` is on the share. If only `ingest_path` is, the add-on only switches the ingest watcher to polling (`CWA_WATCH_MODE=poll`), since inotify does not see files added to the share from other machines.
- Paths under `/mnt/smb` are refused when `smb_share` is empty, since they would point into the container's throwaway filesystem.

## Plugins

Set `plugins_path` to a folder, drop your Calibre plugin `.zip` files in it (DeDRM, DeACSM, and so on) and restart the add-on. On start-up the add-on registers every `.zip` it finds with `calibre-customize -a`, and the ingest, conversion and metadata subprocesses run with that plugin directory as Calibre's configuration directory. The folder ships configured but empty, and an empty folder loads nothing — no third-party plugin code runs until you put a `.zip` in it.

Two details worth knowing:

- **Adding a plugin later.** Registration is skipped once Calibre's registry has entries, so a plugin dropped in after the first successful registration is not picked up by a plain restart. Register it from the add-on shell (SSH/Terminal add-on) with `calibre-customize -a /config/.config/calibre/plugins/<file>.zip`, or clear `/config/.config/calibre/customize.py.json` and restart to re-register everything.
- **Earlier versions.** Before v4.1.40.0 this needed a hand-written `customize.py.json`, because the base image exported a misspelled `CALIBRE_CONFIG_DIR` that Calibre ignored. That is fixed; if you wrote one by hand it is still valid and can be left alone.

## Custom metadata providers

CWA looks up book metadata through the providers in `/app/calibre-web-automated/cps/metadata_provider/` inside the container (Google, Amazon, Hardcover, arXiv, …). You can add your own without rebuilding the image or touching the built-in ones:

1. Set `metadata_providers_path`, e.g. `/addon_config/metadata-providers` (the folder is created if missing).
2. Put each provider in it as a single `.py` file, written against CWA's `cps.services.Metadata` interface (see the add-on's own `arxiv.py` for an example). The file name becomes the module name, so it must be a valid Python identifier: `my_source.py`, not `my-source.py`.
3. Restart the add-on. The log lists what was installed, and the provider shows up in CWA's metadata search.

How it behaves:

- **Built-ins are never overwritten.** A file named like a built-in provider (`google.py`, `arxiv.py`, …) is skipped with a warning in the log. Rename it to add it alongside.
- **Removing a file uninstalls it** on the next restart. Clearing the option removes all of them.
- Only top-level `.py` files are installed. Subfolders, other files and hidden files (including macOS `._*` files) are ignored. Providers can only use Python packages the image already ships.
- **This runs code inside CWA.** Anyone who can write to that folder can run code as the CWA user, the same as with `plugins_path`. Keep it somewhere only you can write to.

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

## Persistence

CWA's app database, user accounts, and settings live in the add-on's local `/data` directory, which survives add-on upgrades and is included in Home Assistant backups, but isn't reachable from Samba. The library, ingest and plugins folders live in the add-on's config folder (`/addon_config`) by default, also part of its backups, or wherever their options point.

Earlier versions could keep this on a share via `config_path`, and shipped with `config_path: /share/calibre/config`. On the first start of this version, the add-on copies CWA's config from `config_path` (or from `/share/calibre/config` if `config_path` was never saved) into `/data`, as long as `/data` does not already have an `app.db`. The old copy is left where it was but is no longer used; clear `config_path` once the log says the import is done.

## Backups

A Home Assistant backup of this add-on contains exactly two folders: its `/data` (CWA's app database, users, settings, Tailscale state) and its config folder `/addon_config` (by default the library, ingest and plugins folders). Nothing else is in it:

- **Paths on the SMB share** (`/mnt/smb/...`) live on your NAS; back them up there.
- **Paths under `/share` or `/media`** are only in full Home Assistant backups (or partial ones with the Share/Media folder ticked), never in the add-on's own backup, including the one Home Assistant takes automatically before an add-on update. The add-on logs a warning at startup for every path option outside `/addon_config`, `/data` and `/mnt/smb`.

Keeping the library in `/addon_config` means it is copied into every backup of the add-on, including those automatic pre-update ones. That is the point, but with a large library it makes those backups large and slower.

### Databases

Home Assistant backs add-ons up by copying their files while they keep running, and it does nothing special for databases. Copying a SQLite database that is being written to (or one in WAL mode, whose latest changes sit in a separate `-wal` file) can capture a damaged or out-of-date copy. CWA has several: `app.db` and `cwa.db` in `/data`, and the library's `metadata.db`.

So the add-on takes care of it:

1. Just before a backup, Home Assistant runs the add-on's `backup_pre` command. It copies every SQLite database in `/data` and `/addon_config` to `<name>.db.cwa-snapshot`, using SQLite's own backup API, which produces a consistent copy of a database in use.
   Last, it writes a list of those snapshots to `/data/.cwa-backup-snapshots`.
2. Home Assistant copies the folders, snapshots and list included. `backup_post` then deletes the snapshots and the list.
3. When the add-on starts from a restored backup, it finds the list and puts each listed snapshot in place of its database (deleting any leftover `-wal`/`-shm`/`-journal` files) before CWA opens anything. On a normal start there is no list, so the add-on doesn't search the library for snapshots.

If the add-on was stopped when the backup was taken, Home Assistant skips `backup_pre`; the database files are then not in use and are copied as they are. If the add-on is restarted while a backup is running, the next start rolls the databases back to when that backup began; changes made during the backup are lost.

`cwa.log` and the temporary `processed_books/` folder are left out of backups.

## Security

The add-on needs the `SYS_ADMIN` capability to bind-mount your chosen paths over the base image's volumes and to mount `smb_share`. Instead of turning AppArmor off for that, it ships its own AppArmor profile (`apparmor.txt`): Docker's default container profile plus permission for exactly those mounts. Home Assistant should rate the add-on's security 5 out of 8 — one point off for its capabilities, one point back for the custom profile.

It also holds `DAC_READ_SEARCH`, only because `mount.cifs` refuses to run without it: while dropping privileges it puts that capability back into its own set, which fails with `Unable to apply new capability set` if the container was never given it. Nothing in the add-on uses it, and the AppArmor profile denies its use, which keeps `open_by_handle_at` (the call behind the "Shocker" container escape) refused just as under Docker's defaults. That protection comes from AppArmor alone: holding the capability also lifts Docker's default seccomp block on `open_by_handle_at`, so on a host where AppArmor is unavailable (Home Assistant then runs add-ons without their profiles) nothing refuses it.

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
