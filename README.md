# Zabbix test

A local **Zabbix 7.0 LTS** learning sandbox: a full Docker Compose stack plus a
Python automation layer that configures it through the JSON-RPC API. Disposable
and reproducible — tear it down and rebuild any time.

## Layout

```
docker-compose.yml   # postgres + zabbix-server + web + agent2 + snmpsim (all 7.0)
.env / .env.example  # secrets + connection settings (.env is gitignored)
requirements.txt     # zabbix-utils + python-dotenv
Makefile             # shortcuts: make up / down / reset / bootstrap / add-hosts / maps
scripts/
  zbx_client.py      # API client + idempotent get-or-create helpers
  bootstrap.py       # creates a sample agent host, items, and triggers (re-runnable)
  add_hosts.py       # adds hosts of different types (agent/SNMP/ICMP/HTTP) + locations
  create_maps.py     # builds the network map + geomap dashboard
  list_hosts.py      # read example: prints hosts and interfaces
templates/           # put exported YAML templates here for version control
```

## Quick start

```bash
# 1. Start the stack (first boot imports the DB schema automatically — give it a minute)
make up           # or: docker compose up -d
make ps           # wait until zabbix-web and zabbix-server are healthy/up

# 2. Open the frontend and log in
#    http://localhost:8080   —   Admin / zabbix   (change the password on first login)

# 3. Set up Python and configure the lab via the API
make venv         # creates .venv and installs deps
make bootstrap    # the starter agent host, items, triggers (idempotent)
make add-hosts    # more hosts: SNMP, ICMP, HTTP — each placed in Islamabad/Rawalpindi
make maps         # corporate topology map + geomap dashboard
make hosts        # lists hosts through the API
```

### Troubleshooting lab (break/fix scenarios)

**Read the guide first:** [scenarios/GUIDE.md](scenarios/GUIDE.md) — step-by-step method, all 10 real-world scenarios, UI map, progress tracker, and answer key.

```bash
make scenario-list
make scenario SCENARIO=agent-down   # inject fault + NOC ticket
make scenario-hint                  # progressive hints
make scenario-verify                # checks your fix
make scenario-reset                 # undo before the next one
```

After `make maps`, view them in the frontend:

- **Monitoring → Maps → Lab corporate topology** — five cooperating corporate networks,
  shared internal segments, edge clusters (homes / shops / SOHO), and the four lab hosts
  with live status coloring.
- **Dashboards → Lab geomap** — hosts plotted over Islamabad/Rawalpindi on OpenStreetMap,
  alongside the network map widget.

The `bootstrap` script logs in with `Admin` / `zabbix` from `.env` by default.
To use a token instead, create one in **Administration → API tokens**, put it in
`ZABBIX_TOKEN` in `.env`, and the scripts will prefer it.

## Resetting

```bash
make down     # stop containers, keep the database
make reset    # stop containers AND wipe the database volume (clean slate)
```

## Notes

- All Zabbix container tuning lives in the `environment:` blocks in
  `docker-compose.yml` (`ZBX_*` vars map to `zabbix_server.conf` parameters).
  Edit there and `make up` to apply — don't edit files inside the containers.
- If the server doesn't pick up an API change immediately:
  `docker compose exec zabbix-server zabbix_server -R config_cache_reload`.
- See [CLAUDE.md](CLAUDE.md) for the architecture and conventions in more depth.
