#!/usr/bin/env python3
"""Add hosts of several monitoring types, each pinned to a Rawalpindi/Islamabad
location so they plot on the geomap. Fully idempotent — re-run any time.

    python scripts/add_hosts.py

Types created (all collect real data within the compose network):
  - Zabbix agent (passive)   test-host-01     -> zabbix-agent container
  - SNMPv2c                   snmp-device-01   -> snmpsim container
  - Simple check / ICMP       router-icmp-01   -> pings the postgres container
  - HTTP agent                frontend-http-01 -> GETs the Zabbix frontend

Run scripts/create_maps.py afterwards to build the network map + geomap.
"""

from zbx_client import (
    connect,
    ensure_host,
    ensure_host_group,
    ensure_http_item,
    ensure_interfaceless_host,
    ensure_item,
    ensure_simple_item,
    ensure_snmp_host,
    ensure_snmp_item,
    ensure_trigger,
    set_host_location,
)

GROUP = "Learning/Lab"

# Twin-cities coordinates (lat, lon, label) — Islamabad & Rawalpindi, Pakistan.
LOC_NOC = (33.6995, 73.0363, "Islamabad (NOC)")
LOC_F8 = (33.7080, 73.0290, "Islamabad F-8")
LOC_BLUE_AREA = (33.7156, 73.0717, "Islamabad Blue Area")
LOC_SADDAR = (33.5973, 73.0479, "Rawalpindi Saddar")
LOC_COMMITTEE = (33.6300, 73.0680, "Rawalpindi Committee Chowk")


def main() -> None:
    api = connect()
    try:
        print(f"Connected to Zabbix API {api.api_version()}")
        groupid = ensure_host_group(api, GROUP)
        print(f"  host group '{GROUP}' -> {groupid}")

        # Locate the built-in Zabbix server host at the NOC.
        srv = api.host.get(filter={"host": "Zabbix server"}, output=["hostid"])
        if srv:
            set_host_location(api, srv[0]["hostid"], *LOC_NOC)
            print(f"  'Zabbix server' located at {LOC_NOC[2]}")

        # 1. Zabbix agent (passive) ------------------------------------------
        h_agent = ensure_host(
            api, "test-host-01", groupid, "zabbix-agent",
            visible_name="Test Host 01 (agent)",
        )
        ensure_item(api, h_agent, "Agent ping", "agent.ping", value_type=3, delay="30s")
        ensure_item(
            api, h_agent, "CPU load (1m avg)", "system.cpu.load[all,avg1]",
            value_type=0, delay="1m",
        )
        set_host_location(api, h_agent, *LOC_F8)
        print(f"  agent host '{h_agent}' at {LOC_F8[2]}")

        # 2. SNMPv2c ----------------------------------------------------------
        h_snmp = ensure_snmp_host(
            api, "snmp-device-01", groupid, "snmpsim",
            community="public", version=2,
            visible_name="SNMP Device 01 (Rawalpindi)",
        )
        ensure_snmp_item(
            api, h_snmp, "SNMP sysName", "snmp.sysname",
            "1.3.6.1.2.1.1.5.0", value_type=1, delay="1m",
        )
        ensure_snmp_item(
            api, h_snmp, "SNMP sysUpTime", "snmp.sysuptime",
            "1.3.6.1.2.1.1.3.0", value_type=3, delay="1m",
        )
        set_host_location(api, h_snmp, *LOC_SADDAR)
        print(f"  SNMP host '{h_snmp}' at {LOC_SADDAR[2]}")

        # 3. Simple check / ICMP (agentless) ---------------------------------
        # Reuses an agent interface purely as the address; the simple check
        # itself runs from the server (fping). Points at the postgres container.
        h_icmp = ensure_host(
            api, "router-icmp-01", groupid, "postgres",
            visible_name="Router ICMP 01 (Rawalpindi)",
        )
        ensure_simple_item(api, h_icmp, "ICMP ping", "icmpping", value_type=3, delay="30s")
        ensure_simple_item(
            api, h_icmp, "ICMP response time", "icmppingsec", value_type=0, delay="30s"
        )
        set_host_location(api, h_icmp, *LOC_COMMITTEE)
        print(f"  ICMP host '{h_icmp}' at {LOC_COMMITTEE[2]}")

        # 4. HTTP agent -------------------------------------------------------
        h_http = ensure_interfaceless_host(
            api, "frontend-http-01", groupid,
            visible_name="Frontend HTTP 01 (Islamabad)",
        )
        ensure_http_item(
            api, h_http, "Frontend home page", "frontend.http.get",
            "http://zabbix-web:8080/", value_type=4, delay="1m", status_codes="200,302",
        )
        set_host_location(api, h_http, *LOC_BLUE_AREA)
        print(f"  HTTP host '{h_http}' at {LOC_BLUE_AREA[2]}")

        # Triggers across types ----------------------------------------------
        ensure_trigger(
            api, "snmp-device-01: SNMP not responding",
            "nodata(/snmp-device-01/snmp.sysuptime,5m)=1", priority=3,
        )
        ensure_trigger(
            api, "router-icmp-01: host unreachable (ICMP)",
            "max(/router-icmp-01/icmpping,#3)=0", priority=4,
        )
        ensure_trigger(
            api, "frontend-http-01: no data from frontend",
            "nodata(/frontend-http-01/frontend.http.get,5m)=1", priority=2,
        )
        print("  triggers ensured (SNMP down, ICMP unreachable, HTTP no-data)")

        print("\nDone. Next: python scripts/create_maps.py")
    finally:
        api.logout()


if __name__ == "__main__":
    main()
