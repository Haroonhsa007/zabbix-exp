# Security Policy

This repository is a **local Zabbix 7.0 LTS learning sandbox** (Docker Compose +
Python API scripts). It is not a production deployment and is not intended to be
exposed to untrusted networks.

## Supported Versions

Security-relevant maintenance applies to the **current default stack** in
`docker-compose.yml` and the Python dependencies in `requirements.txt`.

| Component | Version / line | Supported |
| --------- | -------------- | --------- |
| Zabbix (server, web, agent2) | **7.0 LTS** (`ubuntu-7.0-latest` images) | :white_check_mark: |
| PostgreSQL | **16** (`postgres:16-alpine`) | :white_check_mark: |
| Zabbix 6.x or earlier in this repo | — | :x: |
| Ad-hoc image tags you change locally | — | :x: |

Older Zabbix major versions are out of scope for this project. If you pin a
different tag, you are responsible for tracking upstream advisories yourself.

## Scope

| In scope for this repo | Out of scope (report upstream) |
| ---------------------- | ------------------------------ |
| Scripts under `scripts/`, Makefile, compose/env examples | CVEs in Zabbix Server, Web, or Agent |
| Accidental secret exposure in committed files | CVEs in PostgreSQL or base OS images |
| Misconfiguration documented in this lab | Issues in `polinux/snmpd` or other third-party images |

Upstream references:

- [Zabbix security advisories](https://www.zabbix.com/documentation/current/en/manual/appendix/security_advisories)
- [PostgreSQL security](https://www.postgresql.org/support/security/)
- [Docker Hub — Zabbix official images](https://hub.docker.com/u/zabbix)

## Local Lab Risks (not bugs in this repo)

- Default frontend login is **Admin / zabbix** until you change it on first login.
- `.env` holds API tokens and database passwords — it is gitignored; never commit it.
- Published ports (`8080`, `10050`, `10051`) are for **localhost learning only**;
  do not bind them on a public interface without hardening.

## Reporting a Vulnerability

**Repository-specific issues** (leaked credentials in history, unsafe defaults in
our scripts, Dependabot misconfiguration, etc.):

1. Prefer **[GitHub Security Advisories](https://github.com/advisories)** (Private
   vulnerability report) if the repository is on GitHub.
2. Otherwise open a **private** issue or contact the maintainer directly — do not
   post secrets or live tokens in public issues.

**What to include:** affected file or image, steps to reproduce, impact, and
whether you believe it affects only local dev or a fork deployed elsewhere.

**Response expectations:** best-effort review within **14 days** for confirmed
reports; we may ask for clarification. Accepted issues get a fix or documented
mitigation; declined reports get a short explanation (duplicate, upstream-only,
out of scope for a learning lab).

**Upstream product vulnerabilities** in Zabbix, PostgreSQL, or container bases
should be reported to those projects (see links above). We will bump pinned
images and dependencies via Dependabot and manual updates when fixes are
available.

## Dependency Updates

Python (`requirements.txt`) and Docker (`docker-compose.yml`) updates are handled
by [Dependabot](.github/dependabot.yml) on a weekly schedule. Review PRs before
merging — especially Zabbix image bumps, which may require a `make reset` or
migration per [Zabbix upgrade notes](https://www.zabbix.com/documentation/7.0/en/manual/installation/upgrade).
