
#lambda Functions to generate commands

#without clear interface 


"""
Configure a Huawei router (VRP) with Netmiko, using lambda functions
to generate the commands.

Install:  pip install netmiko
Run:      python huawei_router_config.py
"""
import socket
import struct
from getpass import getpass
from itertools import chain

from netmiko import ConnectHandler

# ---------------- Device ----------------
device = {
    "device_type": "huawei_vrpv8",
    "host": "192.168.74.215",      # management IP of the router
    "port": 22,
    "username": "ovi123",
    "password": getpass("Password: "),
    "conn_timeout": 15,
}

# ---------------- Lambda helpers ----------------
cidr_to_mask = lambda c: socket.inet_ntoa(struct.pack("!I", (0xFFFFFFFF << (32 - c)) & 0xFFFFFFFF))
wildcard     = lambda c: socket.inet_ntoa(struct.pack("!I", (1 << (32 - c)) - 1))
valid_ip     = lambda ip: len(ip.split(".")) == 4 and all(
    map(lambda o: o.isdigit() and 0 <= int(o) <= 255, ip.split(".")))
confirm      = lambda msg: input(msg).strip().lower() == "y"

# ---------------- Lambda command generators (Huawei VRP syntax) ----------------
sysname      = lambda name: [f"sysname {name}"]

interface    = lambda n, ip, c, d="": [
    f"interface {n}",
    *([f"description {d}"] if d else []),
    f"ip address {ip} {cidr_to_mask(c)}",
    "undo shutdown",
    "quit",
]

static_route = lambda net, c, nh: [f"ip route-static {net} {cidr_to_mask(c)} {nh}"]

ospf         = lambda pid, net, c, area="0.0.0.0": [
    f"ospf {pid}",
    f"area {area}",
    f"network {net} {wildcard(c)}",
    "quit",
    "quit",
]

acl_permit   = lambda num, rule, net, c: [
    f"acl number {num}",
    f"rule {rule} permit source {net} {wildcard(c)}",
    "quit",
]

# ---------------- Router data (edit to match your device) ----------------
HOSTNAME = "R1"

interfaces = [
    {"name": "Ethernet1/0/5", "ip": "192.168.10.1", "cidr": 24, "desc": "LAN"},
    {"name": "Ethernet1/0/6", "ip": "10.0.0.1",     "cidr": 30, "desc": "WAN"},
]
routes = [
    ("0.0.0.0", 0, "10.0.0.2"),
]

# Drop entries with invalid IPs (filter + lambda)
interfaces = list(filter(lambda i: valid_ip(i["ip"]), interfaces))
routes     = list(filter(lambda r: valid_ip(r[0]) and valid_ip(r[2]), routes))

# ---------------- Build the config (map + chain, no explicit loops) ----------------
config = list(chain(
    sysname(HOSTNAME),
    chain.from_iterable(map(lambda i: interface(i["name"], i["ip"], i["cidr"], i["desc"]), interfaces)),
    chain.from_iterable(map(lambda r: static_route(*r), routes)),
    ospf(1, "192.168.10.0", 24),
    acl_permit(2000, 5, "192.168.10.0", 24),
))

# ---------------- Connection lambdas ----------------
push = lambda conn, cmds: conn.send_config_set(cmds)   # enters system-view automatically
save = lambda conn: (                                   # Huawei "save" asks for confirmation
    conn.send_command_timing("save")
    + conn.send_command_timing("y")
)

if __name__ == "__main__":
    print("----- Config to be pushed -----")
    print("\n".join(config))
    print("-------------------------------")

    if not confirm(f"Push this to {device['host']}? (y/N): "):
        raise SystemExit("Aborted, nothing was changed.")

    try:
        with ConnectHandler(**device) as conn:
            print(conn.find_prompt())
            print(push(conn, config))

            # VRP V8 (NE/CE series) uses a candidate config, so commit is required.
            # On older VRP V5 devices (AR series), change device_type to "huawei" and remove this line.
            print(conn.commit())

            print(conn.send_command("display ip interface brief"))
            print(conn.send_command("display ip routing-table protocol static"))

            if confirm("Save configuration to startup? (y/N): "):
                print(save(conn))
    except Exception as e:
        raise SystemExit(f"Connection or configuration failed: {e}")




#with Clear interface data

"""
Configure a Huawei router (VRP) with Netmiko, using lambda functions
to generate the commands.

New in this version: any existing configuration found on the interfaces
listed in CLEAN_INTERFACES (e.g. GigabitEthernet0/0/1) is removed first,
then the interface is configured from scratch.

Install:  pip install netmiko
Run:      python huawei_router_config.py
"""
import socket
import struct
from getpass import getpass
from itertools import chain

from netmiko import ConnectHandler

# ---------------- Device ----------------
device = {
    "device_type": "huawei_vrpv8",
    "host": "192.168.74.215",      # management IP of the router
    "port": 22,
    "username": "ovi123",
    "password": getpass("Password: "),
    "conn_timeout": 15,
    "session_log": "netmiko_session.log",   # full CLI dialogue, for debugging
}

# ---------------- Lambda helpers ----------------
cidr_to_mask = lambda c: socket.inet_ntoa(struct.pack("!I", (0xFFFFFFFF << (32 - c)) & 0xFFFFFFFF))
wildcard     = lambda c: socket.inet_ntoa(struct.pack("!I", (1 << (32 - c)) - 1))
valid_ip     = lambda ip: len(ip.split(".")) == 4 and all(
    map(lambda o: o.isdigit() and 0 <= int(o) <= 255, ip.split(".")))
confirm      = lambda msg: input(msg).strip().lower() == "y"

# ---------------- Lambda command generators (Huawei VRP syntax) ----------------
sysname      = lambda name: [f"sysname {name}"]

interface    = lambda n, ip, c, d="": [
    f"interface {n}",
    *([f"description {d}"] if d else []),
    f"ip address {ip} {cidr_to_mask(c)}",
    "undo shutdown",
    "quit",
]

static_route = lambda net, c, nh: [f"ip route-static {net} {cidr_to_mask(c)} {nh}"]

ospf         = lambda pid, net, c, area="0.0.0.0": [
    f"ospf {pid}",
    f"area {area}",
    f"network {net} {wildcard(c)}",
    "quit",
    "quit",
]

acl_permit   = lambda num, rule, net, c: [
    f"acl number {num}",
    f"rule {rule} permit source {net} {wildcard(c)}",
    "quit",
]

# ---------------- Lambdas: find and remove existing interface config ----------------
show_if    = lambda name: f"display current-configuration interface {name}"

# keep only real config lines (drop '#', 'interface ...', 'return', prompts, 'undo ...' lines)
SKIP       = ("#", "interface", "return", "undo ", "<", "[", "display", "Info:", "Warning:")
is_cfg     = lambda l: bool(l) and not l.startswith(SKIP)
found_cfg  = lambda out: list(filter(is_cfg, map(str.strip, out.splitlines())))

# "description LAN" -> "undo description", everything else -> "undo <line>"
undo_line  = lambda l: "undo description" if l.startswith("description") else f"undo {l}"
make_undo  = lambda name, lines: (
    [f"interface {name}", *map(undo_line, reversed(lines)), "quit"] if lines else []
)

holds_mgmt = lambda lines: any(device["host"] in l for l in lines)

# ---------------- Router data (edit to match your device) ----------------
HOSTNAME = "R1"
# Changing sysname changes the CLI prompt mid-session, which can make Netmiko lose
# track of the prompt ("Pattern not detected"). Leave False unless you need it.
CHANGE_HOSTNAME = False

# Interfaces to wipe before reconfiguring
CLEAN_INTERFACES = ["Ethernet1/0/5"]

interfaces = [
    {"name": "Ethernet1/0/5", "ip": "192.168.10.1", "cidr": 24, "desc": "LAN"},
    {"name": "Ethernet1/0/6", "ip": "10.0.0.1",     "cidr": 30, "desc": "WAN"},
]
routes = [

    ("0.0.0.0", 0, "10.0.0.2"),
]

# Drop entries with invalid IPs (filter + lambda)
interfaces = list(filter(lambda i: valid_ip(i["ip"]), interfaces))
routes     = list(filter(lambda r: valid_ip(r[0]) and valid_ip(r[2]), routes))

# ---------------- Build the new config (map + chain, no explicit loops) ----------------
config = list(chain(
    sysname(HOSTNAME) if CHANGE_HOSTNAME else [],
    chain.from_iterable(map(lambda i: interface(i["name"], i["ip"], i["cidr"], i["desc"]), interfaces)),
    chain.from_iterable(map(lambda r: static_route(*r), routes)),
    ospf(1, "192.168.10.0", 24),
    acl_permit(2000, 5, "192.168.10.0", 24),
))

# ---------------- Connection lambdas ----------------
push = lambda conn, cmds: conn.send_config_set(        # enters system-view automatically
    cmds, read_timeout=60, cmd_verify=False)
save = lambda conn: (                                   # Huawei "save" asks for confirmation
    conn.send_command_timing("save")
    + conn.send_command_timing("y")
)

if __name__ == "__main__":
    try:
        with ConnectHandler(**device) as conn:
            print(conn.find_prompt())

            # 1) Read what is currently configured on each interface to clean
            existing = {n: found_cfg(conn.send_command(show_if(n))) for n in CLEAN_INTERFACES}
            undo     = list(chain.from_iterable(map(lambda kv: make_undo(*kv), existing.items())))

            # 2) Preview
            print("\n----- Existing config found (will be removed) -----")
            for name, lines in existing.items():
                print(f"{name}:")
                print("\n".join(f"   {l}" for l in lines) if lines else "   (nothing configured)")

            print("\n----- Commands to be pushed -----")
            print("\n".join(undo + config))
            print("---------------------------------")

            # 3) Safety check: don't cut off our own SSH session by accident
            if any(map(holds_mgmt, existing.values())):
                print(f"\nWARNING: an interface being cleaned holds the management IP {device['host']}.")
                print("Removing it will drop this SSH session.")
                if not confirm("Continue anyway? (y/N): "):
                    raise SystemExit("Aborted, nothing was changed.")

            if not confirm(f"Push this to {device['host']}? (y/N): "):
                raise SystemExit("Aborted, nothing was changed.")

            # 4) Remove old config, then apply the new one
            try:
                print(push(conn, undo + config))
            except Exception as e:
                raise SystemExit(
                    f"Push failed: {e.__class__.__name__}. If a cleaned interface carried "
                    f"{device['host']}, the SSH session dropped. Check netmiko_session.log."
                )

            # VRP V8 (NE/CE series) uses a candidate config, so commit is required.
            # On older VRP V5 devices (AR series), change device_type to "huawei" and remove this line.
            print(conn.commit())

            # 5) Verify
            for n in CLEAN_INTERFACES:
                print(conn.send_command(show_if(n)))
            print(conn.send_command("display ip interface brief"))
            print(conn.send_command("display ip routing-table protocol static"))

            if confirm("Save configuration to startup? (y/N): "):
                print(save(conn))
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(f"Connection or configuration failed: {e}")
