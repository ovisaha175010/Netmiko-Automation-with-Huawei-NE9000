"""
Huawei router automation: Jinja2 (render config) + Netmiko (push config).
Self-contained: the template is embedded, no router.j2 needed.

Behaviour:
  1. Render the config from DATA with Jinja2
  2. For every interface in DATA: if it already has configuration,
     wipe it ("clear configuration interface") and then reconfigure it
  3. Push the rendered config, commit, save, verify

Install:  pip install netmiko jinja2
Run:      python3 py_jinja2_Day11.py            (push to router)
          python3 py_jinja2_Day11.py --dry-run  (only render the config)
"""
import socket
import sys

from jinja2 import Environment
from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

# ================== EDIT THIS ==================
ROUTER_IP = "1.11.11.22"   # must be the router's real, reachable management IP
USERNAME = "ovi123"
PASSWORD = "Test@123"
# ===============================================

DEVICE = {
    "device_type": "huawei_vrpv8",
    "host": ROUTER_IP,
    "port": 22,
    "username": USERNAME,
    "password": PASSWORD,
    "conn_timeout": 60,
}

TEMPLATE = """\
sysname {{ hostname }}
{% for intf in interfaces %}
interface {{ intf.name }}
 description {{ intf.desc }}
 ip address {{ intf.ip }} {{ intf.mask }}
 undo shutdown
quit
{% endfor %}
{% if ospf %}
ospf {{ ospf.process_id }}
 area {{ ospf.area }}
{% for net in ospf.networks %}
  network {{ net.network }} {{ net.wildcard }}
{% endfor %}
quit
quit
{% endif %}
{% if bgp %}
bgp {{ bgp.asn }}
{% for n in bgp.neighbors %}
 peer {{ n.ip }} as-number {{ n.asn }}
{% endfor %}
quit
{% endif %}
"""

DATA = {
    "hostname": "R1",
    "interfaces": [
        {"name": "Ethernet1/0/4", "desc": "Uplink",
         "ip": "10.0.0.1", "mask": "255.255.255.252"},
        {"name": "Ethernet1/0/8", "desc": "LAN",
         "ip": "10.1.1.1", "mask": "255.255.255.0"},
    ],
    "ospf": {
        "process_id": 1,
        "area": "0.0.0.0",
        "networks": [
            {"network": "10.1.1.0", "wildcard": "0.0.0.255"},
            {"network": "10.0.0.0", "wildcard": "0.0.0.3"},
        ],
    },
    "bgp": {
        "asn": 65001,
        "neighbors": [{"ip": "10.0.0.2", "asn": 65002}],
    },
}


# ---------------------------------------------------------------- helpers
def render_config(data):
    env = Environment(trim_blocks=True, lstrip_blocks=True)
    rendered = env.from_string(TEMPLATE).render(data)
    return [line for line in rendered.splitlines() if line.strip()]


def port_open(host, port, timeout=5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def pick_connection():
    """Use SSH if port 22 answers, otherwise fall back to Telnet on port 23."""
    if port_open(ROUTER_IP, 22):
        return dict(DEVICE)

    print(f"[!] SSH (22) is not reachable on {ROUTER_IP}.")
    if port_open(ROUTER_IP, 23):
        print("[i] Telnet (23) is open - falling back to Telnet.")
        dev = dict(DEVICE)
        dev["device_type"] = "huawei_telnet"
        dev["port"] = 23
        return dev

    print(f"[X] Neither SSH (22) nor Telnet (23) is reachable on {ROUTER_IP}.")
    print("    Check ping, VMware network mode, SSH enabled on router, ACL/firewall.")
    return None


# Lines that exist even on an unconfigured interface
IGNORED = ("#", "return", "interface ", "undo shutdown", "shutdown")


def interface_config(conn, name):
    """Return the meaningful config lines currently on an interface."""
    out = conn.send_command(f"display current-configuration interface {name}")
    lines = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line or line.startswith(IGNORED):
            continue
        if line.lower().startswith(("error", "info:", "^")):
            continue
        lines.append(line)
    return lines


def clear_interface(conn, name):
    """Reset an interface to default. Answers the [Y/N] confirmation."""
    conn.config_mode()
    out = conn.send_command_timing(f"clear configuration interface {name}")
    if "[Y/N]" in out or "[y/n]" in out:
        out += conn.send_command_timing("y")
    conn.exit_config_mode()
    return out


def clean_existing_interfaces(conn, interfaces):
    """Remove old config from every interface we are about to configure."""
    for intf in interfaces:
        name = intf["name"]
        existing = interface_config(conn, name)

        if not existing:
            print(f"[=] {name}: no existing config, nothing to remove")
            continue

        # Never cut our own management session
        if any(ROUTER_IP in line for line in existing):
            print(f"[!] {name}: carries the management IP {ROUTER_IP}; "
                  "skipping clear to keep the session alive (it will be reconfigured in place)")
            continue

        print(f"[-] {name}: found existing config, removing:")
        for line in existing:
            print(f"      {line}")
        clear_interface(conn, name)


# ------------------------------------------------------------------- main
def main():
    commands = render_config(DATA)

    print("----- Generated configuration -----")
    print("\n".join(commands))
    print("-----------------------------------")

    if "--dry-run" in sys.argv:
        print("[i] Dry run: nothing was sent to the router.")
        return

    device = pick_connection()
    if device is None:
        sys.exit(1)

    try:
        with ConnectHandler(**device) as conn:
            print("Connected to:", conn.find_prompt())

            # 1) Remove old interface config
            clean_existing_interfaces(conn, DATA["interfaces"])

            # 2) Apply the new config
            print(conn.send_config_set(commands))

            # VRPv8 uses a commit-based model
            try:
                print(conn.commit())
            except Exception as e:
                print("Commit skipped/not required:", e)

            conn.exit_config_mode()
            print(conn.save_config())

            print("----- Verification -----")
            print(conn.send_command("display ip interface brief"))

    except NetmikoAuthenticationException:
        print("[X] Login failed: wrong username/password, or user lacks ssh/telnet service-type.")
        sys.exit(1)
    except NetmikoTimeoutException as e:
        print("[X] Connection timed out:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()