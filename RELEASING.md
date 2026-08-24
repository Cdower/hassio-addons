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

1. Run the **Bump** workflow (Actions → Bump → Run workflow) with the add-on
   slug and the new version. It opens a PR that sets `version:` in
   `<addon>/config.yaml` and promotes that add-on's changelog: the
   `## [Unreleased]` heading becomes `## [<version>] - <YYYY-MM-DD>`, with a
   fresh `## [Unreleased]` above it.
2. Review and merge that PR. Check the release notes while you are there —
   the promoted section is published verbatim. If the add-on had nothing
   under `## [Unreleased]`, the PR says so and leaves a placeholder to
   replace.
3. Run the **Release** workflow (Actions → Release → Run workflow) and give it
   the add-on slug.

Steps 1 and 2 are a convenience; editing `config.yaml` and `CHANGELOG.md` by
hand in an ordinary PR does the same job. Either way the version lands on
`main` before the release is cut, because `config.yaml` is what the Supervisor
reads.

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

## CI on bump PRs

Merging needs the required `CI` check, and a branch pushed with the default
`GITHUB_TOKEN` triggers no workflow run at all — left alone, a bump PR would
have no check to satisfy and could never merge. So the Bump workflow starts CI
on the branch itself, which is allowed because dispatch events are exempt from
that rule. The run reports against the branch's head commit, which is the PR's
head commit, so the gate still sees it.

That works with no setup. If you would rather have the ordinary flow, add a
repository secret named `BUMP_TOKEN` holding a PAT with `contents:write` and
`pull-requests:write`: the workflow pushes with it instead, CI attaches to the
PR by itself, and the manual dispatch is skipped.

## Guard rails

The release tooling refuses to:

- release an add-on whose `config.yaml` still says `version: "dev"`, the
  local-build placeholder;
- bump to a version that sorts at or before the current one;
- bump to an already-released version, or start a bump whose branch is still
  open;
- reuse a tag that already exists — bump the version instead;
- publish a release whose tag version and `config.yaml` version disagree;
- act on a tag that does not name a known add-on.
