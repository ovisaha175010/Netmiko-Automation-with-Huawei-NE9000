#**kwargs (variable keyword arguments)

import time
from getpass import getpass
from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


def build_device(**kwargs) -> dict:
    """Build a Netmiko device dict. Defaults can be overridden via **kwargs."""
    device = {
        "device_type": "huawei_vrpv8",
        "port": 22,
        "conn_timeout": 15,
    }
    device.update(kwargs)          # host, username, password, fast_cli, etc.
    return device


def run_commands(device: dict, *commands: str, **cmd_kwargs) -> dict:
    """
    Connect to a device and run commands.

    device      : dict of ConnectHandler arguments (unpacked with **device)
    *commands   : one or more CLI commands
    **cmd_kwargs: forwarded to conn.send_command()
                  e.g. read_timeout=120, strip_prompt=False, delay_factor=2
    """
    cmd_kwargs.setdefault("read_timeout", 60)   # default, overridable by caller

    results, timings = {}, {}
    t_start = time.perf_counter()
    try:
        with ConnectHandler(**device) as conn:
            timings["connect"] = time.perf_counter() - t_start
            prompt = conn.find_prompt()          # e.g. <PE_1>

            for cmd in commands:
                t_cmd = time.perf_counter()
                out = conn.send_command(cmd, **cmd_kwargs)
                timings[cmd] = time.perf_counter() - t_cmd
                results[cmd] = out

                print(f"{prompt} {cmd}")
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
    device = build_device(
        host="192.168.74.215",
        username="ovi123",
        password=getpass("Password: "),
    )

    cmds = [
        "display ip interface brief",
        "display version",
        "display current-configuration",
        "display ip routing-table",
        "display bgp peer",
    ]

    # Extra keyword args go straight to send_command()
    run_commands(device, *cmds, read_timeout=90)

