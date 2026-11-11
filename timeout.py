
import time
from getpass import getpass

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


def run_commands(device: dict, *commands: str) -> dict:
    results = {}
    t0 = time.perf_counter()
    try:
        with ConnectHandler(**device) as conn:
            print(f"Connect time: {time.perf_counter() - t0:.2f}s")
            for cmd in commands:
                t1 = time.perf_counter()
                out = conn.send_command(cmd)
                print(f"\n===== {cmd} ({time.perf_counter() - t1:.2f}s) =====")
                print(out)
                results[cmd] = out
    except NetmikoTimeoutException:
        print(f"Timeout connecting to {device['host']}")
    except NetmikoAuthenticationException:
        print(f"Authentication failed on {device['host']}")
    print(f"\nTotal: {time.perf_counter() - t0:.2f}s")
    return results


device = {
    "device_type": "huawei",
    "host": "1.11.11.22",        # use your device's real IP
    "username": "ovi123",
    "password": getpass("Password: "),
}

run_commands(device, "dis ip int brief", "dis version", "dis curr-config")
