# Security Policy

## Supported versions

Each add-on and integration in this repository is supported at its latest
release only. Fixes ship in a new release; older versions are not patched.

| Component | Supported |
| --- | --- |
| Calibre-Web Automated add-on | Latest release |
| AC Pro Thermostat add-on | Latest release |
| Tempur-Pedic Sleeptracker integration | Latest commit on `main` |

A problem in something an add-on only packages (Calibre-Web NextGen,
Tailscale, a Python library) is best reported to that project. Report it here
as well if the add-on's own configuration or scripts make it worse, or if the
add-on needs to pick up a fixed version.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately
through GitHub: on this repository's **Security** tab, choose **Report a
vulnerability**. That opens a private advisory only the maintainer can see.

Include the add-on or integration and its version, how it is configured (the
access mode, for Calibre-Web Automated), and the steps that show the problem.

This is a personal project maintained in spare time. Expect a first reply
within about a week. If the report is accepted, the fix is released and
credited in the changelog unless you prefer otherwise; if it is declined, you
will be told why.

## How dependencies are kept current

Every dependency is pinned (commit SHAs, hashes, image digests or, for the
add-on base images, exact release tags) and moved by reviewed pull requests:
see the dependency sections of [RELEASING.md](RELEASING.md).
