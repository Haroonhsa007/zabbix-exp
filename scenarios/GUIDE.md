# Zabbix Troubleshooting Lab — Learner’s Guide

**Preferred document.** Work through this guide scenario by scenario. Scripts inject breaks; you fix them in the UI like a real on-call shift.


|           |                                                           |
| --------- | --------------------------------------------------------- |
| **Stack** | Zabbix 7.0 LTS · Docker Compose · `http://localhost:8080` |
| **Login** | `Admin` / `zabbix` (change on first login)                |
| **Hosts** | `Learning/Lab` group — Islamabad / Rawalpindi geomap      |
| **Map**   | Monitoring → Maps → **Lab corporate topology**            |


---

## Table of contents

1. [Before you start](#1-before-you-start)
2. [How this lab is wired](#2-how-this-lab-is-wired)
3. [The troubleshooting method](#3-the-troubleshooting-method)
4. [Where to look in the UI (7.0)](#4-where-to-look-in-the-ui-70)
5. [Commands cheat sheet](#5-commands-cheat-sheet)
6. [Scenario walkthroughs](#6-scenario-walkthroughs)
7. [Learning path & progress tracker](#7-learning-path--progress-tracker)
8. [Working with an AI coach](#8-working-with-an-ai-coach)
9. [Answer key](#9-answer-key)
10. [When things go wrong](#10-when-things-go-wrong)

---

## 1. Before you start

### One-time setup

```bash
make down && make up && make bootstrap && make add-hosts && make maps && make hosts

cd /path/to/zabbix_test
make up              # wait until zabbix-web is healthy
make venv
make bootstrap       # fixes Zabbix server → agent container
make add-hosts       # four lab hosts + triggers
make maps            # topology map + geomap dashboard
```

Confirm the API: `make api-version` → `7.0.x`.

### Per scenario (repeat every time)

```bash
make scenario-reset                              # clean slate
make scenario SCENARIO=<id>                      # inject fault + ticket
# … you investigate and fix in the UI …
make scenario-verify                             # automated check
make scenario-reset                              # before the next scenario
```

Other commands: `make scenario-list`, `make scenario-hint`, `make scenario-reveal`, `make scenario-status`.

**Rule:** Only one active scenario. Always `scenario-reset` before starting the next.

### What you need open

- Browser: Zabbix frontend
- Terminal: `make logs` in another tab (server poller errors)
- Optional: this guide + `make scenario-hint`

---

## 2. How this lab is wired

```text
                    ┌─────────────────┐
                    │  Zabbix server  │  ← polls everything
                    │   (container)   │
                    └────────┬────────┘
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    agent:10050          SNMP:161            fping/HTTP
         │                   │                   │
  ┌──────▼──────┐     ┌──────▼──────┐    ┌──────▼──────────┐
  │ zabbix-agent│     │   snmpsim   │    │ postgres / web  │
  │  container  │     │  container  │    │   containers    │
  └─────────────┘     └─────────────┘    └─────────────────┘
```


| Host            | Technical name     | Monitoring type        | Points at                                 |
| --------------- | ------------------ | ---------------------- | ----------------------------------------- |
| Test app server | `test-host-01`     | Zabbix agent (passive) | `zabbix-agent:10050`                      |
| SNMP router     | `snmp-device-01`   | SNMPv2c                | `snmpsim:161`, macro `{$SNMP_COMMUNITY}`  |
| WAN probe       | `router-icmp-01`   | Simple check (ICMP)    | Interface address → `postgres`            |
| UI health       | `frontend-http-01` | HTTP agent             | `http://zabbix-web:8080/`                 |
| Monitoring core | `Zabbix server`    | Agent (Linux template) | Should be `zabbix-agent`, not `127.0.0.1` |


Triggers you will see in Problems:


| Trigger                                   | Host                   |
| ----------------------------------------- | ---------------------- |
| `test-host-01: agent is not responding`   | agent `nodata`         |
| `snmp-device-01: SNMP not responding`     | SNMP `nodata`          |
| `router-icmp-01: host unreachable (ICMP)` | `icmpping = 0`         |
| `frontend-http-01: no data from frontend` | HTTP `nodata`          |
| `test-host-01: CPU load is high`          | needs `make bootstrap` |


---

## 3. The troubleshooting method

Use the same order every scenario. Skipping steps is how real outages get longer.

### Step A — Triage (2 minutes)

1. **Monitoring → Problems** — what fired? severity? how long?
2. Note **host name** and **trigger description** — that narrows the layer (agent vs SNMP vs URL vs config).

### Step B — Data layer (5 minutes)

1. **Monitoring → Latest data** — filter by host.
2. For each suspect item check:
  - **Last check** — recent or stale?
  - **Last value** — `nodata`, `0`, `1`, error text?
  - **Info** column — often “cannot connect”, “timeout”, “404”.


| Last value          | Often means                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------ |
| *nodata*            | Poller never got data — wrong address, disabled item/host, auth failure, or not polled yet |
| `0`                 | Check ran; result is “down” (ICMP, service down)                                           |
| `1`                 | Check ran; “up” (agent ping, icmpping)                                                     |
| error / unsupported | Wrong key, OID, URL, or permissions                                                        |


### Step C — Configuration (5–10 minutes)

1. **Data collection → Hosts** → click host name.
2. Tabs to visit depending on type:


| Symptom                    | Check first                                                         |
| -------------------------- | ------------------------------------------------------------------- |
| Agent / nodata             | **Interfaces** (DNS/IP/port), then **Items** (enabled? key?)        |
| SNMP                       | **Macros** (`{$SNMP_COMMUNITY}`), **Interfaces**, item **SNMP OID** |
| ICMP                       | **Interfaces** (target IP/DNS), item type **Simple check**          |
| HTTP                       | **Items** → URL, **Status codes**, no interface needed              |
| Alert but “server is fine” | **Maintenance**, **Items** disabled, **Triggers** threshold         |
| Nothing in Problems        | **Maintenance**, host **Disabled**                                  |


### Step D — Reproduce from the server (optional)

From the host running pollers (here: `zabbix-server` container):

```bash
# Agent
docker compose exec zabbix-server zabbix_get -s zabbix-agent -k agent.ping

# ICMP target (when interface DNS is postgres)
docker compose exec zabbix-server fping -C1 postgres

# SNMP (community public on snmpsim)
docker compose exec zabbix-server snmpget -v2c -c public snmpsim 1.3.6.1.2.1.1.5.0
```

If manual test works but Zabbix shows nodata → config mismatch (wrong DNS on interface, macro, URL).

### Step E — Fix one thing → wait → verify

- Change **one** setting; click **Update**.
- Wait **30–90 seconds** (or use **Execute now** on the item).
- Refresh Latest data; run `make scenario-verify`.

### Step F — Retrospective (1 minute)

Ask: *What signal told me the root cause? How do I prevent this in production?*

---

## 4. Where to look in the UI (7.0)

Menu names for Zabbix 7.0:


| Goal            | Menu path                                      |
| --------------- | ---------------------------------------------- |
| Active alerts   | **Monitoring → Problems**                      |
| Current values  | **Monitoring → Latest data**                   |
| Host config     | **Data collection → Hosts** → *hostname*       |
| Items           | Host → **Items**                               |
| Triggers        | Host → **Triggers**                            |
| Interfaces      | Host → **Interfaces**                          |
| Macros          | Host → **Macros**                              |
| Maintenance     | **Data collection → Maintenance**              |
| Network picture | **Monitoring → Maps → Lab corporate topology** |
| Geomap          | **Dashboards → Lab geomap**                    |
| Server log      | terminal: `make logs`                          |


**Host list icons:** orange wrench = maintenance; disabled hosts show grey/disabled state in list.

**Map:** Red host = problem on that host. Red **link** = linked trigger in PROBLEM state (e.g. WAN ICMP).

---

## 5. Commands cheat sheet

```bash
# Scenarios
make scenario-list
make scenario SCENARIO=agent-down
make scenario-hint
make scenario-verify
make scenario-reveal      # spoiler
make scenario-reset

# Restore lab defaults
make add-hosts
make bootstrap

# Stack
make up | make ps | make logs | make down | make reset

# API smoke test
make api-version
```

---

## 6. Scenario walkthroughs

For each scenario: run `make scenario SCENARIO=<id>`, follow the investigation guide, fix in the UI, then `make scenario-verify`.

Use `make scenario-hint` if stuck — hints escalate; the guide does not repeat every hint.

---

### Scenario 1 — `agent-down`

**Ticket:** App server `test-host-01` — no agent metrics; VM is up.

**You learn:** Agent interface DNS; `nodata()` triggers; difference between “host up” and “monitoring up”.

**Investigation checklist**

- Problems: trigger `test-host-01: agent is not responding`?
- Latest data: `agent.ping` = nodata?
- Host → Interfaces → Agent: what DNS/IP? (lab expects DNS `zabbix-agent`)
- From server: `zabbix_get -s <that-dns> -k agent.ping` — fails?

**What good looks like after fix**

- Interface DNS = `zabbix-agent`, port `10050`
- `agent.ping` last value = `1`

**Real world:** Wrong DNS after clone, typo in automation, firewall allows IP but hostname doesn’t resolve from server.

---

### Scenario 2 — `snmp-community`

**Ticket:** `snmp-device-01` — SNMP died after “community rotation”.

**You learn:** SNMP credentials via host macros; interface `{$SNMP_COMMUNITY}`.

**Investigation checklist**

- Latest data: `snmp.sysuptime` / `snmp.sysname` nodata?
- Host → Macros: value of `{$SNMP_COMMUNITY}` (lab device uses `public`)
- Host → Interfaces → SNMP: community field references macro?
- Server log: authentication errors to `snmpsim`?

**What good looks like after fix**

- Macro = `public`
- SNMP items return sysName / sysUpTime

**Real world:** NetOps changes community on devices but not in Zabbix; macro per site is best practice.

---

### Scenario 3 — `icmp-unreachable`

**Ticket:** WAN probe `router-icmp-01` down; map link may be red.

**You learn:** Simple checks use **host interface address** as ping target.

**Investigation checklist**

- Problems: `host unreachable (ICMP)`?
- Latest data: `icmpping` = `0`?
- Host → Interfaces: which IP/DNS? (lab: DNS `postgres`, use DNS not IP)
- `docker compose exec zabbix-server ping -c1 postgres` works?

**What good looks like after fix**

- Interface: Connect via DNS `postgres`
- `icmpping` = `1`

**Real world:** Wrong gateway IP on interface; monitoring VPN vs production routing.

---

### Scenario 4 — `http-broken`

**Ticket:** `frontend-http-01` — portal health check failing.

**You learn:** HTTP agent items store full URL on the item; status code matching.

**Investigation checklist**

- Latest data: `frontend.http.get` nodata or error?
- Item → URL field — still `http://zabbix-web:8080/`?
- Item → Required status codes include `200` (and `302` if redirected)?
- curl the URL from a container on the compose network

**What good looks like after fix**

- URL exactly `http://zabbix-web:8080/`
- Item returns response body / success

**Real world:** Typo in path after deploy; TLS cert change; load balancer returns 503.

---

### Scenario 5 — `server-agent-loopback`

**Ticket:** `Zabbix server` host — Linux by Zabbix agent template items failing.

**You learn:** Docker pitfall — `127.0.0.1` is the server container, not the agent container.

**Investigation checklist**

- Problems on **Zabbix server** host (not only test-host-01)
- Interfaces → Agent: IP `127.0.0.1`? (broken in compose split layout)
- Compare with `bootstrap.py` / `make bootstrap` intent

**What good looks like after fix**

- Agent interface DNS = `zabbix-agent` (use DNS)

**Real world:** Same mistake on any multi-container or Kubernetes deployment.

---

### Scenario 6 — `item-disabled`

**Ticket:** Ping alert on `test-host-01` but “server is clearly up”.

**You learn:** Disabled **item** vs disabled **host**; nodata from disabled item.

**Investigation checklist**

- Host status = Enabled?
- Items list: `agent.ping` status **Disabled**?
- Re-enable item; Execute now

**What good looks like after fix**

- Item enabled; `agent.ping` = `1`

**Real world:** Someone disabled one noisy item during incident and forgot to re-enable.

---

### Scenario 7 — `host-disabled`

**Ticket:** `snmp-device-01` vanished from monitoring; device still on network.

**You learn:** Disabled host stops **all** collection.

**Investigation checklist**

- Host list: snmp-device-01 grey/disabled?
- All SNMP items stale/nodata
- Enable host; wait for poll

**What good looks like after fix**

- Host enabled; SNMP data flowing

**Real world:** Decommission ticket closed wrong host; import template on disabled host.

---

### Scenario 8 — `cpu-noise`

**Prerequisite:** `make bootstrap` (creates CPU trigger).

**Ticket:** CPU alert storm on `test-host-01`; load is normal.

**You learn:** Trigger expression thresholds; alert fatigue.

**Investigation checklist**

- Problems: `CPU load is high` constantly?
- Latest data: actual `system.cpu.load[all,avg1]` value?
- Host → Triggers → expression — threshold absurdly low?

**What good looks like after fix**

- Expression uses realistic threshold (e.g. `>2` for 5m average)

**Real world:** Copied template without tuning; wrong units (percent vs load average).

---

### Scenario 9 — `maintenance-blind`

**Ticket:** WAN down but no Problem; ops “we knew”.

**You learn:** Maintenance suppresses problems (not the same as “fixed”).

**Investigation checklist**

- Problems empty for `router-icmp-01`?
- Host icon: maintenance wrench?
- **Data collection → Maintenance** — active window “Lab scenario…”?
- Delete or stop maintenance

**What good looks like after fix**

- Maintenance window removed (`make scenario-verify` checks this)

**Real world:** Forgotten maintenance after change window; wrong host group in maintenance.

---

### Scenario 10 — `snmp-delay`

**Ticket:** SLA breach — SNMP data only every 30 minutes.

**You learn:** Item **Update interval** (`delay`) drives freshness, not just trigger.

**Investigation checklist**

- Latest data: last check ~30m ago?
- Item `snmp.sysuptime` → Update interval = `30m`?
- Change to `1m`; wait or Execute now

**What good looks like after fix**

- Delay = `1m`

**Real world:** Copied discovery rule with long interval; performance tuning gone wrong.

---

## 7. Learning path & progress tracker

Recommended order (easiest → harder):

```text
agent-down → item-disabled → host-disabled → server-agent-loopback
    → snmp-community → snmp-delay → icmp-unreachable → http-broken
    → maintenance-blind → cpu-noise
```

Print or copy this tracker:


| #   | Scenario              | Started | Fixed (verify ✓) | Notes |
| --- | --------------------- | ------- | ---------------- | ----- |
| 1   | agent-down            | ☐       | ☐                |       |
| 2   | item-disabled         | ☐       | ☐                |       |
| 3   | host-disabled         | ☐       | ☐                |       |
| 4   | server-agent-loopback | ☐       | ☐                |       |
| 5   | snmp-community        | ☐       | ☐                |       |
| 6   | snmp-delay            | ☐       | ☐                |       |
| 7   | icmp-unreachable      | ☐       | ☐                |       |
| 8   | http-broken           | ☐       | ☐                |       |
| 9   | maintenance-blind     | ☐       | ☐                |       |
| 10  | cpu-noise             | ☐       | ☐                |       |


**Target time:** 15–25 minutes per scenario first time; under 10 minutes on retry.

---

## 8. Working with an AI coach

Paste this template (fill in blanks) when you want help **without** full spoilers:

```text
Zabbix lab — scenario: <id>
Ticket: <one line>

Problems tab:
- <trigger names / none>

Latest data:
- <item key>: <value or nodata>

I checked:
- <interfaces / macros / items / maintenance>

I think the cause is:
- <your hypothesis>

Please give ONE next step only (no full answer).
```

After `make scenario-verify` passes:

```text
Scenario <id> solved. Give a 3-bullet retrospective: signal, fix, prevention.
```

---

## 9. Answer key

Only read after you tried, or use `make scenario-reveal`.


| Scenario                | Root cause injected               | Fix                                    |
| ----------------------- | --------------------------------- | -------------------------------------- |
| `agent-down`            | Agent DNS → `zabbix-agent-broken` | DNS → `zabbix-agent`                   |
| `snmp-community`        | Macro → `wrong-community`         | Macro → `public`                       |
| `icmp-unreachable`      | Interface IP → `192.0.2.1`        | DNS `postgres`, use DNS                |
| `http-broken`           | URL path typo                     | `http://zabbix-web:8080/`              |
| `server-agent-loopback` | Agent IP `127.0.0.1`              | DNS `zabbix-agent` or `make bootstrap` |
| `item-disabled`         | `agent.ping` disabled             | Enable item                            |
| `host-disabled`         | Host disabled                     | Enable host                            |
| `cpu-noise`             | Threshold `>0.0001`               | Restore `>2` (5m avg)                  |
| `maintenance-blind`     | Active maintenance window         | Delete maintenance                     |
| `snmp-delay`            | Item delay `30m`                  | Set delay `1m`                         |


Automated undo: `make scenario-reset` then `make add-hosts` / `make bootstrap` if needed.

---

## 10. When things go wrong


| Problem                        | Fix                                                                      |
| ------------------------------ | ------------------------------------------------------------------------ |
| `unknown scenario`             | `make scenario-list`                                                     |
| `still active` scenario        | `make scenario-reset`                                                    |
| verify passes before you fixed | Wait for stale cache; check you changed the right field                  |
| verify never passes            | `make scenario-hint`; compare to [Answer key](#9-answer-key)             |
| Whole lab broken               | `make scenario-reset && make add-hosts && make bootstrap`                |
| Nuclear reset                  | `make reset && make up && make bootstrap && make add-hosts && make maps` |
| API auth errors                | Check `.env` — `ZABBIX_TOKEN` or `Admin`/`zabbix`                        |


Official reference: [Zabbix 7.0 documentation](https://www.zabbix.com/documentation/7.0/en/manual).

---

*Next step:* run `make scenario SCENARIO=agent-down` and work through [Scenario 1](#scenario-1--agent-down) without peeking at the answer key.