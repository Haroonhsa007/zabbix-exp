#!/usr/bin/env python3
"""Read example: print the API version and every host with its interfaces.

    python scripts/list_hosts.py
"""

from zbx_client import connect


def main() -> None:
    api = connect()
    try:
        print(f"Connected to Zabbix API {api.api_version()}\n")
        hosts = api.host.get(
            output=["hostid", "host", "name", "status"],
            selectInterfaces=["ip", "dns", "port", "type"],
            sortfield="host",
        )
        if not hosts:
            print("No hosts found.")
            return
        for h in hosts:
            status = "enabled" if h["status"] == "0" else "DISABLED"
            print(f"[{h['hostid']:>4}] {h['host']}  ({h['name']}) — {status}")
            for iface in h.get("interfaces", []):
                target = iface["dns"] or iface["ip"]
                print(f"        iface type={iface['type']} {target}:{iface['port']}")
    finally:
        api.logout()


if __name__ == "__main__":
    main()
