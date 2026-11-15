"""
Huawei Router Automation (Netmiko + OOP)
----------------------------------------
Target : Huawei VRP router, device_type = huawei_vrpv8
Needs  : pip install netmiko

Checks included:
  1. Display current configuration
  2. Eth-Trunk (bundle port) check
  3. Interface check

Concepts used:
  - Constructor            -> __init__
  - Instance / Static / Local variables
  - Instance / Class / Static methods
  - Inheritance            -> Router (parent) -> HuaweiRouter (child)
"""

import ipaddress
import re
from datetime import datetime
from getpass import getpass

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


# ======================================================================
# PARENT CLASS : generic router
# ======================================================================
class Router:
    # ---- STATIC (CLASS) VARIABLES : shared by all routers ----
    total_routers = 0
    default_port = 22

    # ---- CONSTRUCTOR ----
    def __init__(self, device):
        # ---- INSTANCE VARIABLES : unique to each router ----
        self.device = device
        self.host = device["host"]
        self.conn = None
        self.connected = False
        Router.total_routers += 1

    # ================= INSTANCE METHODS =================
    def connect(self):
        if not Router.is_valid_ip(self.host):
            print(f"[{self.host}] ERROR: invalid IP address")
            return False
        try:
            self.conn = ConnectHandler(**self.device)
            self.connected = True
            print(f"[{self.host}] Connected. Prompt: {self.conn.find_prompt()}")
            return True
        except NetmikoAuthenticationException:
            print(f"[{self.host}] ERROR: authentication failed")
        except NetmikoTimeoutException:
            print(f"[{self.host}] ERROR: timeout (check IP, SSH, reachability)")
        except Exception as e:
            print(f"[{self.host}] ERROR: {e}")
        return False

    def disconnect(self):
        if self.conn and self.connected:
            self.conn.disconnect()
            self.connected = False
            print(f"[{self.host}] Disconnected")

    def run_show(self, command):
        """Run one show/display command and return its output."""
        return self.conn.send_command(command)

    def backup_config(self):
        output = self.run_show(self.show_run_command())     # local variable
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")    # local variable
        filename = f"{self.host}_{stamp}_backup.txt"        # local variable
        with open(filename, "w") as f:
            f.write(output)
        print(f"[{self.host}] Backup saved to {filename}")
        return filename

    def show_run_command(self):
        return "show running-config"

    # ================= CLASS METHODS =================
    @classmethod
    def get_total_routers(cls):
        return cls.total_routers

    # ================= STATIC METHODS =================
    @staticmethod
    def is_valid_ip(ip):
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

    @staticmethod
    def prefix_to_mask(prefix):
        return str(ipaddress.ip_network(f"0.0.0.0/{prefix}").netmask)


# ======================================================================
# CHILD CLASS : Huawei VRP
# ======================================================================
class HuaweiRouter(Router):
    def __init__(self, device):
        super().__init__(device)
        self.vendor = "huawei"

    # Override: Huawei uses "display", not "show"
    def show_run_command(self):
        return "display current-configuration"

    # ------------------------------------------------------------------
    # CHECK 1 : Current configuration
    # ------------------------------------------------------------------
    def check_current_config(self, section=None):
        """
        Display the current configuration.
        section=None          -> full configuration
        section="Eth-Trunk1"  -> only that interface's configuration
        """
        if section:
            cmd = f"display current-configuration interface {section}"
        else:
            cmd = "display current-configuration"
        print(f"\n===== {cmd} =====")
        output = self.run_show(cmd)
        print(output)
        return output

    # ------------------------------------------------------------------
    # CHECK 2 : Eth-Trunk (bundle ports)
    # ------------------------------------------------------------------
    def check_eth_trunk(self, trunk_id=None):
        """
        Display Eth-Trunk bundle status.
        trunk_id=None -> all trunks, trunk_id=1 -> Eth-Trunk1 only.
        Prints the raw output, then a parsed summary.
        """
        cmd = "display eth-trunk" if trunk_id is None else f"display eth-trunk {trunk_id}"
        print(f"\n===== {cmd} =====")
        output = self.run_show(cmd)
        print(output)

        trunks = HuaweiRouter.parse_eth_trunk(output)
        print("\n----- Eth-Trunk summary -----")
        if not trunks:
            print("No Eth-Trunk found (or output could not be parsed).")
        for t in trunks:
            print(f"{t['name']}: status={t['status']}, "
                  f"up ports={t['up_ports']}, members={len(t['members'])}")
            for port, state in t["members"]:
                flag = "" if state.lower() == "up" else "   <-- CHECK THIS PORT"
                print(f"    {port:<28} {state}{flag}")
        return trunks

    def check_eth_trunk_config(self):
        """Show only the Eth-Trunk related lines of the running config."""
        cmd = "display current-configuration | include eth-trunk"
        print(f"\n===== {cmd} =====")
        output = self.run_show(cmd)
        print(output)
        return output

    # ------------------------------------------------------------------
    # CHECK 3 : Interfaces
    # ------------------------------------------------------------------
    def check_interfaces(self):
        """Interface brief status plus a list of any that are down."""
        print("\n===== display interface brief =====")
        output = self.run_show("display interface brief")
        print(output)

        interfaces = HuaweiRouter.parse_interface_brief(output)
        down = [i for i in interfaces if i["phy"].lower().lstrip("*^") == "down"]
        print("\n----- Interface summary -----")
        print(f"Total: {len(interfaces)} | Up: {len(interfaces) - len(down)} "
              f"| Down: {len(down)}")
        for i in down:
            print(f"    DOWN: {i['name']} (phy={i['phy']}, protocol={i['protocol']})")
        return interfaces

    def check_ip_interfaces(self):
        """Interface IP addresses and status."""
        cmd = "display ip interface brief"
        print(f"\n===== {cmd} =====")
        output = self.run_show(cmd)
        print(output)
        return output

    def check_interface(self, name):
        """Detailed view of one interface, e.g. GigabitEthernet0/0/1."""
        cmd = f"display interface {name}"
        print(f"\n===== {cmd} =====")
        output = self.run_show(cmd)
        print(output)
        return output

    def check_all(self):
        """Run every check in order."""
        self.check_current_config()
        self.check_eth_trunk()
        self.check_eth_trunk_config()
        self.check_interfaces()
        self.check_ip_interfaces()

    # ================= STATIC PARSERS =================
    @staticmethod
    def parse_eth_trunk(text):
        """Turn 'display eth-trunk' output into a list of dicts."""
        trunks = []
        # split into one block per trunk
        blocks = re.split(r"(?=Eth-Trunk\d+'s state information)", text)
        for block in blocks:
            m = re.match(r"(Eth-Trunk\d+)'s state information", block)
            if not m:
                continue
            status = re.search(r"Operate status:\s*(\S+)", block)
            up_ports = re.search(r"Number Of Up Port In Trunk:\s*(\d+)", block)
            members = re.findall(
                r"^(\S+)\s+(Up|Down|Selected|Unselected)\s+\d+", block,
                re.MULTILINE | re.IGNORECASE,
            )
            trunks.append({
                "name": m.group(1),
                "status": status.group(1) if status else "unknown",
                "up_ports": int(up_ports.group(1)) if up_ports else 0,
                "members": members,
            })
        return trunks

    @staticmethod
    def parse_interface_brief(text):
        """Turn 'display interface brief' output into a list of dicts."""
        interfaces = []
        for line in text.splitlines():
            m = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+[\d.]+%", line.strip())
            if m:
                interfaces.append({
                    "name": m.group(1),
                    "phy": m.group(2),
                    "protocol": m.group(3),
                })
        return interfaces


# ======================================================================
# RUNNER
# ======================================================================
MENU = """
==== Huawei Router Checks ====
 1) Display current configuration
 2) Check Eth-Trunk (bundle ports)
 3) Check interfaces (brief + down list)
 4) Check one interface in detail
 5) Check interface IP addresses
 6) Run ALL checks
 7) Backup configuration to file
 0) Exit
"""


def main():
    device = {
        "device_type": "huawei_vrpv8",
        "host": "192.168.74.215",
        "port": 22,
        "username": "ovi123",
        "password": getpass("Password: "),
        "conn_timeout": 15,
        "session_log": "netmiko_session.log",
    }

    router = HuaweiRouter(device)

    if not router.connect():
        return

    try:
        while True:
            print(MENU)
            choice = input("Choose: ").strip()
            if choice == "1":
                router.check_current_config()
            elif choice == "2":
                tid = input("Trunk ID (Enter = all): ").strip()
                router.check_eth_trunk(int(tid) if tid.isdigit() else None)
            elif choice == "3":
                router.check_interfaces()
            elif choice == "4":
                name = input("Interface name (e.g. GigabitEthernet0/0/1): ").strip()
                if name:
                    router.check_interface(name)
            elif choice == "5":
                router.check_ip_interfaces()
            elif choice == "6":
                router.check_all()
            elif choice == "7":
                router.backup_config()
            elif choice == "0":
                break
            else:
                print("Invalid choice.")
    finally:
        router.disconnect()


if __name__ == "__main__":
    main()