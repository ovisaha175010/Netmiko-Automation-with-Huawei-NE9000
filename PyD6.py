""" Second example for the same Huawei router: VLAN sub-interfaces (router-on-a-stick),
DHCP pools and NAT, built with lambda + filter / map / reduce.

  filter -> keep only usable VLANs, DHCP VLANs, NAT VLANs, duplicates
  map    -> turn each VLAN into sub-interface / DHCP pool / ACL-rule commands
  reduce -> flatten command lists, count duplicates, total DHCP capacity

Other helpers used where needed: sorted, enumerate, any.

Install:  pip install netmiko
Run:      python huawei_vlan_dhcp_nat.py """






from functools import reduce
from getpass import getpass
from netmiko import ConnectHandler

device = {
    "device_type": "huawei_vrpv8",
    "host": "192.168.74.215",
    "port": 22,
    "username": "ovi123",
    "password": getpass("Password: "),
    "conn_timeout": 15,
    "session_log": "netmiko_session.log",
}

PARENT = "Ethernet1/0/7"

vlans = [
    {"id": 10, "name": "SERVERS", "ip": "192.168.10.1", "mask": "255.255.255.0"},
    {"id": 20, "name": "SALES",   "ip": "192.168.20.1", "mask": "255.255.255.0"},
    {"id": 30, "name": "STAFF",   "ip": "192.168.30.1", "mask": "255.255.255.0"},
]

valid_vid = lambda n: 1 <= n <= 4094
flatten   = lambda lists: reduce(lambda a, c: a + c, lists, [])

subif = lambda v: [
    f"interface {PARENT}.{v['id']}",
    f"description {v['name']}",
    f"vlan-type dot1q {v['id']}",
    f"ip address {v['ip']} {v['mask']}",
    "undo shutdown",
    "quit",
]

def run(conn, cmds):
    """Send one command at a time; stop on the first error."""
    for c in cmds:
        out = conn.send_command_timing(c, strip_prompt=False, strip_command=False)
        if "Error" in out:
            print(f"\nFAILED at: {c}\n{out}")
            return False
    return True

if __name__ == "__main__":
    with ConnectHandler(**device) as conn:
        print(conn.find_prompt())

        # Skip VLANs whose IP is already configured on the router
        current = conn.send_command("display current-configuration | include ip address")
        todo = list(filter(
            lambda v: valid_vid(v["id"]) and f"ip address {v['ip']} " not in current,
            vlans))
        skipped = [v["ip"] for v in vlans if v not in todo]
        if skipped:
            print("Already configured, skipped:", skipped)
        if not todo:
            raise SystemExit("Nothing to do.")

        cmds = flatten(map(subif, todo))
        print("\n".join(cmds))
        if input("Push this? (y/N): ").strip().lower() != "y":
            raise SystemExit("Aborted.")

        conn.send_command_timing("system-view")
        if run(conn, cmds):
            print(conn.send_command_timing("commit"))
            conn.send_command_timing("return")
            print(conn.send_command("display ip interface brief"))
            if input("Save? (y/N): ").strip().lower() == "y":
                print(conn.send_command_timing("save"))
                print(conn.send_command_timing("y"))
        else:
            conn.send_command_timing("abort")
            print("Nothing was committed.")



#  updated Code for PyD6.py  = > Remove Configuaration commands and only run commands to display information from the device.

from getpass import getpass
from netmiko import ConnectHandler

device = {
    "device_type": "huawei_vrpv8",
    "host": "192.168.74.215",
    "port": 22,
    "username": "ovi123",
    "password": getpass("Password: "),
    "conn_timeout": 15,
    "session_log": "netmiko_session.log",
}

PARENT = "Ethernet1/0/7"
PROTECTED = ["Ethernet1/0/0", "LoopBack0"]   # never touched
AUTO_SAVE = True                              # False = ask before saving

vlans = [
    {"id": 10, "name": "SERVERS", "ip": "192.168.10.1", "mask": "255.255.255.0"},
    {"id": 20, "name": "SALES",   "ip": "192.168.20.1", "mask": "255.255.255.0"},
    {"id": 30, "name": "STAFF",   "ip": "192.168.30.1", "mask": "255.255.255.0"},
]


def read_interfaces(conn):
    """Return {interface_name: [config lines]} from the running config."""
    out = conn.send_command("display current-configuration interface", read_timeout=60)
    blocks, name = {}, None
    for line in out.splitlines():
        if line.startswith("interface "):
            name = line.split()[1]
            blocks[name] = []
        elif name and line.startswith(" "):
            blocks[name].append(line.strip())
        elif line.startswith("#"):
            name = None
    return blocks


def run(conn, cmds):
    """Send one command at a time; stop on the first error."""
    for c in cmds:
        out = conn.send_command_timing(c)
        if "Error" in out:
            print(f"\nFAILED at: {c}\n{out}")
            return False
    return True


if __name__ == "__main__":
    with ConnectHandler(**device) as conn:
        print(conn.find_prompt())
        current = read_interfaces(conn)

        targets = {f"{PARENT}.{v['id']}": v for v in vlans}
        wanted_ips = {v["ip"] for v in vlans}
        remove = {}   # interface -> list of config lines to undo

        # 1. Target sub-interfaces that already exist: remove all their config
        for name in targets:
            if name in current and name not in PROTECTED:
                remove[name] = current[name]

        # 2. Any other interface holding one of our IPs: remove just that IP line
        for name, lines in current.items():
            if name in PROTECTED or name in remove:
                continue
            ip_lines = [l for l in lines
                        if l.startswith("ip address ") and l.split()[2] in wanted_ips]
            if ip_lines:
                remove[name] = ip_lines

        # 3. Never touch the interface we are connected through
        for name in list(remove):
            if any(device["host"] in l for l in remove[name]):
                print(f"SKIPPED {name}: holds the management IP")
                del remove[name]

        cmds = []
        for name, lines in remove.items():
            print(f"\nWill remove from {name}:")
            print("\n".join(f"   {l}" for l in lines))
            cmds.append(f"interface {name}")
            for l in lines:
                if l.startswith("undo "):
                    continue
                cmds.append("undo description" if l.startswith("description") else f"undo {l}")
            cmds.append("quit")

        for v in vlans:
            cmds += [
                f"interface {PARENT}.{v['id']}",
                f"description {v['name']}",
                f"vlan-type dot1q {v['id']}",
                f"ip address {v['ip']} {v['mask']}",
                "undo shutdown",
                "quit",
            ]

        print("\n----- Commands to push -----")
        print("\n".join(cmds))
        if input("\nPush this? (y/N): ").strip().lower() != "y":
            raise SystemExit("Aborted, nothing changed.")

        conn.send_command_timing("system-view")
        if run(conn, cmds):
            print(conn.send_command_timing("commit"))
            conn.send_command_timing("return")
            print(conn.send_command("display ip interface brief"))
            if AUTO_SAVE or input("Save? (y/N): ").strip().lower() == "y":
                print(conn.send_command_timing("save"))
                print(conn.send_command_timing("y"))
        else:
            conn.send_command_timing("abort")
            print("Nothing was committed.")