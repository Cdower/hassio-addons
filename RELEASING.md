# Releasing

Each add-on in this repository is versioned and released on its own. A release
covers one add-on only, so shipping a fix for one never republishes another.

## Tag convention

Release tags name the add-on they belong to:

```text
<slug>-v<version>
```

For example `calibre-web-automated-v4.0.6.11` or `acpro-thermostat-v1.0.1`.
The `<slug>` is the `slug:` field from that add-on's `config.yaml`, and
`<version>` must match its `version:` field exactly — the Supervisor pulls the
image tag named by `config.yaml`, so a tag that disagrees with it would publish
images nobody can install. `Deploy` fails the build rather than let that
through.

Version numbers are per add-on and unrelated to each other. Calibre-Web
Automated tracks its upstream release (`4.0.6.x`); AC Pro Thermostat uses plain
semver.

> Tags from before the repository held more than one add-on are bare
> (`v4.0.6.10`) and all refer to Calibre-Web Automated. They are kept as
> history; new releases must use the prefixed form.

## Cutting a release

1. Bump `version:` in `<addon>/config.yaml`.
2. Update `<addon>/CHANGELOG.md`: rename the `## [Unreleased]` heading to
   `## [<version>] - <YYYY-MM-DD>` and start a fresh `## [Unreleased]` above
   it. The release notes are taken verbatim from that section.
3. Merge to `main` and let CI pass.
4. Run the **Release** workflow (Actions → Release → Run workflow) and give it
   the add-on slug.

That workflow tags the current `main` commit, publishes a GitHub release with
the changelog section as its notes, and then builds and pushes only that
add-on's images to GHCR — `:<version>` and `:latest`, per architecture.

Tick **dry_run** to see the resolved tag and release notes without creating
anything.

Creating the release by hand instead of running the workflow also works: the
`Deploy` workflow reacts to any published release, and takes the add-on and
version from the tag. Just make sure the tag follows the convention above.

## Republishing without a release

To rebuild and push images without cutting a new release — a base image moved,
or a push failed partway — run the **Deploy** workflow directly (Actions →
Deploy → Run workflow) with the add-on slug. It publishes the version in that
add-on's `config.yaml`; the optional `version` input overrides it, and the
optional `ref` input builds a specific tag or commit rather than the default
branch.

## Guard rails

The release tooling refuses to:

- release an add-on whose `config.yaml` still says `version: "dev"`, the
  local-build placeholder;
- reuse a tag that already exists — bump the version instead;
- publish a release whose tag version and `config.yaml` version disagree;
- act on a tag that does not name a known add-on.
