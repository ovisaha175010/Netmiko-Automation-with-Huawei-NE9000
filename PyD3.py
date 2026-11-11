# *args (variable positional arguments)#


import time
from getpass import getpass

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


def run_commands(device: dict, *commands: str) -> dict:
    results, timings = {}, {}
    t_start = time.perf_counter()
    try:
        with ConnectHandler(**device) as conn:
            timings["connect"] = time.perf_counter() - t_start
            prompt = conn.find_prompt()              # e.g. <PE_1>

            for cmd in commands:
                t_cmd = time.perf_counter()
                out = conn.send_command(cmd, read_timeout=60)
                timings[cmd] = time.perf_counter() - t_cmd
                results[cmd] = out

                print(f"{prompt} {cmd}")             # <PE_1> display ip interface brief
                print(out)
                print()
    except NetmikoTimeoutException:
        print(f"Timeout connecting to {device['host']} "
              f"after {time.perf_counter() - t_start:.2f}s")
    except NetmikoAuthenticationException:
        print(f"Authentication failed on {device['host']}")

    print("-" * 50)
    print(f"{'Step':<35}{'Time (s)':>10}")
    print("-" * 50)
    for name, secs in timings.items():
        print(f"{name:<35}{secs:>10.2f}")
    print(f"{'TOTAL':<35}{time.perf_counter() - t_start:>10.2f}")
    return results


if __name__ == "__main__":
    device = {
        "device_type": "huawei_vrpv8",
        "host": "192.168.74.215",       # see note below
        "port": 22,
        "username": "ovi123",
        "password": getpass("Password: "),
        "conn_timeout": 15,
    }

    cmds = [
        "display ip interface brief",
        "display version",
        "display current-configuration",
        "display ip routing-table",
        "display bgp peer",
    ]
    run_commands(device, *cmds)