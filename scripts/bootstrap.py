#!/usr/bin/env python3
"""Configure a sample host through the API — fully idempotent.

Creates (or reuses) a host group, a host that points at the agent2 container,
a couple of agent items, and a trigger. Run it as many times as you like:

    python scripts/bootstrap.py

After it runs, open http://localhost:8080 -> Monitoring -> Latest data to watch
the items populate, and Monitoring -> Problems if you stop the agent.
"""

from zbx_client import (
    connect,
    ensure_agent_interface,
    ensure_host,
    ensure_host_group,
    ensure_item,
    ensure_trigger,
)

# Default host created by the Zabbix image; Linux template fires if agent is down.
DEFAULT_HOST = "Zabbix server"

GROUP = "Learning/Lab"
HOST = "test-host-01"
# The agent2 service in docker-compose.yml — resolvable by name on the network.
AGENT_DNS = "zabbix-agent"


def main() -> None:
    api = connect()
    try:
        print(f"Connected to Zabbix API {api.api_version()}")

        if ensure_agent_interface(api, DEFAULT_HOST, agent_dns=AGENT_DNS):
            print(f"  '{DEFAULT_HOST}' agent interface -> DNS {AGENT_DNS}")
        else:
            print(f"  '{DEFAULT_HOST}' agent interface already OK")

        groupid = ensure_host_group(api, GROUP)
        print(f"  host group '{GROUP}' -> {groupid}")

        hostid = ensure_host(api, HOST, groupid, AGENT_DNS, visible_name="Test Host 01")
        print(f"  host '{HOST}' -> {hostid}")

        # agent.ping returns 1 when the agent answers; nothing (nodata) when it doesn't.
        ensure_item(api, hostid, "Agent ping", "agent.ping", value_type=3, delay="30s")
        # system.cpu.load is a float -> value_type 0.
        ensure_item(
            api, hostid, "CPU load (1m avg)", "system.cpu.load[all,avg1]",
            value_type=0, delay="1m",
        )
        print("  items ensured: agent.ping, system.cpu.load[all,avg1]")

        ensure_trigger(
            api,
            description=f"{HOST}: agent is not responding",
            expression=f"nodata(/{HOST}/agent.ping,5m)=1",
            priority=4,  # high
        )
        ensure_trigger(
            api,
            description=f"{HOST}: CPU load is high",
            expression=f"avg(/{HOST}/system.cpu.load[all,avg1],5m)>2",
            priority=2,  # warning
        )
        print("  triggers ensured: agent down, high CPU load")

        print("\nDone. Watch it in the UI: Monitoring -> Latest data.")
    finally:
        api.logout()


if __name__ == "__main__":
    main()
