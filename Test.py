"""
Python for Network Engineers - Chapter 16: Error Handling
Sections 16.9 to 16.18 (all examples in one file)

Install dependencies:
    pip install netmiko ncclient requests

Edit the DEVICE / URL values below before running the real examples.
Each section is a function, so you can run just one from the bottom of the file.
"""

import logging
import time
from functools import wraps

# Third-party libraries are imported safely: if one is missing, only the
# examples that need it are skipped, with a message telling you what to install.
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    requests = None
    HAS_REQUESTS = False

try:
    from ncclient import manager
    from ncclient.operations import RPCError
    HAS_NCCLIENT = True
except ImportError:
    manager = None
    HAS_NCCLIENT = False

    class RPCError(Exception):
        """Placeholder so the except clauses still work without ncclient."""

try:
    from netmiko import ConnectHandler
    try:
        from netmiko.exceptions import (
            NetmikoAuthenticationException as NetMikoAuthenticationException,
            NetmikoTimeoutException as NetMikoTimeoutException,
        )
    except ImportError:  # older Netmiko versions
        from netmiko.ssh_exception import (
            NetMikoAuthenticationException,
            NetMikoTimeoutException,
        )
    from paramiko.ssh_exception import SSHException
    HAS_NETMIKO = True
except ImportError:
    ConnectHandler = None
    HAS_NETMIKO = False

    class NetMikoTimeoutException(Exception):
        """Placeholder so the except clauses still work without netmiko."""

    class NetMikoAuthenticationException(Exception):
        """Placeholder so the except clauses still work without netmiko."""

    class SSHException(Exception):
        """Placeholder so the except clauses still work without netmiko."""


def _need(available, package):
    """Return True if the library is installed, else print how to install it."""
    if not available:
        print(f"Skipped: '{package}' is not installed. Run: pip install {package}")
    return available

# ---------------------------------------------------------------------------
# Shared settings (change these)
# ---------------------------------------------------------------------------
DEVICE = {
    "device_type": "huawei_vrpv8",
    "host": "192.168.74.215",  # Ethernet1/0/0 management IP (1.11.11.22 is the LoopBack0 IP)
    "port": 22,
    "username": "ovi123",
    "password": "Test@123",
    "conn_timeout": 60,
}

RESTCONF_URL = "https://10.1.1.1/restconf/data/ietf-interfaces:interfaces"
RESTCONF_AUTH = ("admin", "admin123")
RESTCONF_HEADERS = {"Accept": "application/yang-data+json"}

NETCONF_PARAMS = {
    "host": "192.168.74.215",  # Ethernet1/0/0 management IP
    "port": 830,
    "username": "ovi123",  # needs "snetconf" service-type on the device (see notes)
    "password": "Test@123",
    "hostkey_verify": False,
    "device_params": {"name": "huawei"},  # Huawei VRP NETCONF handler
    "look_for_keys": False,
    "allow_agent": False,
    "timeout": 30,
}


# ---------------------------------------------------------------------------
# 16.9 - Netmiko Error Handling
# ---------------------------------------------------------------------------
def netmiko_error_handling():
    if not _need(HAS_NETMIKO, "netmiko"):
        return
    try:
        conn = ConnectHandler(**DEVICE)
        print(conn.send_command("display version"))
        conn.disconnect()
    except NetMikoTimeoutException:
        print("Timeout: Device unreachable")
    except NetMikoAuthenticationException:
        print("Authentication failed")
    except SSHException as e:
        # General SSH failure or algorithm mismatch
        print(f"SSH error: {e}")
    except Exception as e:
        print(f"General error: {e}")


# ---------------------------------------------------------------------------
# 16.10 - RESTCONF Error Handling
# ---------------------------------------------------------------------------
def restconf_error_handling(url=RESTCONF_URL):
    if not _need(HAS_REQUESTS, "requests"):
        return
    try:
        r = requests.get(
            url,
            auth=RESTCONF_AUTH,
            headers=RESTCONF_HEADERS,
            verify=False,  # lab only; use valid certificates in production
            timeout=5,
        )
        r.raise_for_status()  # raises HTTPError for 401, 404, 500, etc.
        print(r.json())
    except requests.exceptions.Timeout:
        print("RESTCONF server timeout")
    except requests.exceptions.SSLError as e:
        print("SSL certificate error:", e)
    except requests.exceptions.InvalidURL as e:
        print("Invalid URL:", e)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            print("Unauthorized (401): check username/password")
        else:
            print("HTTP error:", e)
    except requests.exceptions.ConnectionError:
        print("Connection failed")


# ---------------------------------------------------------------------------
# 16.11 - NETCONF Error Handling
# ---------------------------------------------------------------------------
def netconf_error_handling():
    if not _need(HAS_NCCLIENT, "ncclient"):
        return
    try:
        with manager.connect(**NETCONF_PARAMS) as conn:
            result = conn.get_config(source="running")
            print(result.xml[:500])
    except RPCError as e:
        print("NETCONF RPC error:", e)
    except Exception as e:
        print("General NETCONF error:", e)


# ---------------------------------------------------------------------------
# 16.13 - Logging Errors to a File
# ---------------------------------------------------------------------------
logging.basicConfig(
    filename="error.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)


def logging_errors():
    try:
        10 / 0
    except Exception as e:
        logging.error(f"Error: {e}")
        print("Error written to error.log")


# ---------------------------------------------------------------------------
# 16.14 - Raising Your Own Error
# ---------------------------------------------------------------------------
def check_ip(ip):
    if not ip.startswith("10."):
        raise ValueError("Invalid IP range")
    return True


def raise_own_error():
    try:
        check_ip("172.16.1.1")
    except ValueError as e:
        print("Caught:", e)


# ---------------------------------------------------------------------------
# 16.15 - Retry Logic
# ---------------------------------------------------------------------------
def retry(func, attempts=3, delay=2):
    """Call func() up to `attempts` times, waiting `delay` seconds between tries."""
    for i in range(1, attempts + 1):
        try:
            return func()
        except Exception as e:
            print(f"Attempt {i}/{attempts} failed: {e}")
            time.sleep(delay)
    print("Failed after retries")
    return None


def retry_decorator(attempts=3, delay=2):
    """Same idea as a decorator, so you can wrap any function once."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    print(f"{func.__name__}: attempt {i}/{attempts} failed: {e}")
                    time.sleep(delay)
            print(f"{func.__name__}: failed after retries")
            return None
        return wrapper
    return decorator


@retry_decorator(attempts=3, delay=2)
def get_version():
    with ConnectHandler(**DEVICE) as conn:
        return conn.send_command("display version")


def retry_demo():
    if not _need(HAS_NETMIKO, "netmiko"):
        return

    def run_show_version():
        with ConnectHandler(**DEVICE) as conn:
            return conn.send_command("display version")

    print(retry(run_show_version, attempts=3))
    print(get_version())


# ---------------------------------------------------------------------------
# 16.16 - Network Example: Retry SSH Until Device Reboots
# ---------------------------------------------------------------------------
def retry_ssh_until_reboot(max_tries=5, wait=10):
    if not _need(HAS_NETMIKO, "netmiko"):
        return None
    conn = None
    for attempt in range(1, max_tries + 1):
        try:
            conn = ConnectHandler(**DEVICE)
            print("Device is back online")
            break
        except (NetMikoTimeoutException, SSHException, OSError):
            print(f"Attempt {attempt}/{max_tries}: retrying in {wait} seconds...")
            time.sleep(wait)
    else:
        print("Device did not come back in time")
        return None
    return conn


# ---------------------------------------------------------------------------
# 16.18 - Best Practices (all combined)
#   - catch specific exceptions
#   - try/except around network calls
#   - log errors to a file
#   - retry transient failures
#   - one bad device never crashes the whole script
#   - finally block closes sessions
# ---------------------------------------------------------------------------
def best_practice_run(devices, command="display version", retries=2):
    if not _need(HAS_NETMIKO, "netmiko"):
        return {}
    results = {}

    for dev in devices:
        host = dev["host"]
        conn = None
        try:
            for attempt in range(1, retries + 1):
                try:
                    conn = ConnectHandler(**dev)
                    break
                except NetMikoTimeoutException:
                    logging.error(f"{host}: timeout (attempt {attempt})")
                    time.sleep(3)
            if conn is None:
                results[host] = "FAILED: unreachable"
                continue

            results[host] = conn.send_command(command)

        except NetMikoAuthenticationException:
            logging.error(f"{host}: authentication failed")
            results[host] = "FAILED: authentication"
        except SSHException as e:
            logging.error(f"{host}: SSH error: {e}")
            results[host] = "FAILED: ssh"
        except Exception as e:
            logging.error(f"{host}: unexpected error: {e}")
            results[host] = f"FAILED: {e}"
        finally:
            if conn is not None:
                conn.disconnect()  # always close the session

    return results


if __name__ == "__main__":
    # Safe demos that need no network device:
    logging_errors()
    raise_own_error()

    # Tests against your device (1.11.11.22):
    print("\n--- Netmiko (SSH) test ---")
    netmiko_error_handling()

    print("\n--- NETCONF test ---")
    netconf_error_handling()

    # Uncomment the others if you want to test them too:
    # restconf_error_handling()
    # retry_demo()
    # retry_ssh_until_reboot()
    # print(best_practice_run([DEVICE, {**DEVICE, "host": "10.1.1.2"}]))
