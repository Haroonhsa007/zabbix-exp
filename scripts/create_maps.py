#!/usr/bin/env python3
"""Build a corporate topology network map and a geomap dashboard for the lab hosts.

    python scripts/create_maps.py

Creates / ensures:
  - "Lab corporate topology" (Monitoring -> Maps): five cooperating corporate
    networks, shared internal segments, edge clusters (homes / shops / SOHO),
    and the four lab hosts wired into the layout with live status.
  - the global geomap tile provider (OpenStreetMap) — required or geomaps error.
  - "Lab geomap" dashboard (Dashboards): a geomap widget + the network-map widget.

Run scripts/add_hosts.py first so the hosts and their locations exist.
"""

from zbx_client import (
    connect,
    ensure_geomap_dashboard,
    ensure_geomap_provider,
    ensure_host_group,
    ensure_topology_map,
)

GROUP = "Learning/Lab"
MAP_NAME = "Lab corporate topology"

# Host technical names used on the topology map (must exist after add_hosts.py).
LAB_HOSTS = (
    "Zabbix server",
    "test-host-01",
    "snmp-device-01",
    "router-icmp-01",
    "frontend-http-01",
)

# Triggers that color links when problems fire.
LINK_TRIGGERS = (
    "router-icmp-01: host unreachable (ICMP)",
    "snmp-device-01: SNMP not responding",
    "frontend-http-01: no data from frontend",
)


def main() -> None:
    api = connect()
    try:
        print(f"Connected to Zabbix API {api.api_version()}")
        groupid = ensure_host_group(api, GROUP)

        hosts = api.host.get(
            groupids=groupid,
            filter={"host": list(LAB_HOSTS[1:])},
            output=["hostid", "host"],
        )
        srv = api.host.get(filter={"host": "Zabbix server"}, output=["hostid", "host"])
        if not srv:
            raise SystemExit("'Zabbix server' host not found — is the stack up?")
        if len(hosts) < 4:
            raise SystemExit(
                "missing lab hosts — run scripts/add_hosts.py first "
                f"(found {len(hosts)}/4)"
            )

        hostids = {h["host"]: h["hostid"] for h in hosts}
        hostids["Zabbix server"] = srv[0]["hostid"]

        triggers = api.trigger.get(
            filter={"description": list(LINK_TRIGGERS)},
            output=["triggerid", "description"],
        )
        triggerids = {t["description"]: t["triggerid"] for t in triggers}

        sysmapid = ensure_topology_map(
            api, MAP_NAME, hostids, triggerids=triggerids
        )
        print(
            f"  network map '{MAP_NAME}' -> {sysmapid} "
            "(5 corps + internal + edge + 4 lab hosts)"
        )

        ensure_geomap_provider(api)
        print("  geomap tile provider set (OpenStreetMap)")

        dashid = ensure_geomap_dashboard(api, "Lab geomap", groupid, sysmapid=sysmapid)
        print(f"  dashboard 'Lab geomap' -> {dashid}")

        print("\nDone. View them in the UI:")
        print(f"  Monitoring -> Maps -> {MAP_NAME}")
        print("  Dashboards -> Lab geomap")
    finally:
        api.logout()


if __name__ == "__main__":
    main()
