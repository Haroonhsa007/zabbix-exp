"""Shared Zabbix API client + idempotent helpers for the learning stack.

Reads connection settings from the environment (and a local .env file):

    ZABBIX_URL        e.g. http://localhost:8080
    ZABBIX_TOKEN      preferred; an API token from Administration -> API tokens
    ZABBIX_USER       fallback login (default: Admin)
    ZABBIX_PASSWORD   fallback login (default: zabbix)

If ZABBIX_TOKEN is set it is used; otherwise we log in with user/password.
Import `connect()` and the get-or-create helpers from your scripts.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from dotenv import load_dotenv
from zabbix_utils import ZabbixAPI

# Load .env from the repo root regardless of where the script is run from.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def connect() -> ZabbixAPI:
    """Return a logged-in ZabbixAPI client. Prefer token, fall back to login."""
    url = os.environ.get("ZABBIX_URL", "http://localhost:8080")
    token = os.environ.get("ZABBIX_TOKEN") or ""
    api = ZabbixAPI(url=url)
    if token.strip():
        api.login(token=token.strip())
    else:
        api.login(
            user=os.environ.get("ZABBIX_USER", "Admin"),
            password=os.environ.get("ZABBIX_PASSWORD", "zabbix"),
        )
    return api


# --- Idempotent helpers ------------------------------------------------------
# Zabbix *.create is NOT idempotent (a second identical create errors), so each
# helper does get-then-create-or-return. Safe to run repeatedly.


def ensure_host_group(api: ZabbixAPI, name: str) -> str:
    """Return the groupid for a host group, creating it if absent."""
    existing = api.hostgroup.get(filter={"name": name}, output=["groupid"])
    if existing:
        return existing[0]["groupid"]
    return api.hostgroup.create(name=name)["groupids"][0]


def ensure_host(
    api: ZabbixAPI,
    host: str,
    groupid: str,
    agent_dns: str,
    *,
    visible_name: str | None = None,
) -> str:
    """Return the hostid for an agent-monitored host, creating it if absent.

    The agent interface uses DNS (useip=0) so the server resolves `agent_dns`
    over the compose network (e.g. the container name "zabbix-agent").
    """
    existing = api.host.get(filter={"host": host}, output=["hostid"])
    if existing:
        return existing[0]["hostid"]
    result = api.host.create(
        host=host,
        name=visible_name or host,
        groups=[{"groupid": groupid}],
        interfaces=[
            {
                "type": 1,        # 1 = agent
                "main": 1,
                "useip": 0,       # use DNS
                "ip": "",
                "dns": agent_dns,
                "port": "10050",
            }
        ],
    )
    return result["hostids"][0]


def ensure_agent_interface(
    api: ZabbixAPI,
    host: str,
    *,
    agent_dns: str | None = None,
    agent_ip: str | None = None,
    port: str = "10050",
) -> bool:
    """Point an existing host's main agent interface at the agent container.

    The default "Zabbix server" host ships with 127.0.0.1:10050, which does not
    work when agent2 runs in a separate compose service. Returns True if updated.
    """
    if not agent_dns and not agent_ip:
        raise ValueError("provide agent_dns or agent_ip")
    hosts = api.host.get(
        filter={"host": host},
        output=["hostid"],
        selectInterfaces=["interfaceid", "type", "main", "ip", "dns", "port"],
    )
    if not hosts:
        return False
    agent = [i for i in hosts[0].get("interfaces") or [] if str(i["type"]) == "1"]
    if not agent:
        return False
    iface = next((i for i in agent if str(i.get("main")) == "1"), agent[0])
    update: dict = {
        "interfaceid": iface["interfaceid"],
        "type": 1,
        "main": 1,
        "port": port,
    }
    if agent_dns:
        update["useip"] = 0
        update["dns"] = agent_dns
        update["ip"] = ""
        already_ok = iface.get("dns") == agent_dns and not iface.get("ip")
    else:
        update["useip"] = 1
        update["ip"] = agent_ip
        update["dns"] = ""
        already_ok = iface.get("ip") == agent_ip and not iface.get("dns")
    if already_ok and str(iface.get("port")) == port:
        return False
    api.host.update(hostid=hosts[0]["hostid"], interfaces=[update])
    return True


def _agent_interface_id(api: ZabbixAPI, hostid: str) -> str:
    """Return the main agent interfaceid for a host."""
    hosts = api.host.get(
        hostids=hostid,
        output=["hostid"],
        selectInterfaces=["interfaceid", "type", "main"],
    )
    if not hosts:
        raise ValueError(f"host {hostid!r} not found")
    agent = [i for i in hosts[0].get("interfaces") or [] if str(i["type"]) == "1"]
    if not agent:
        raise ValueError(f"host {hostid!r} has no agent interface")
    main = [i for i in agent if str(i.get("main")) == "1"]
    return (main or agent)[0]["interfaceid"]


def ensure_item(
    api: ZabbixAPI,
    hostid: str,
    name: str,
    key: str,
    *,
    value_type: int = 3,        # 3 = numeric unsigned
    delay: str = "30s",
    item_type: int = 0,         # 0 = Zabbix agent (passive)
) -> str:
    """Return the itemid for a host item, creating it if absent."""
    existing = api.item.get(
        hostids=hostid, filter={"key_": key}, output=["itemid"]
    )
    if existing:
        return existing[0]["itemid"]
    params: dict = {
        "hostid": hostid,
        "name": name,
        "key_": key,
        "type": item_type,
        "value_type": value_type,
        "delay": delay,
    }
    # Agent passive (0) and active (7) items require interfaceid on 7.0+.
    if item_type in (0, 7):
        params["interfaceid"] = _agent_interface_id(api, hostid)
    result = api.item.create(**params)
    return result["itemids"][0]


def ensure_trigger(
    api: ZabbixAPI,
    description: str,
    expression: str,
    *,
    priority: int = 3,          # 3 = average
) -> str:
    """Return the triggerid for a trigger, creating it if absent.

    `expression` uses 7.0 syntax, e.g.
        nodata(/test-host-01/agent.ping,5m)=1
    """
    existing = api.trigger.get(
        filter={"description": description}, output=["triggerid"]
    )
    if existing:
        return existing[0]["triggerid"]
    result = api.trigger.create(
        description=description, expression=expression, priority=priority
    )
    return result["triggerids"][0]


# --- Hosts of other monitoring types -----------------------------------------


def ensure_snmp_host(
    api: ZabbixAPI,
    host: str,
    groupid: str,
    snmp_dns: str,
    *,
    community: str = "public",
    version: int = 2,           # 2 = SNMPv2c
    port: str = "161",
    visible_name: str | None = None,
) -> str:
    """Return the hostid for an SNMP-monitored host, creating it if absent.

    Stores the community in a {$SNMP_COMMUNITY} host macro (best practice) and
    references it from the interface. `snmp_dns` is resolved over the compose
    network (e.g. the "snmpsim" service container name).
    """
    existing = api.host.get(filter={"host": host}, output=["hostid"])
    if existing:
        return existing[0]["hostid"]
    result = api.host.create(
        host=host,
        name=visible_name or host,
        groups=[{"groupid": groupid}],
        interfaces=[
            {
                "type": 2,        # 2 = SNMP
                "main": 1,
                "useip": 0,
                "ip": "",
                "dns": snmp_dns,
                "port": port,
                "details": {
                    "version": version,
                    "community": "{$SNMP_COMMUNITY}",
                    "bulk": 1,
                },
            }
        ],
        macros=[{"macro": "{$SNMP_COMMUNITY}", "value": community}],
    )
    return result["hostids"][0]


def ensure_interfaceless_host(
    api: ZabbixAPI,
    host: str,
    groupid: str,
    *,
    visible_name: str | None = None,
) -> str:
    """Return the hostid for a host with no interface, creating it if absent.

    Used for HTTP-agent monitoring where items carry an absolute URL and need
    no host interface.
    """
    existing = api.host.get(filter={"host": host}, output=["hostid"])
    if existing:
        return existing[0]["hostid"]
    result = api.host.create(
        host=host, name=visible_name or host, groups=[{"groupid": groupid}]
    )
    return result["hostids"][0]


# --- Items of other monitoring types -----------------------------------------


def _iface_id(api: ZabbixAPI, hostid: str, iface_type: int) -> str:
    """Return the main interfaceid of a given type (1=agent, 2=SNMP)."""
    hosts = api.host.get(
        hostids=hostid,
        output=["hostid"],
        selectInterfaces=["interfaceid", "type", "main"],
    )
    if not hosts:
        raise ValueError(f"host {hostid!r} not found")
    matches = [
        i for i in hosts[0].get("interfaces") or [] if str(i["type"]) == str(iface_type)
    ]
    if not matches:
        raise ValueError(f"host {hostid!r} has no type-{iface_type} interface")
    main = [i for i in matches if str(i.get("main")) == "1"]
    return (main or matches)[0]["interfaceid"]


def ensure_snmp_item(
    api: ZabbixAPI,
    hostid: str,
    name: str,
    key: str,
    oid: str,
    *,
    value_type: int = 3,
    delay: str = "1m",
) -> str:
    """Return the itemid for an SNMP item (type 20), creating it if absent."""
    existing = api.item.get(hostids=hostid, filter={"key_": key}, output=["itemid"])
    if existing:
        return existing[0]["itemid"]
    result = api.item.create(
        hostid=hostid,
        name=name,
        key_=key,
        type=20,                       # SNMP agent
        snmp_oid=oid,
        value_type=value_type,
        delay=delay,
        interfaceid=_iface_id(api, hostid, 2),
    )
    return result["itemids"][0]


def ensure_simple_item(
    api: ZabbixAPI,
    hostid: str,
    name: str,
    key: str,
    *,
    value_type: int = 3,
    delay: str = "30s",
) -> str:
    """Return the itemid for a simple-check item (type 3), creating it if absent.

    Simple checks (e.g. icmpping, net.tcp.service) run from the server and use
    the host's agent interface only for its address.
    """
    existing = api.item.get(hostids=hostid, filter={"key_": key}, output=["itemid"])
    if existing:
        return existing[0]["itemid"]
    result = api.item.create(
        hostid=hostid,
        name=name,
        key_=key,
        type=3,                        # simple check
        value_type=value_type,
        delay=delay,
        interfaceid=_iface_id(api, hostid, 1),
    )
    return result["itemids"][0]


def ensure_http_item(
    api: ZabbixAPI,
    hostid: str,
    name: str,
    key: str,
    url: str,
    *,
    value_type: int = 4,            # 4 = text
    delay: str = "1m",
    status_codes: str = "200",
    retrieve_mode: int = 0,         # 0 = body
) -> str:
    """Return the itemid for an HTTP-agent item (type 19), creating it if absent.

    No interface needed because the URL is absolute.
    """
    existing = api.item.get(hostids=hostid, filter={"key_": key}, output=["itemid"])
    if existing:
        return existing[0]["itemid"]
    result = api.item.create(
        hostid=hostid,
        name=name,
        key_=key,
        type=19,                       # HTTP agent
        url=url,
        request_method=0,              # GET
        retrieve_mode=retrieve_mode,
        status_codes=status_codes,
        value_type=value_type,
        delay=delay,
    )
    return result["itemids"][0]


# --- Geo location + maps -----------------------------------------------------


def set_host_location(
    api: ZabbixAPI,
    hostid: str,
    lat: float,
    lon: float,
    location_text: str | None = None,
) -> bool:
    """Set a host's inventory lat/lon (and optional label) for the geomap."""
    inventory = {"location_lat": str(lat), "location_lon": str(lon)}
    if location_text:
        inventory["location"] = location_text
    api.host.update(hostid=hostid, inventory_mode=0, inventory=inventory)
    return True


def _icon_id(api: ZabbixAPI) -> str:
    """Return a usable map icon imageid, preferring a server/workstation icon."""
    return _map_icons(api)["server"]


def _map_icons(api: ZabbixAPI) -> dict[str, str]:
    """Return imageids for server / router / cloud / workstation map icons."""
    images = api.image.get(filter={"imagetype": 1}, output=["imageid", "name"])
    if not images:
        raise RuntimeError("no map icons found in this Zabbix instance")
    by_name = {im["name"]: im["imageid"] for im in images}
    fallback = images[0]["imageid"]

    def pick(*names: str) -> str:
        for name in names:
            if name in by_name:
                return by_name[name]
        return fallback

    return {
        "server": pick("Server_(96)", "Server_(64)", "Workstation_(96)"),
        "router": pick("Router_(96)", "Router_(64)", "Server_(96)"),
        "cloud": pick("Cloud_(96)", "Cloud_(64)", "Server_(96)"),
        "workstation": pick("Workstation_(96)", "Workstation_(64)", "Server_(96)"),
    }


def ensure_map(
    api: ZabbixAPI,
    name: str,
    center_hostid: str,
    spoke_hostids: list[str],
    *,
    width: int = 900,
    height: int = 600,
) -> str:
    """Create a star-topology network map (center linked to each spoke).

    Idempotent: returns the existing sysmapid if a map with this name exists.
    Map labels default to the element (host) name, so none are set per element.
    """
    existing = api.map.get(filter={"name": name}, output=["sysmapid"])
    if existing:
        return existing[0]["sysmapid"]

    icon = _icon_id(api)
    cx, cy = width // 2 - 24, height // 2 - 24
    selements = [
        {
            "selementid": "1",
            "elements": [{"hostid": center_hostid}],
            "elementtype": 0,          # 0 = host
            "iconid_off": icon,
            "x": cx,
            "y": cy,
        }
    ]
    links = []
    radius = min(width, height) // 2 - 80
    n = max(len(spoke_hostids), 1)
    for i, hid in enumerate(spoke_hostids):
        angle = 2 * math.pi * i / n
        sel = str(i + 2)
        selements.append(
            {
                "selementid": sel,
                "elements": [{"hostid": hid}],
                "elementtype": 0,
                "iconid_off": icon,
                "x": int(cx + radius * math.cos(angle)),
                "y": int(cy + radius * math.sin(angle)),
            }
        )
        links.append(
            {
                "selementid1": "1",
                "selementid2": sel,
                "color": "00CC00",
                "drawtype": 0,
            }
        )
    result = api.map.create(
        name=name,
        width=width,
        height=height,
        label_type=2,                  # 2 = element name
        selements=selements,
        links=links,
    )
    return result["sysmapids"][0]


def ensure_topology_map(
    api: ZabbixAPI,
    name: str,
    hostids: dict[str, str],
    *,
    triggerids: dict[str, str] | None = None,
    width: int = 1200,
    height: int = 800,
) -> str:
    """Create or refresh a multi-segment corporate topology map.

    Layout: Zabbix server at the core, five cooperating corporate networks in a
    pentagon, shared internal segments, edge clusters (homes / shops / SOHO), and
    the four lab hosts linked into the story with live trigger coloring.

    Re-running replaces an existing map of the same name (delete + create) so
    coordinates and links stay in sync with the script.
    """
    icons = _map_icons(api)
    triggerids = triggerids or {}

    def host_el(sid: str, host_key: str, icon: str, x: int, y: int) -> dict:
        return {
            "selementid": sid,
            "elementtype": 0,
            "elements": [{"hostid": hostids[host_key]}],
            "iconid_off": icons[icon],
            "iconid_on": icons[icon],
            "x": x,
            "y": y,
        }

    def image_el(sid: str, label: str, icon: str, x: int, y: int) -> dict:
        return {
            "selementid": sid,
            "elementtype": 4,
            "iconid_off": icons[icon],
            "label": label,
            "x": x,
            "y": y,
        }

    selements = [
        host_el("core", "Zabbix server", "server", 560, 360),
        image_el("corp-a", "Corp Alpha", "router", 560, 60),
        image_el("corp-b", "Corp Beta", "router", 980, 160),
        image_el("corp-g", "Corp Gamma", "router", 980, 560),
        image_el("corp-d", "Corp Delta", "router", 140, 560),
        image_el("corp-e", "Corp Epsilon", "router", 140, 160),
        image_el("int-dc", "Internal DC", "cloud", 720, 80),
        image_el("int-mgmt", "Internal MGMT", "cloud", 400, 80),
        image_el("int-partner", "Partner / B2B VPN", "cloud", 560, 220),
        image_el("homes", "Homes (Residential)", "workstation", 40, 360),
        image_el("shops", "Shops (Retail)", "workstation", 1080, 360),
        image_el("soho", "Small offices (SOHO)", "workstation", 560, 700),
        host_el("h-agent", "test-host-01", "server", 680, 120),
        host_el("h-snmp", "snmp-device-01", "router", 900, 220),
        host_el("h-http", "frontend-http-01", "server", 900, 500),
        host_el("h-icmp", "router-icmp-01", "router", 300, 360),
    ]

    def link(
        a: str,
        b: str,
        *,
        label: str = "",
        color: str = "00CC00",
        drawtype: int = 0,
        linktriggers: list[dict] | None = None,
    ) -> dict:
        row: dict = {
            "selementid1": a,
            "selementid2": b,
            "color": color,
            "drawtype": drawtype,
        }
        if label:
            row["label"] = label
        if linktriggers:
            row["linktriggers"] = linktriggers
        return row

    icmp_trig = triggerids.get("router-icmp-01: host unreachable (ICMP)")
    icmp_indicators = (
        [{"triggerid": icmp_trig, "color": "DD0000", "drawtype": 2}] if icmp_trig else None
    )

    links = [
        # Core to each corporate network
        link("core", "corp-a", label="MPLS"),
        link("core", "corp-b", label="MPLS"),
        link("core", "corp-g", label="MPLS"),
        link("core", "corp-d", label="MPLS"),
        link("core", "corp-e", label="MPLS"),
        # Five corps cooperate (peering ring)
        link("corp-a", "corp-b", label="Peering", color="0066CC", drawtype=4),
        link("corp-b", "corp-g", label="Peering", color="0066CC", drawtype=4),
        link("corp-g", "corp-d", label="Peering", color="0066CC", drawtype=4),
        link("corp-d", "corp-e", label="Peering", color="0066CC", drawtype=4),
        link("corp-e", "corp-a", label="Peering", color="0066CC", drawtype=4),
        # Shared internal networks
        link("core", "int-dc", label="Internal backbone"),
        link("core", "int-mgmt", label="Internal backbone"),
        link("core", "int-partner", label="Internal backbone"),
        link("corp-a", "int-dc", label="DC access", color="0066CC", drawtype=3),
        link("corp-b", "int-partner", label="B2B VPN", color="0066CC", drawtype=3),
        link("corp-g", "int-partner", label="B2B VPN", color="0066CC", drawtype=3),
        link("int-dc", "int-mgmt", label="East-west", color="0066CC", drawtype=3),
        # Edge segments into corporate WAN
        link("homes", "corp-e", label="Residential ISP"),
        link("shops", "corp-b", label="Retail uplink"),
        link("soho", "corp-d", label="SOHO VPN"),
        # Lab hosts in context
        link("h-agent", "corp-a", label="Agent LAN", drawtype=3),
        link("h-snmp", "corp-b", label="SNMP edge", drawtype=3),
        link("h-http", "corp-g", label="HTTP DMZ", drawtype=3),
        link(
            "h-icmp",
            "core",
            label="WAN ICMP",
            drawtype=2,
            linktriggers=icmp_indicators,
        ),
    ]

    shapes = [
        {
            "type": 0,
            "x": 80,
            "y": 20,
            "width": 1040,
            "height": 200,
            "text": "Corporate WAN — five cooperating networks",
            "font": 11,
            "font_color": "333333",
            "background_color": "E8EEF4",
            "border_color": "B0BEC5",
            "zindex": 0,
        },
        {
            "type": 0,
            "x": 320,
            "y": 50,
            "width": 520,
            "height": 120,
            "text": "Shared internal (DC, MGMT, Partner VPN)",
            "font": 10,
            "font_color": "333333",
            "background_color": "E3F2FD",
            "border_color": "90CAF9",
            "zindex": 0,
        },
        {
            "type": 0,
            "x": 20,
            "y": 640,
            "width": 1160,
            "height": 140,
            "text": "Edge access — homes, shops, small offices",
            "font": 10,
            "font_color": "333333",
            "background_color": "F3E5F5",
            "border_color": "CE93D8",
            "zindex": 0,
        },
    ]

    existing = api.map.get(filter={"name": name}, output=["sysmapid"])
    if existing:
        api.map.delete([existing[0]["sysmapid"]])

    result = api.map.create(
        name=name,
        width=width,
        height=height,
        label_type=2,
        label_type_image=5,
        highlight=1,
        markelements=1,
        expandproblem=1,
        grid_show=1,
        grid_align=1,
        grid_size=50,
        selements=selements,
        links=links,
        shapes=shapes,
    )
    return result["sysmapids"][0]


def ensure_geomap_provider(
    api: ZabbixAPI,
    *,
    url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: str = "© OpenStreetMap contributors",
    max_zoom: str = "19",
) -> bool:
    """Configure the global geomap tile provider (custom OpenStreetMap).

    A provider must be set or geomap widgets render an error. Idempotent.
    """
    api.settings.update(
        geomaps_tile_provider="",      # "" = custom, use the URL below
        geomaps_tile_url=url,
        geomaps_attribution=attribution,
        geomaps_max_zoom=max_zoom,
    )
    return True


def ensure_geomap_dashboard(
    api: ZabbixAPI,
    name: str,
    groupid: str,
    *,
    sysmapid: str | None = None,
) -> str:
    """Create a dashboard with a geomap widget (and optional network-map widget).

    Idempotent: returns the existing dashboardid if the name is taken. The
    geomap plots every host in `groupid` that has inventory lat/lon set.
    """
    existing = api.dashboard.get(filter={"name": name}, output=["dashboardid"])
    if existing:
        return existing[0]["dashboardid"]

    widgets = [
        {
            "type": "geomap",
            "name": "Hosts (geo)",
            "x": 0,
            "y": 0,
            "width": 36,               # dashboard grid is 72 columns wide (7.0)
            "height": 12,
            "fields": [
                {"type": 2, "name": "groupids.0", "value": groupid},
            ],
        }
    ]
    if sysmapid:
        widgets.append(
            {
                "type": "map",
                "name": "Network map",
                "x": 36,
                "y": 0,
                "width": 36,
                "height": 12,
                "fields": [
                    {"type": 0, "name": "source_type", "value": 1},  # 1 = map
                    {"type": 8, "name": "sysmapid", "value": sysmapid},
                ],
            }
        )
    result = api.dashboard.create(
        name=name,
        display_period=30,
        auto_start=1,
        pages=[{"widgets": widgets}],
    )
    return result["dashboardids"][0]
