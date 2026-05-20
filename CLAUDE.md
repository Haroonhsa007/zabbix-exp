# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **learning and experimentation workspace for Zabbix 7.0 LTS**, run entirely from a
local **Docker Compose** stack, with **Python** used to drive the Zabbix JSON-RPC API
for configuration and automation. There is no production target — the priority is a
fast, disposable, reproducible local environment to try things in.

Anchor everything to **Zabbix 7.0 LTS**. When a feature differs from 6.0, say so, but
default to 7.0 behavior and 7.0 image tags.

## Architecture

Two layers that talk over the API, not a single app:

1. **The stack** ([docker-compose.yml](docker-compose.yml)) — the Zabbix server itself, run as containers:
   - `postgres` (PostgreSQL 16) — the backend database; the bottleneck at any real scale.
   - `zabbix-server-pgsql` — the core engine (pollers, triggers, escalations). Listens on `10051`.
   - `zabbix-web-nginx-pgsql` — the PHP frontend + nginx. Browse it on `http://localhost:8080`.
   - `zabbix-agent2` — an agent monitoring the stack itself; also the thing to point at when learning agent items. Listens on `10050`.
   - `snmpsim` (`polinux/snmpd`) — a real net-snmp daemon (community `public`, v1/v2c on 161/udp) that gives the SNMP host actual data with no physical device. Only reachable inside the compose network.
   - The Zabbix containers are configured **entirely through `ZBX_*` / `POSTGRES_*` environment variables** — there are no hand-edited `.conf` files inside the containers. An env var like `ZBX_STARTPOLLERS` maps to the `StartPollers` parameter in `zabbix_server.conf`; `ZBX_CACHESIZE` → `CacheSize`, and so on. To change server tuning, edit the env block in compose and recreate the container — do **not** exec in and edit files.

2. **The Python automation** ([scripts/](scripts/)) — code that configures the
   running stack through the API instead of clicking the frontend. This is where the
   learning happens: create hosts, items, triggers, templates, and run queries as code.
   - [scripts/zbx_client.py](scripts/zbx_client.py) — the shared client. `connect()`
     reads `.env`, prefers `ZABBIX_TOKEN`, and falls back to `ZABBIX_USER`/`ZABBIX_PASSWORD`.
     It also holds all the **idempotent `ensure_*` helpers** — every script reuses these.
     Hosts: `ensure_host` (agent), `ensure_snmp_host`, `ensure_interfaceless_host` (HTTP).
     Items: `ensure_item` (agent), `ensure_snmp_item`, `ensure_simple_item` (ICMP/simple
     checks), `ensure_http_item`. Plus `ensure_trigger`, `set_host_location`, `ensure_map`,
     `ensure_geomap_provider`, `ensure_geomap_dashboard`.
   - [scripts/bootstrap.py](scripts/bootstrap.py) — the starter: a host group + one agent
     host pointing at the `zabbix-agent` container, with items and triggers. Re-runnable.
   - [scripts/add_hosts.py](scripts/add_hosts.py) — adds hosts of **different monitoring
     types** (Zabbix agent → `zabbix-agent`; SNMPv2c → `snmpsim`; simple-check/ICMP →
     `postgres`; HTTP agent → the frontend), each given an Islamabad/Rawalpindi inventory
     location so it plots on the geomap.
   - [scripts/create_maps.py](scripts/create_maps.py) — builds a star-topology **network
     map** (`map.create`) and a **geomap dashboard** (`dashboard.create` with a `geomap`
     widget). It also sets the global geomap tile provider via `settings.update` — without
     that, geomap widgets render an error.
   - [scripts/list_hosts.py](scripts/list_hosts.py) — a read example.
  - [scripts/scenario_lab.py](scripts/scenario_lab.py) — troubleshooting lab: inject
    faults, hints, verify fixes (`make scenario SCENARIO=…`). **Learner guide:**
    [scenarios/GUIDE.md](scenarios/GUIDE.md).
   - Uses the official **`zabbix-utils`** library (the supported binding from 7.0+),
     against `http://localhost:8080/api_jsonrpc.php`.
   - `*.create` is **not idempotent**: a second identical create errors. That's why the
     `ensure_*` helpers do *get-then-create*. For templates use `configuration.import`.
     **When adding a new script, follow the same get-or-create pattern** — don't call
     bare `*.create` in code that might run twice.

The mental model: **the stack is the system under test; the Python is how you poke it.**
Most "how do I do X in Zabbix" experiments should end up as a runnable Python script that
configures the stack, so the setup is reproducible after a `docker compose down -v`.

## Common commands

A [Makefile](Makefile) wraps the common flows (`make help` lists them); the raw
commands are below. Run from the repo root.

```bash
make up      # docker compose up -d           — start the whole stack
make ps      # docker compose ps              — services + port mappings
make logs    # docker compose logs -f server  — tail server logs (first place to debug)
make down    # docker compose down            — stop containers, KEEP the db volume
make reset   # docker compose down -v         — ALSO delete the db volume → clean reset
make venv    # create .venv and pip install -r requirements.txt
make bootstrap   # run scripts/bootstrap.py   (starter agent host)
make add-hosts   # run scripts/add_hosts.py   (SNMP/ICMP/HTTP hosts + locations)
make maps        # run scripts/create_maps.py (network map + geomap dashboard)
make hosts       # run scripts/list_hosts.py
```

`docker compose pull` updates images before recreating (7.0 point releases).

First-login credentials for the frontend at `http://localhost:8080` are **Admin / zabbix**
(change on first login). The DB schema is imported automatically by the server image's
entrypoint on first start against an empty database — there is no manual `zcat | psql` step.

Sanity-check the agent and API once the stack is healthy:

```bash
# Agent reachable from inside its container
docker compose exec zabbix-agent zabbix_get -s 127.0.0.1 -k agent.ping     # → 1

# API is up (no auth needed for apiinfo.version)
curl -s -X POST http://localhost:8080/api_jsonrpc.php \
  -H "Content-Type: application/json-rpc" \
  -d '{"jsonrpc":"2.0","method":"apiinfo.version","params":{},"id":1}'      # → "7.0.x"
```

Python automation (a venv plus the `scripts/` dir):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/bootstrap.py                # run a single automation script
```

## Conventions

- **Image tags are pinned to 7.0**, e.g. `zabbix/zabbix-server-pgsql:ubuntu-7.0-latest`.
  Keep server, web, and agent on the *same* 7.0 line to avoid schema/frontend mismatches.
- **Server config changes go in compose env vars**, never inside a running container.
- **Secrets** (`POSTGRES_PASSWORD`, API tokens) live in an `.env` file or environment,
  not hard-coded in `docker-compose.yml` or committed scripts. Keep `.env` out of git.
- **Templates as code**: export templates as **YAML** (not XML) — friendlier to review and
  diff — and re-import with `configuration.import`.
- After API changes that the server doesn't pick up immediately, force a config reload:
  `docker compose exec zabbix-server zabbix_server -R config_cache_reload`.

## Where to get Zabbix specifics

This repo's author uses the `zabbix-expert` skill for deep Zabbix knowledge (item keys,
trigger functions, API method signatures, tuning). When unsure of an exact item key,
trigger function, or API parameter, consult that skill or the official 7.0 manual at
`https://www.zabbix.com/documentation/7.0/en/manual` rather than guessing — these are
case-sensitive and unforgiving.
