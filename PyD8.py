"""
Huawei Router Automation - Full OOP version
===========================================
Target : Huawei VRP router (device_type = huawei_vrpv8)
Needs  : pip install netmiko

OOP concepts and where they appear
----------------------------------
 1. ENCAPSULATION      public (host), protected (_conn), private (__password)
 2. GETTER / SETTER    @property + @setter on hostname, host, port, password
 3. INHERITANCE        NetworkDevice -> Router -> HuaweiRouter
 4. METHOD OVERRIDING  show_run_command(), get_version_command(), describe()
 5. super()            HuaweiRouter.__init__, HuaweiRouter.connect, describe
 6. POLYMORPHISM       run_checks(devices) calls the same methods on any device
 7. MULTIPLE INHERIT.  HuaweiRouter(LoggingMixin, SNMPMixin, SSHMixin, Router)
 8. ABSTRACT CLASSES   NetworkDevice(ABC) with @abstractmethod
"""

import ipaddress
import re
from abc import ABC, abstractmethod
from datetime import datetime
from getpass import getpass

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


# ======================================================================
# MIXINS  (small reusable abilities, combined with multiple inheritance)
# ======================================================================
class LoggingMixin:
    """Adds timestamped logging to any class, and saves it to a file."""

    log_file = "automation.log"            # static variable

    def log(self, message, level="INFO"):
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{level}] {message}"
        print(line)
        with open(self.log_file, "a") as f:
            f.write(line + "\n")


class SSHMixin:
    """Adds SSH connection handling through Netmiko."""

    BANNER_HELP = (
        "The router accepted the TCP connection on the SSH port but closed it "
        "before the SSH handshake. On the router (console) check:\n"
        "   display users                      (are all VTY lines busy?)\n"
        "   display ssh server status          (is stelnet server enabled?)\n"
        "   display current-configuration configuration user-interface\n"
        "       -> needs: authentication-mode aaa, protocol inbound ssh,\n"
        "          and no 'acl' that blocks your PC address\n"
        "   display rsa local-key-pair public  (SSH needs an RSA/ECDSA key)")

    def ssh_connect(self, device_params, retries=3, delay=5):
        import time
        # Give a slow router more time for the banner and login
        params = dict(device_params)
        params.setdefault("banner_timeout", 30)
        params.setdefault("auth_timeout", 30)

        for attempt in range(1, retries + 1):
            try:
                self._conn = ConnectHandler(**params)          # protected
                return True
            except NetmikoAuthenticationException:
                self.log("Authentication failed - wrong username/password, or "
                         "the user has no SSH service-type", "ERROR")
                return False                  # retrying would not help
            except NetmikoTimeoutException as e:
                text = str(e)
                if "banner" in text.lower() or "reset" in text.lower():
                    self.log(f"Attempt {attempt}/{retries}: router reset the "
                             f"connection before the SSH banner", "ERROR")
                else:
                    self.log(f"Attempt {attempt}/{retries}: timeout - check IP, "
                             f"routing and firewall", "ERROR")
            except Exception as e:
                self.log(f"Attempt {attempt}/{retries}: SSH error: {e}", "ERROR")

            if attempt < retries:
                self.log(f"Retrying in {delay} seconds...")
                time.sleep(delay)

        self.log("Could not connect.\n" + self.BANNER_HELP, "ERROR")
        return False

    def ssh_disconnect(self):
        if self._conn is not None:
            self._conn.disconnect()
            self._conn = None

    def ssh_send(self, command):
        return self._conn.send_command(command)

    def ssh_send_config(self, commands):
        return self._conn.send_config_set(commands)


# ======================================================================
# ABSTRACT CLASS  (a blueprint: cannot be created directly)
# ======================================================================
class NetworkDevice(ABC):
    # ---- STATIC (CLASS) VARIABLE ----
    total_devices = 0

    def __init__(self, hostname, host, port, username, password):
        # PUBLIC attribute   : usable from anywhere
        self.username = username
        # PROTECTED attribute: single underscore, for this class + subclasses
        self._conn = None
        self._connected = False
        # PRIVATE attributes : double underscore, name-mangled, class-only
        self.__password = password
        self.__host = None
        self.__port = None
        self.__hostname = None

        # setters validate the values
        self.hostname = hostname
        self.host = host
        self.port = port

        NetworkDevice.total_devices += 1

    # ------------------ GETTERS and SETTERS ------------------
    @property
    def hostname(self):
        return self.__hostname

    @hostname.setter
    def hostname(self, value):
        if not value or not str(value).strip():
            raise ValueError("hostname cannot be empty")
        self.__hostname = str(value).strip()

    @property
    def host(self):
        return self.__host

    @host.setter
    def host(self, value):
        try:
            ipaddress.ip_address(value)
        except ValueError:
            raise ValueError(f"invalid IP address: {value}")
        self.__host = value

    @property
    def port(self):
        return self.__port

    @port.setter
    def port(self, value):
        if not (isinstance(value, int) and 1 <= value <= 65535):
            raise ValueError("port must be an integer between 1 and 65535")
        self.__port = value

    @property
    def password(self):
        return "********"            # getter hides the real password

    @password.setter
    def password(self, value):
        if len(value) < 1:
            raise ValueError("password cannot be empty")
        self.__password = value

    @property
    def connected(self):             # read-only: getter, no setter
        return self._connected

    # Protected helper: subclasses may use it, outsiders should not
    def _build_device_params(self, device_type, **extra):
        params = {
            "device_type": device_type,
            "host": self.__host,
            "port": self.__port,
            "username": self.username,
            "password": self.__password,
        }
        params.update(extra)
        return params

    # ------------------ ABSTRACT METHODS ------------------
    # Every child class MUST implement these, or Python refuses to create it.
    @abstractmethod
    def connect(self):
        ...

    @abstractmethod
    def disconnect(self):
        ...

    @abstractmethod
    def show_run_command(self):
        ...

    @abstractmethod
    def get_version_command(self):
        ...

    # ------------------ Normal (concrete) methods ------------------
    def describe(self):
        return f"{self.hostname} ({self.host}:{self.port})"

    @classmethod
    def get_total_devices(cls):
        return cls.total_devices

    @staticmethod
    def timestamp():
        return datetime.now().strftime("%Y%m%d_%H%M%S")


# ======================================================================
# INTERMEDIATE CLASS : generic Router
# ======================================================================
class Router(NetworkDevice):
    def __init__(self, hostname, host, port, username, password):
        super().__init__(hostname, host, port, username, password)
        self.role = "router"

    def describe(self):                                   # OVERRIDING
        return f"Router {super().describe()}"

    def get_version_command(self):
        return "show version"

    def show_run_command(self):
        return "show running-config"

    # connect/disconnect stay abstract here: still not instantiable
    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError


# ======================================================================
# CONCRETE CLASS : Huawei router (multiple inheritance + overriding)
# ======================================================================
class HuaweiRouter(LoggingMixin, SSHMixin, Router):
    DEVICE_TYPE = "huawei_vrpv8"

    def __init__(self, hostname, host, port, username, password,
                 conn_timeout=15, session_log="netmiko_session.log"):
        super().__init__(hostname, host, port, username, password)   # super()
        self.vendor = "huawei"
        self._conn_timeout = conn_timeout
        self._session_log = session_log

    # ---------- OVERRIDDEN methods ----------
    def describe(self):
        return f"Huawei VRP {super().describe()}"          # super()

    def show_run_command(self):
        return "display current-configuration"

    def get_version_command(self):
        return "display version"

    def connect(self):
        params = self._build_device_params(
            self.DEVICE_TYPE,
            conn_timeout=self._conn_timeout,
            session_log=self._session_log,
        )
        self.log(f"Connecting to {self.describe()}")
        if self.ssh_connect(params):
            self._connected = True
            self.log(f"Connected. Prompt: {self._conn.find_prompt()}")
            return True
        return False

    def disconnect(self):
        self.ssh_disconnect()
        self._connected = False
        self.log("Disconnected")

    # ---------- CHECKS ----------
    def check_version(self):
        out = self.ssh_send(self.get_version_command())
        print(f"\n===== {self.get_version_command()} =====\n{out}")
        return out

    def check_current_config(self, section=None):
        cmd = self.show_run_command()
        if section:
            cmd += f" interface {section}"
        out = self.ssh_send(cmd)
        print(f"\n===== {cmd} =====\n{out}")
        return out

    def check_eth_trunk(self, trunk_id=None):
        cmd = "display eth-trunk" + (f" {trunk_id}" if trunk_id is not None else "")
        out = self.ssh_send(cmd)
        print(f"\n===== {cmd} =====\n{out}")
        trunks = self.parse_eth_trunk(out)
        print("\n----- Eth-Trunk summary -----")
        if not trunks:
            print("No Eth-Trunk found (or output could not be parsed).")
        for t in trunks:
            print(f"{t['name']}: status={t['status']}, up ports={t['up_ports']}")
            for port, state in t["members"]:
                flag = "" if state.lower() == "up" else "   <-- CHECK THIS PORT"
                print(f"    {port:<28} {state}{flag}")
        return trunks

    def check_interfaces(self):
        out = self.ssh_send("display interface brief")
        print(f"\n===== display interface brief =====\n{out}")
        interfaces = self.parse_interface_brief(out)
        down = [i for i in interfaces if i["phy"].lower().lstrip("*^") == "down"]
        print("\n----- Interface summary -----")
        print(f"Total: {len(interfaces)} | Up: {len(interfaces) - len(down)} "
              f"| Down: {len(down)}")
        for i in down:
            print(f"    DOWN: {i['name']} (phy={i['phy']}, protocol={i['protocol']})")
        return interfaces

    def check_interface(self, name):
        out = self.ssh_send(f"display interface {name}")
        print(f"\n===== display interface {name} =====\n{out}")
        return out

    def backup_config(self):
        out = self.ssh_send(self.show_run_command())
        filename = f"{self.host}_{self.timestamp()}_backup.txt"
        with open(filename, "w") as f:
            f.write(out)
        self.log(f"Backup saved to {filename}")
        return filename

    def run_checks(self):
        """POLYMORPHISM target: every device type exposes the same method."""
        self.check_version()
        self.check_current_config()
        self.check_eth_trunk()
        self.check_interfaces()

    # ---------- PARSERS (static: no self needed) ----------
    @staticmethod
    def parse_eth_trunk(text):
        trunks = []
        for block in re.split(r"(?=Eth-Trunk\d+'s state information)", text):
            m = re.match(r"(Eth-Trunk\d+)'s state information", block)
            if not m:
                continue
            status = re.search(r"Operate status:\s*(\S+)", block)
            up_ports = re.search(r"Number Of Up Port In Trunk:\s*(\d+)", block)
            members = re.findall(
                r"^(\S+)\s+(Up|Down|Selected|Unselected)\s+\d+", block,
                re.MULTILINE | re.IGNORECASE)
            trunks.append({
                "name": m.group(1),
                "status": status.group(1) if status else "unknown",
                "up_ports": int(up_ports.group(1)) if up_ports else 0,
                "members": members,
            })
        return trunks

    @staticmethod
    def parse_interface_brief(text):
        interfaces = []
        for line in text.splitlines():
            m = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+[\d.]+%", line.strip())
            if m:
                interfaces.append({"name": m.group(1), "phy": m.group(2),
                                   "protocol": m.group(3)})
        return interfaces


# ======================================================================
# POLYMORPHISM DEMO : one function, any kind of device
# ======================================================================
def audit(devices):
    """Works with ANY NetworkDevice subclass. Each one answers in its own way."""
    for dev in devices:
        print(f"\n########## {dev.describe()} ##########")
        print(f"Version command : {dev.get_version_command()}")
        print(f"Config command  : {dev.show_run_command()}")


# ======================================================================
# RUNNER
# ======================================================================
MENU = """
==== Huawei Router Automation ====
 1) Version
 2) Display current configuration
 3) Check Eth-Trunk (bundle ports)
 4) Check interfaces (brief + down list)
 5) Check one interface in detail
 6) Run ALL checks
 7) Backup configuration
 8) Show encapsulation demo
 0) Exit
"""


def encapsulation_demo(router):
    print("\n--- Encapsulation demo ---")
    print("public    username :", router.username)
    print("protected _conn    :", router._conn is not None, "(works, but discouraged)")
    print("password (getter)  :", router.password)
    try:
        router.port = 99999
    except ValueError as e:
        print("setter rejected bad port:", e)
    try:
        print(router.__password)                    # private, hidden
    except AttributeError:
        print("private __password is not directly accessible")


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

    # Abstract class cannot be instantiated:
    try:
        NetworkDevice("x", "1.1.1.1", 22, "u", "p")
    except TypeError as e:
        print("Abstract class check:", e)

    router = HuaweiRouter(
        hostname="HUAWEI-R1",
        host=device["host"],
        port=device["port"],
        username=device["username"],
        password=device["password"],
        conn_timeout=device["conn_timeout"],
        session_log=device["session_log"],
    )
    print("Devices created:", NetworkDevice.get_total_devices())
    audit([router])                                  # polymorphism

    if not router.connect():
        return
    try:
        while True:
            print(MENU)
            choice = input("Choose: ").strip()
            if choice == "1":
                router.check_version()
            elif choice == "2":
                router.check_current_config()
            elif choice == "3":
                tid = input("Trunk ID (Enter = all): ").strip()
                router.check_eth_trunk(int(tid) if tid.isdigit() else None)
            elif choice == "4":
                router.check_interfaces()
            elif choice == "5":
                name = input("Interface (e.g. GigabitEthernet0/0/1): ").strip()
                if name:
                    router.check_interface(name)
            elif choice == "6":
                router.run_checks()
            elif choice == "7":
                router.backup_config()
            elif choice == "8":
                encapsulation_demo(router)
            elif choice == "0":
                break
            else:
                print("Invalid choice.")
    finally:
        router.disconnect()


if __name__ == "__main__":
    main()

    #==============================================================================


    """
SSH diagnostic for a Huawei router
==================================
Run this FIRST when the automation script cannot connect.
It needs no password for steps 1-3 and tells you where the problem is.

Usage:  python ssh_diagnose.py 192.168.74.215
        python ssh_diagnose.py 192.168.74.215 --user ovi123 --port 22
"""

import argparse
import socket
import time
from getpass import getpass


def source_address(host, port):
    """The local IP this computer would use to reach the router."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((host, port))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError as e:
        return f"unknown ({e})"


def read_banner(host, port, timeout=8):
    """Return (state, detail): ok / reset / silent / refused / unreachable."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
    except ConnectionRefusedError:
        return "refused", "port closed: SSH server is not listening"
    except socket.timeout:
        return "unreachable", "no reply: wrong IP, no route, or firewall drops it"
    except OSError as e:
        return "unreachable", str(e)
    try:
        s.settimeout(timeout)
        data = s.recv(256)
        if not data:
            return "reset", "connection closed with no banner"
        text = data.decode(errors="replace").strip()
        if text.startswith("SSH-"):
            return "ok", text
        return "other", f"not an SSH banner: {text[:60]!r}"
    except ConnectionResetError:
        return "reset", "connection reset by the other side before any banner"
    except socket.timeout:
        return "silent", "connected but the server sent nothing"
    finally:
        s.close()


def try_login(host, port, user, password):
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=port, username=user, password=password,
                       timeout=15, banner_timeout=30, auth_timeout=30,
                       look_for_keys=False, allow_agent=False)
        return [("SSH login", "LOGIN OK")]
    except paramiko.AuthenticationException:
        return [("SSH login", "reached the router, but username/password "
                              "rejected (or user lacks SSH service-type)")]
    except Exception as e:
        return [("SSH login", f"failed: {e}")]
    finally:
        client.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--user", default="")
    args = ap.parse_args()

    print(f"\n[1] Source address")
    src = source_address(args.host, args.port)
    print(f"    This computer reaches {args.host} from: {src}")
    print("    -> It should be in the same network as the router "
          "(or have a route to it).")

    print(f"\n[2] Other management ports")
    for p, name in ((23, "Telnet"), (443, "HTTPS"), (830, "NETCONF")):
        try:
            socket.create_connection((args.host, p), timeout=3).close()
            print(f"    {p:<4} {name:<8} open")
        except OSError:
            print(f"    {p:<4} {name:<8} closed/filtered")

    print(f"\n[3] SSH banner test on port {args.port} (5 tries)")
    states = []
    for i in range(1, 6):
        state, detail = read_banner(args.host, args.port)
        states.append(state)
        print(f"    try {i}: {state:<12} {detail}")
        time.sleep(2)

    print("\n[Verdict]")
    if all(s == "ok" for s in states):
        print("    SSH server is answering normally.")
    elif all(s == "reset" for s in states):
        print("    The router (or a device in between) resets every SSH "
              "connection.\n"
              "    Most common causes:\n"
              "      a) all VTY lines busy:      display users\n"
              "      b) VTY blocks SSH or your IP (acl): "
              "display current-configuration configuration user-interface\n"
              "      c) SSH server disabled/no key: display ssh server status\n"
              "      d) this computer is NOT on the router's network (VM/WSL/"
              "cloud/VPN)\n"
              "         and a firewall or proxy resets the connection:\n"
              "         compare [1] with the router's subnet.")
    elif "refused" in states:
        print("    Nothing listens on that port: enable SSH "
              "(stelnet server enable) or use the right port.")
    elif "unreachable" in states:
        print("    The router cannot be reached from this computer. Check the "
              "IP, cable/VM network mode, routing and firewall.")
    elif "ok" in states:
        print("    Intermittent: sometimes works, sometimes reset. This usually "
              "means the VTY lines are nearly full or a connection-rate limit "
              "is active on the router.")
    else:
        print("    Unclear result; send this output to your instructor/admin.")

    if "ok" in states and args.user:
        print(f"\n[4] Login test as {args.user}")
        for label, outcome in try_login(args.host, args.port, args.user,
                                        getpass("Password: ")):
            print(f"    {label}: {outcome}")


if __name__ == "__main__":
    main()