#!/usr/bin/env python3
"""Troubleshooting lab — inject realistic faults, verify fixes, guided hints.

    .venv/bin/python scripts/scenario_lab.py list
    .venv/bin/python scripts/scenario_lab.py start agent-down
    .venv/bin/python scripts/scenario_lab.py hint
    .venv/bin/python scripts/scenario_lab.py verify
    .venv/bin/python scripts/scenario_lab.py reveal
    .venv/bin/python scripts/scenario_lab.py reset

See scenarios/GUIDE.md for the full learner's guide.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from zbx_client import connect

STATE_PATH = Path(__file__).resolve().parent.parent / ".scenario-lab.json"

# --- API helpers -------------------------------------------------------------


def _host(api, name: str) -> dict:
    rows = api.host.get(
        filter={"host": name},
        output=["hostid", "host", "status"],
        selectInterfaces=["interfaceid", "type", "main", "ip", "dns", "port", "useip"],
        selectMacros=["macro", "value"],
    )
    if not rows:
        raise SystemExit(f"host {name!r} not found — run make add-hosts")
    return rows[0]


def _item(api, host: str, key: str) -> dict:
    h = _host(api, host)
    rows = api.item.get(
        hostids=h["hostid"],
        filter={"key_": key},
        output=["itemid", "key_", "status", "delay", "url", "state"],
    )
    if not rows:
        raise SystemExit(f"item {host}/{key!r} not found")
    return rows[0]


def _trigger(api, description: str) -> dict:
    rows = api.trigger.get(
        filter={"description": description},
        output=["triggerid", "description", "expression", "value", "status"],
    )
    if not rows:
        raise SystemExit(f"trigger {description!r} not found")
    return rows[0]


def _agent_iface(host_row: dict) -> dict:
    for i in host_row.get("interfaces") or []:
        if str(i["type"]) == "1" and str(i.get("main")) == "1":
            return i
    raise SystemExit(f"no agent interface on {host_row['host']!r}")


def _save_state(data: dict) -> None:
    STATE_PATH.write_text(json.dumps(data, indent=2) + "\n")


def _load_state() -> dict | None:
    if not STATE_PATH.exists():
        return None
    return json.loads(STATE_PATH.read_text())


def _require_active() -> dict:
    state = _load_state()
    if not state or not state.get("active"):
        raise SystemExit("no active scenario — run: scenario_lab.py start <id>")
    return state


# --- Scenario definitions ----------------------------------------------------


@dataclass
class Scenario:
    id: str
    title: str
    ticket: str
    hints: list[str]
    reveal: str
    inject: Callable[..., None]
    verify: Callable[..., bool]
    reset: Callable[..., None] = field(default=lambda api, s: None)


def _inject_agent_down(api: Any, state: dict) -> None:
    host = "test-host-01"
    h = _host(api, host)
    iface = _agent_iface(h)
    state["backups"].append(
        {
            "kind": "agent_interface",
            "host": host,
            "interfaceid": iface["interfaceid"],
            "dns": iface.get("dns"),
            "ip": iface.get("ip"),
            "useip": iface.get("useip"),
            "port": iface.get("port"),
        }
    )
    api.host.update(
        hostid=h["hostid"],
        interfaces=[
            {
                "interfaceid": iface["interfaceid"],
                "type": 1,
                "main": 1,
                "useip": 0,
                "dns": "zabbix-agent-broken",
                "ip": "",
                "port": "10050",
            }
        ],
    )


def _verify_agent_down(api: Any) -> bool:
    h = _host(api, "test-host-01")
    iface = _agent_iface(h)
    if str(iface.get("useip")) != "0" or iface.get("dns") != "zabbix-agent":
        return False
    item = _item(api, "test-host-01", "agent.ping")
    if str(item.get("status")) != "0":
        return False
    last = api.item.get(itemids=item["itemid"], output=["lastvalue"])
    return bool(last and last[0].get("lastvalue") == "1")


def _reset_agent_interface(api: Any, backup: dict) -> None:
    h = _host(api, backup["host"])
    api.host.update(
        hostid=h["hostid"],
        interfaces=[
            {
                "interfaceid": backup["interfaceid"],
                "type": 1,
                "main": 1,
                "useip": int(backup["useip"]),
                "dns": backup["dns"] or "",
                "ip": backup["ip"] or "",
                "port": backup["port"],
            }
        ],
    )


def _inject_snmp_community(api: Any, state: dict) -> None:
    host = "snmp-device-01"
    h = _host(api, host)
    macros = h.get("macros") or []
    for m in macros:
        if m["macro"] == "{$SNMP_COMMUNITY}":
            state["backups"].append(
                {"kind": "macro", "hostid": h["hostid"], "macro": m["macro"], "value": m["value"]}
            )
            api.host.update(
                hostid=h["hostid"],
                macros=[{"macro": "{$SNMP_COMMUNITY}", "value": "wrong-community"}],
            )
            return
    raise SystemExit(f"{{$SNMP_COMMUNITY}} macro missing on {host}")


def _verify_snmp_community(api: Any) -> bool:
    h = _host(api, "snmp-device-01")
    macro = next(
        (m for m in (h.get("macros") or []) if m["macro"] == "{$SNMP_COMMUNITY}"),
        None,
    )
    if not macro or macro["value"] != "public":
        return False
    item = _item(api, "snmp-device-01", "snmp.sysuptime")
    last = api.item.get(itemids=item["itemid"], output=["lastvalue", "state"])
    return bool(last and last[0].get("lastvalue"))


def _reset_macro(api: Any, backup: dict) -> None:
    api.host.update(
        hostid=backup["hostid"],
        macros=[{"macro": backup["macro"], "value": backup["value"]}],
    )


def _inject_icmp_unreachable(api: Any, state: dict) -> None:
    host = "router-icmp-01"
    h = _host(api, host)
    iface = _agent_iface(h)
    state["backups"].append(
        {
            "kind": "agent_interface",
            "host": host,
            "interfaceid": iface["interfaceid"],
            "dns": iface.get("dns"),
            "ip": iface.get("ip"),
            "useip": iface.get("useip"),
            "port": iface.get("port"),
        }
    )
    api.host.update(
        hostid=h["hostid"],
        interfaces=[
            {
                "interfaceid": iface["interfaceid"],
                "type": 1,
                "main": 1,
                "useip": 1,
                "ip": "192.0.2.1",
                "dns": "",
                "port": "10050",
            }
        ],
    )


def _verify_icmp_unreachable(api: Any) -> bool:
    h = _host(api, "router-icmp-01")
    iface = _agent_iface(h)
    if str(iface.get("useip")) != "0" or iface.get("dns") != "postgres":
        return False
    item = _item(api, "router-icmp-01", "icmpping")
    last = api.item.get(itemids=item["itemid"], output=["lastvalue"])
    return bool(last and last[0].get("lastvalue") == "1")


def _inject_http_broken(api: Any, state: dict) -> None:
    host = "frontend-http-01"
    item = _item(api, host, "frontend.http.get")
    full = api.item.get(itemids=item["itemid"], output=["url"])
    url = full[0]["url"] if full else "http://zabbix-web:8080/"
    state["backups"].append({"kind": "item_url", "itemid": item["itemid"], "url": url})
    api.item.update(
        itemid=item["itemid"],
        url="http://zabbix-web:8080/this-path-does-not-exist",
    )


def _verify_http_broken(api: Any) -> bool:
    item = _item(api, "frontend-http-01", "frontend.http.get")
    full = api.item.get(itemids=item["itemid"], output=["url", "lastvalue"])
    if not full:
        return False
    return (
        full[0]["url"] == "http://zabbix-web:8080/"
        and bool(full[0].get("lastvalue"))
    )


def _reset_item_url(api: Any, backup: dict) -> None:
    api.item.update(itemid=backup["itemid"], url=backup["url"])


def _inject_server_loopback(api: Any, state: dict) -> None:
    host = "Zabbix server"
    h = _host(api, host)
    iface = _agent_iface(h)
    state["backups"].append(
        {
            "kind": "agent_interface",
            "host": host,
            "interfaceid": iface["interfaceid"],
            "dns": iface.get("dns"),
            "ip": iface.get("ip"),
            "useip": iface.get("useip"),
            "port": iface.get("port"),
        }
    )
    api.host.update(
        hostid=h["hostid"],
        interfaces=[
            {
                "interfaceid": iface["interfaceid"],
                "type": 1,
                "main": 1,
                "useip": 1,
                "ip": "127.0.0.1",
                "dns": "",
                "port": "10050",
            }
        ],
    )


def _verify_server_loopback(api: Any) -> bool:
    h = _host(api, "Zabbix server")
    iface = _agent_iface(h)
    return str(iface.get("useip")) == "0" and iface.get("dns") == "zabbix-agent"


def _inject_item_disabled(api: Any, state: dict) -> None:
    item = _item(api, "test-host-01", "agent.ping")
    state["backups"].append({"kind": "item_status", "itemid": item["itemid"], "status": item["status"]})
    api.item.update(itemid=item["itemid"], status=1)


def _verify_item_enabled(api: Any) -> bool:
    item = _item(api, "test-host-01", "agent.ping")
    if str(item.get("status")) != "0":
        return False
    last = api.item.get(itemids=item["itemid"], output=["lastvalue", "state"])
    return bool(last and last[0].get("lastvalue") == "1" and str(last[0].get("state")) == "0")


def _reset_item_status(api: Any, backup: dict) -> None:
    api.item.update(itemid=backup["itemid"], status=int(backup["status"]))


def _inject_host_disabled(api: Any, state: dict) -> None:
    h = _host(api, "snmp-device-01")
    state["backups"].append({"kind": "host_status", "hostid": h["hostid"], "status": h["status"]})
    api.host.update(hostid=h["hostid"], status=1)


def _verify_host_enabled(api: Any) -> bool:
    h = _host(api, "snmp-device-01")
    if str(h.get("status")) != "0":
        return False
    item = _item(api, "snmp-device-01", "snmp.sysuptime")
    last = api.item.get(itemids=item["itemid"], output=["lastvalue"])
    return bool(last and last[0].get("lastvalue"))


def _reset_host_status(api: Any, backup: dict) -> None:
    api.host.update(hostid=backup["hostid"], status=int(backup["status"]))


def _inject_cpu_noise(api: Any, state: dict) -> None:
    desc = "test-host-01: CPU load is high"
    trig = _trigger(api, desc)
    state["backups"].append(
        {
            "kind": "trigger_expression",
            "triggerid": trig["triggerid"],
            "expression": trig["expression"],
        }
    )
    api.trigger.update(
        triggerid=trig["triggerid"],
        expression="avg(/test-host-01/system.cpu.load[all,avg1],5m)>0.0001",
    )


def _verify_cpu_noise(api: Any) -> bool:
    trig = _trigger(api, "test-host-01: CPU load is high")
    expr = trig["expression"]
    return ">2" in expr or ">=2" in expr


def _reset_trigger_expression(api: Any, backup: dict) -> None:
    api.trigger.update(
        triggerid=backup["triggerid"],
        expression=backup["expression"],
    )


def _inject_maintenance(api: Any, state: dict) -> None:
    h = _host(api, "router-icmp-01")
    now = int(time.time())
    result = api.maintenance.create(
        name="Lab scenario — planned WAN work",
        active_since=now - 300,
        active_till=now + 7200,
        hostids=[h["hostid"]],
        timeperiods=[{"timeperiod_type": 0, "start_date": now - 300, "period": 7200}],
    )
    state["backups"].append(
        {"kind": "maintenance", "maintenanceids": result["maintenanceids"]}
    )
    api.host.update(hostid=h["hostid"], status=0)


def _verify_maintenance_cleared(api: Any) -> bool:
    state = _load_state() or {}
    for b in state.get("backups", []):
        if b.get("kind") != "maintenance":
            continue
        mids = b.get("maintenanceids") or []
        if mids:
            existing = api.maintenance.get(maintenanceids=mids, output=["maintenanceid"])
            if existing:
                return False
    return True


def _reset_maintenance(api: Any, backup: dict) -> None:
    mids = backup.get("maintenanceids") or []
    if mids:
        api.maintenance.delete(mids)


def _inject_snmp_delay(api: Any, state: dict) -> None:
    item = _item(api, "snmp-device-01", "snmp.sysuptime")
    state["backups"].append({"kind": "item_delay", "itemid": item["itemid"], "delay": item.get("delay", "1m")})
    api.item.update(itemid=item["itemid"], delay="30m")


def _verify_snmp_delay(api: Any) -> bool:
    item = _item(api, "snmp-device-01", "snmp.sysuptime")
    delay = (item.get("delay") or "").strip().lower()
    return delay in ("1m", "60s")


def _reset_item_delay(api: Any, backup: dict) -> None:
    api.item.update(itemid=backup["itemid"], delay=backup["delay"])


SCENARIOS: dict[str, Scenario] = {
    "agent-down": Scenario(
        id="agent-down",
        title="Agent not responding (wrong DNS)",
        ticket=(
            "TICKET #LAB-101 — Monitoring\n"
            "Host: test-host-01 (Corp Alpha app server)\n"
            "Alert: No agent data for 5+ minutes. App team says the VM is up.\n"
            "Your task: Find why Zabbix cannot reach the agent and restore metrics."
        ),
        hints=[
            "Open Monitoring → Problems. Which host and trigger fired?",
            "Check Data collection → Hosts → test-host-01 → Interfaces. "
            "Is the agent address reachable from the server container?",
            "From the server container, `zabbix_get -s <dns> -k agent.ping` is the same test the poller runs.",
            "Fix the agent interface DNS (or IP) so it points at the real agent service on the compose network.",
        ],
        reveal=(
            "The agent interface DNS was set to a bogus name. "
            "Set DNS back to `zabbix-agent` (or run `make bootstrap` / `make add-hosts`)."
        ),
        inject=_inject_agent_down,
        verify=_verify_agent_down,
    ),
    "snmp-community": Scenario(
        id="snmp-community",
        title="SNMP stopped after credential change",
        ticket=(
            "TICKET #LAB-102 — Network ops\n"
            "Host: snmp-device-01 (Corp Beta edge router)\n"
            "Change record: 'SNMPv2c community rotated' — since then, no SNMP metrics.\n"
            "snmpsim in the lab still uses community `public`."
        ),
        hints=[
            "Latest data: do SNMP items show 'nodata' or errors?",
            "On the host, check Macros — SNMP interfaces often reference {$SNMP_COMMUNITY}.",
            "Compare macro value to what the device actually accepts (lab: `public`).",
            "After fixing the macro, wait one poll cycle or use Update now on the item.",
        ],
        reveal="Set host macro {$SNMP_COMMUNITY} back to `public`.",
        inject=_inject_snmp_community,
        verify=_verify_snmp_community,
    ),
    "icmp-unreachable": Scenario(
        id="icmp-unreachable",
        title="WAN ICMP probe failing",
        ticket=(
            "TICKET #LAB-103 — NOC\n"
            "Host: router-icmp-01 — WAN reachability probe to internal gateway.\n"
            "Map link 'WAN ICMP' may be red. Branch claims their router is fine."
        ),
        hints=[
            "Simple checks (icmpping) use the host interface IP/DNS as the ping target — not the item key alone.",
            "Inspect router-icmp-01 → Interfaces → agent tab (used as address for ICMP).",
            "In compose, postgres is the intended target hostname.",
            "Test from server: `docker compose exec zabbix-server ping -c1 postgres`.",
        ],
        reveal=(
            "Interface was pointed at RFC5737 TEST-NET IP 192.0.2.1. "
            "Restore useip=0 and DNS `postgres`."
        ),
        inject=_inject_icmp_unreachable,
        verify=_verify_icmp_unreachable,
    ),
    "http-broken": Scenario(
        id="http-broken",
        title="Frontend HTTP health check failing",
        ticket=(
            "TICKET #LAB-104 — Platform\n"
            "Host: frontend-http-01 — synthetic GET of the Zabbix UI.\n"
            "Status: nodata / not 200. Release was 'no URL changes'."
        ),
        hints=[
            "Item type is HTTP agent — URL and expected status codes live on the item.",
            "Try the URL from inside the web container network: curl the zabbix-web service.",
            "A trailing path typo still returns HTTP 404 — Zabbix records that as failure.",
        ],
        reveal="Set item URL back to `http://zabbix-web:8080/`.",
        inject=_inject_http_broken,
        verify=_verify_http_broken,
    ),
    "server-agent-loopback": Scenario(
        id="server-agent-loopback",
        title="Zabbix server agent on 127.0.0.1 (Docker pitfall)",
        ticket=(
            "TICKET #LAB-105 — Monitoring team\n"
            "Host: Zabbix server — Linux template items show agent unreachable.\n"
            "Architecture: agent2 runs in a separate container, not on localhost."
        ),
        hints=[
            "This is a classic Docker Compose mistake: 127.0.0.1 inside the server container is not the agent container.",
            "Check the Zabbix server host agent interface IP/DNS.",
            "bootstrap.py exists in this repo specifically to point the interface at `zabbix-agent`.",
        ],
        reveal=(
            "Set agent interface to DNS `zabbix-agent` (useip=0) or run `make bootstrap`."
        ),
        inject=_inject_server_loopback,
        verify=_verify_server_loopback,
    ),
    "item-disabled": Scenario(
        id="item-disabled",
        title="Item disabled — host looks fine",
        ticket=(
            "TICKET #LAB-106 — False alarm investigation\n"
            "Host: test-host-01 — ping trigger fired but 'the server is clearly up'.\n"
            "Hint from senior: always check item Status, not only the host."
        ),
        hints=[
            "If the host is enabled but an item is disabled, you still get nodata().",
            "Data collection → Hosts → Items — look for Disabled in the Status column.",
            "Re-enable the item; confirm Latest data shows agent.ping = 1.",
        ],
        reveal="Re-enable item agent.ping on test-host-01.",
        inject=_inject_item_disabled,
        verify=_verify_item_enabled,
    ),
    "host-disabled": Scenario(
        id="host-disabled",
        title="Entire host disabled",
        ticket=(
            "TICKET #LAB-107 — Inventory\n"
            "Device snmp-device-01 removed from dashboards after 'decommission' ticket — "
            "but hardware is still on the network."
        ),
        hints=[
            "Disabled hosts stop all data collection — different from maintenance.",
            "Check host Status on Data collection → Hosts.",
            "Re-enable the host; confirm SNMP items populate.",
        ],
        reveal="Set host snmp-device-01 status to Enabled.",
        inject=_inject_host_disabled,
        verify=_verify_host_enabled,
    ),
    "cpu-noise": Scenario(
        id="cpu-noise",
        title="CPU alert storm (bad threshold)",
        ticket=(
            "TICKET #LAB-108 — Alert fatigue\n"
            "Host: test-host-01 — 'CPU load is high' fires continuously while load is normal.\n"
            "Change request: tune monitoring, not reboot the server."
        ),
        hints=[
            "Read the trigger expression — what function and threshold are used?",
            "Compare Latest data for system.cpu.load[all,avg1] to the threshold in the trigger.",
            "A threshold of 0.0001 on Linux load will always fire.",
        ],
        reveal=(
            "Restore expression to avg(/test-host-01/system.cpu.load[all,avg1],5m)>2 "
            "(or run make bootstrap)."
        ),
        inject=_inject_cpu_noise,
        verify=_verify_cpu_noise,
    ),
    "maintenance-blind": Scenario(
        id="maintenance-blind",
        title="Maintenance suppressing WAN alert",
        ticket=(
            "TICKET #LAB-109 — Shift handover\n"
            "router-icmp-01 is down for real, but nothing in Problems. "
            "Ops says 'we put it in maintenance yesterday and forgot to close it'."
        ),
        hints=[
            "Check Data collection → Maintenance — active windows suppress problems.",
            "Also look at the host orange wrench icon in the host list.",
            "End or delete the maintenance; confirm ICMP problem appears if the target is still broken.",
            "For this scenario, after clearing maintenance the ICMP target is still correct — "
            "you may need to re-break icmp separately, or just clear maintenance to pass verify.",
        ],
        reveal=(
            "Delete the 'Lab scenario — planned WAN work' maintenance window. "
            "scenario reset also removes it."
        ),
        inject=_inject_maintenance,
        verify=_verify_maintenance_cleared,
    ),
    "snmp-delay": Scenario(
        id="snmp-delay",
        title="Stale data — update interval too long",
        ticket=(
            "TICKET #LAB-110 — SLA review\n"
            "snmp-device-01 must report every minute per contract; dashboards show 30m gaps."
        ),
        hints=[
            "Check item Update interval (delay) on SNMP items.",
            "SLA issues are often configuration, not device failure.",
            "Set snmp.sysuptime delay back to 1m.",
        ],
        reveal="Set snmp.sysuptime update interval to `1m`.",
        inject=_inject_snmp_delay,
        verify=_verify_snmp_delay,
    ),
}


# --- Reset dispatcher --------------------------------------------------------


def _reset_backup(api: Any, backup: dict) -> None:
    kind = backup.get("kind")
    if kind == "agent_interface":
        _reset_agent_interface(api, backup)
    elif kind == "macro":
        _reset_macro(api, backup)
    elif kind == "item_url":
        _reset_item_url(api, backup)
    elif kind == "item_status":
        _reset_item_status(api, backup)
    elif kind == "item_delay":
        _reset_item_delay(api, backup)
    elif kind == "host_status":
        _reset_host_status(api, backup)
    elif kind == "trigger_expression":
        _reset_trigger_expression(api, backup)
    elif kind == "maintenance":
        _reset_maintenance(api, backup)


def cmd_reset(api: Any, *, force: bool = False) -> None:
    state = _load_state()
    if not state:
        print("No scenario state file — nothing to reset.")
        return
    if state.get("active") and not force:
        print(f"Resetting scenario: {state['active']}")
    for backup in reversed(state.get("backups") or []):
        _reset_backup(api, backup)
    STATE_PATH.unlink(missing_ok=True)
    print("Scenario lab reset complete. Run `make add-hosts` if anything still looks wrong.")


def cmd_start(api: Any, scenario_id: str, *, force: bool = False) -> None:
    if scenario_id not in SCENARIOS:
        raise SystemExit(f"unknown scenario {scenario_id!r} — run: scenario_lab.py list")
    existing = _load_state()
    if existing and existing.get("active"):
        if not force:
            raise SystemExit(
                f"scenario {existing['active']!r} still active — "
                "run reset first or use --force"
            )
        cmd_reset(api, force=True)

    sc = SCENARIOS[scenario_id]
    state: dict[str, Any] = {"active": scenario_id, "hint_index": 0, "backups": []}
    sc.inject(api, state)
    _save_state(state)

    print("=" * 60)
    print(sc.title)
    print("=" * 60)
    print(sc.ticket)
    print("=" * 60)
    print(f"\nScenario '{scenario_id}' injected.")
    print("Wait ~1–2 poll cycles for Problems/Latest data to update.")
    print("Investigate in the UI, then:  scenario_lab.py verify")
    print("Stuck?                         scenario_lab.py hint")
    print("Give up on this round?         scenario_lab.py reveal")
    print("Clean up:                      scenario_lab.py reset\n")


def cmd_hint() -> None:
    state = _require_active()
    sc = SCENARIOS[state["active"]]
    idx = state.get("hint_index", 0)
    if idx >= len(sc.hints):
        print("No more hints — try verify or reveal.")
        return
    print(f"Hint {idx + 1}/{len(sc.hints)}:")
    print(sc.hints[idx])
    state["hint_index"] = idx + 1
    _save_state(state)


def cmd_verify(api: Any) -> None:
    state = _require_active()
    sc = SCENARIOS[state["active"]]
    print(f"Checking scenario: {sc.id} …")
    if sc.verify(api):
        print("\n✓ Looks fixed! Nice work.")
        print("Run `scenario_lab.py reset` before starting the next scenario.")
    else:
        print("\n✗ Not fixed yet (or data has not refreshed).")
        print("Wait 30–60s after changes, reload Latest data, try again.")
        print("Next hint: scenario_lab.py hint")


def cmd_reveal() -> None:
    state = _require_active()
    sc = SCENARIOS[state["active"]]
    print(f"Scenario: {sc.title}\n")
    print(sc.reveal)


def cmd_status() -> None:
    state = _load_state()
    if not state or not state.get("active"):
        print("No active scenario.")
        return
    sc = SCENARIOS[state["active"]]
    print(f"Active: {sc.id} — {sc.title}")
    print(f"Hints used: {state.get('hint_index', 0)}/{len(sc.hints)}")


def cmd_list() -> None:
    print("Troubleshooting scenarios:\n")
    for sc in SCENARIOS.values():
        print(f"  {sc.id:22} {sc.title}")
    print("\nStart:  scenario_lab.py start <id>")
    print("Guide:  scenarios/GUIDE.md")


def main() -> None:
    parser = argparse.ArgumentParser(description="Zabbix troubleshooting lab")
    parser.add_argument("--force", action="store_true", help="replace active scenario on start")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list scenarios")
    p_start = sub.add_parser("start", help="inject a scenario")
    p_start.add_argument("scenario_id", choices=sorted(SCENARIOS.keys()))

    sub.add_parser("status", help="show active scenario")
    sub.add_parser("hint", help="next hint")
    sub.add_parser("verify", help="check if fixed")
    sub.add_parser("reveal", help="show intended fix")
    sub.add_parser("reset", help="undo injection")

    args = parser.parse_args()
    if args.cmd == "list":
        cmd_list()
        return
    if args.cmd in ("hint", "reveal", "status"):
        {"hint": cmd_hint, "reveal": cmd_reveal, "status": cmd_status}[args.cmd]()
        return

    api = connect()
    try:
        if args.cmd == "start":
            cmd_start(api, args.scenario_id, force=args.force)
        elif args.cmd == "verify":
            cmd_verify(api)
        elif args.cmd == "reset":
            cmd_reset(api, force=True)
    finally:
        api.logout()


if __name__ == "__main__":
    main()
