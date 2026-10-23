# Tailscale distsign root keys

`roots/` holds Tailscale's public **root** keys for distsign, the scheme
Tailscale signs its packages with. The Tailscale workflow
(`.github/workflows/tailscale.yaml`) uses them, through
`.github/scripts/verify-tailscale.py`, to check that each tarball it pins was
signed by Tailscale before it opens an update PR:

```text
root key (offline, committed here)
  └─ signs  https://pkgs.tailscale.com/distsign.pub   (current signing keys)
       └─ signs  tailscale_<version>_<arch>.tgz       (via <tarball>.sig)
```

A `.sig` is an Ed25519 signature over the tarball's BLAKE2s-256 hash followed
by its length as a little-endian uint64.

The keys are committed instead of fetched, so the trust anchor is this
repository, not the download server: faking a release needs Tailscale's
offline root key, not just control of pkgs.tailscale.com.

## Source

Copied unchanged from `clientupdate/distsign/roots/` in
[tailscale/tailscale](https://github.com/tailscale/tailscale/tree/v1.104.1/clientupdate/distsign/roots)
at tag `v1.104.1` (commit `9a522a9786c97eb7910c01ccb7bd66557b04c910`).
Tailscale's own client embeds the same files to verify `tailscale update`.

## Updating

Root keys only change when Tailscale rotates them, and they rotate by shipping
a client release with the new key next to the old one. When that happens the
workflow fails with "does not validate with any root key". Copy the `.pem`
files from that directory at the newest release tag, update the tag and commit
above, and review the change like any other key change: compare it with what
the Tailscale repository shows at that tag.
