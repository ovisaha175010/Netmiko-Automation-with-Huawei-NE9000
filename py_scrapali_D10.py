
"""
Python for Network Engineers - Chapter 18: Scrapli
All Scrapli examples, written for a Huawei VRP router.

Install inside your venv (versions matter!):
    pip install "scrapli==2025.1.30" "scrapli-community==2025.1.30" paramiko
    pip install asyncssh                  # only for the async example (18.12)
    pip install textfsm ntc-templates     # only for the parsing example (18.13)

Why pin the versions?
  - Huawei is not a built-in Scrapli platform; it comes from scrapli-community
    (platform name: "huawei_vrp").
  - Scrapli 2026.x was rewritten and no longer has Scrapli(...), so the API used
    in the course notes needs the 2025.1.30 release.

Each section is a function. The ones that change the router (config / save)
are NOT run by default: uncomment them at the bottom of the file.
"""

import asyncio
import logging
import re
import socket
import time
from functools import wraps

try:
    from scrapli import AsyncScrapli, Scrapli
    from scrapli.exceptions import (
        ScrapliAuthenticationFailed,
        ScrapliConnectionError,
        ScrapliConnectionNotOpened,
        ScrapliException,
        ScrapliTimeout,
    )
except ImportError:
    raise SystemExit(
        "Scrapli (classic API) is not installed. Run:\n"
        '  pip install "scrapli==2025.1.30" "scrapli-community==2025.1.30" paramiko'
    )

# ---------------------------------------------------------------------------
# Logging (18.17: "log response metadata")
# ---------------------------------------------------------------------------
logging.basicConfig(
    filename="scrapli.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ---------------------------------------------------------------------------
# Your device
# ---------------------------------------------------------------------------
# One place to change the router address for every example:
#   "192.168.74.215" = Ethernet1/0/0 management IP (works now)
#   "1.11.11.22"     = LoopBack0 IP (only after the VM has a route to it)
ROUTER_IP = "1.11.11.22"
MGMT_IP = "1.11.11.22"  # router Ethernet1/0/0, used as next hop in the route hint

DEVICE = {
    "device_type": "huawei_vrpv8",
    "host": ROUTER_IP,
    "port": 22,
    "username": "ovi123",
    "password": "Test@123",
    "conn_timeout": 60,
}

# Add more routers here for the multi-device examples (18.11 / 18.12):
DEVICES = [DEVICE]
# DEVICES = [DEVICE, {**DEVICE, "host": "192.168.74.216"}]


PASSWORD_PROMPT = b"[y/n]"  # "The password needs to be changed. Change now? [Y/N]:"
PROMPT_RE = re.compile(rb"<[^>\s]+>\s*$")  # normal Huawei prompt, for example <R1>
WAIT_AFTER_LOGIN = 4  # seconds to wait for the router's first message


def answer_password_prompt(conn):
    """Answer N to 'The initial password poses security risks... Change now? [Y/N]'.

    Huawei routers ask this right after login while the account still has its
    initial password. Scrapli waits for a normal <R1> prompt, never sees one,
    and times out (shown as "encountered EOF reading from transport").
    Netmiko answers this question automatically; here we do the same.
    """
    chan = conn.transport.session_channel  # the paramiko channel
    seen = b""
    end = time.time() + WAIT_AFTER_LOGIN
    while time.time() < end:
        if chan.recv_ready():
            seen += chan.recv(65535)
            if PASSWORD_PROMPT in seen.lower():
                logging.info("%s: password-change question answered with N", conn.host)
                conn.channel.write(channel_input="n")
                conn.channel.send_return()
                return True
            if PROMPT_RE.search(seen):
                return False  # already at the normal prompt
        elif chan.closed or chan.eof_received:
            return False
        else:
            time.sleep(0.1)
    return False


async def async_answer_password_prompt(conn):
    """Same as answer_password_prompt, for the async (asyncssh) transport."""
    seen = b""
    end = time.time() + WAIT_AFTER_LOGIN
    while time.time() < end:
        try:
            seen += await asyncio.wait_for(
                conn.channel.read(), timeout=max(0.1, end - time.time())
            )
        except (asyncio.TimeoutError, ScrapliException):
            return False
        if PASSWORD_PROMPT in seen.lower():
            logging.info("%s: password-change question answered with N", conn.host)
            conn.channel.write(channel_input="n")
            conn.channel.send_return()
            return True
        if PROMPT_RE.search(seen):
            return False
    return False


def safe_on_open(conn):
    """What Scrapli runs right after login.

    1. Answer the 'Change password now? [Y/N]' question with N (if it appears).
    2. Turn paging off.

    The community Huawei driver also sends 'screen-width 256' followed by 'y'.
    Some AR / eNSP versions do not accept that, so it is left out here (the
    same thing Netmiko's Huawei driver does).
    """
    answer_password_prompt(conn)
    conn.acquire_priv(desired_priv=conn.default_desired_privilege_level)
    conn.send_command(command="screen-length 0 temporary")


async def async_safe_on_open(conn):
    """Async version of safe_on_open."""
    await async_answer_password_prompt(conn)
    await conn.acquire_priv(desired_priv=conn.default_desired_privilege_level)
    await conn.send_command(command="screen-length 0 temporary")


def scrapli_args(dev=DEVICE, transport="paramiko"):
    """Convert the DEVICE dictionary into Scrapli arguments.

    Netmiko says device_type; Scrapli says platform (key difference from 18.5).
    paramiko is used because it is already installed with Netmiko and it is the
    same SSH library that already logs in to your router successfully.
    """
    return {
        "host": dev["host"],
        "port": dev["port"],
        "auth_username": dev["username"],
        "auth_password": dev["password"],
        "auth_strict_key": False,
        "platform": "huawei_vrp",
        "transport": transport,
        "timeout_socket": 15,
        "timeout_transport": dev["conn_timeout"],
        "timeout_ops": 30,
        "on_open": async_safe_on_open if transport == "asyncssh" else safe_on_open,
    }


# ---------------------------------------------------------------------------
# Diagnosis: shows what the router itself says before it closes the session
# ---------------------------------------------------------------------------
_DIAGNOSED = False


def _read_channel(chan, wait=2.0):
    end = time.time() + wait
    data = b""
    while time.time() < end:
        if chan.recv_ready():
            data += chan.recv(65535)
        elif chan.closed or chan.eof_received:
            break
        else:
            time.sleep(0.1)
    return data.decode(errors="replace").strip()


def diagnose_session(dev=DEVICE):
    """Log in with plain paramiko and replay the steps Scrapli does after login."""
    try:
        import paramiko
    except ImportError:
        print("paramiko is not installed: pip install paramiko")
        return

    print("\n=== Diagnosis: what does the router do after login? ===")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            dev["host"],
            port=dev["port"],
            username=dev["username"],
            password=dev["password"],
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            banner_timeout=30,
            auth_timeout=30,
        )
        print("1. SSH login: OK")
        chan = client.invoke_shell(width=200, height=50)
        greeting = _read_channel(chan, 3)
        print("2. Router greeting / prompt:", repr(greeting) if greeting else "(nothing)")
        if chan.closed or chan.eof_received:
            print("   -> The router closed the session right after login.")
            print("   Check on the router: 'display users' (are all VTY lines used?) and")
            print("   'display local-user' (is ovi123 in state Block?).")
            return

        for label, text in (
            ("3. screen-length 0 temporary", "screen-length 0 temporary\n"),
            ("4. screen-width 256 + y (sent by the community driver)", "screen-width 256\ny\n\n"),
        ):
            chan.send(text)
            reply = _read_channel(chan, 2)
            state = "session CLOSED" if (chan.closed or chan.eof_received) else "session still open"
            print(f"{label}: {state}")
            print("   router reply:", repr(reply[:300]) if reply else "(nothing)")
            if chan.closed or chan.eof_received:
                break
    except paramiko.AuthenticationException:
        print("1. SSH login FAILED: wrong password, or ovi123 is blocked "
              "(3 failed logins block it for 5 minutes).")
    except Exception as e:
        print(f"Diagnosis stopped: {type(e).__name__}: {e}")
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Error handling (specific Scrapli exceptions, never a crash)
# ---------------------------------------------------------------------------
def scrapli_safe(func):
    """Wrap an example so connection problems print a clear message."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ScrapliAuthenticationFailed:
            print("Authentication failed: check username/password "
                  "(the account blocks for 5 minutes after 3 failures)")
        except ScrapliConnectionNotOpened as e:
            print(f"Could not open the connection: {e}")
        except ScrapliTimeout:
            print("Timeout: device unreachable or too slow")
        except ScrapliConnectionError as e:
            print(f"Connection error: {e}")
            global _DIAGNOSED
            if "EOF" in str(e) and not _DIAGNOSED:
                _DIAGNOSED = True  # run the diagnosis only once
                diagnose_session()
        except ScrapliException as e:
            print(f"Scrapli error: {e}")
        except Exception as e:
            print(f"General error: {e}")
        return None

    return wrapper


def log_response(response):
    """18.17: log response metadata."""
    logging.info(
        "host=%s command=%r failed=%s elapsed=%.2fs",
        response.host,
        response.channel_input,
        response.failed,
        response.elapsed_time,
    )


def preflight(dev=DEVICE):
    """Check that the SSH port answers before running any example."""
    try:
        with socket.create_connection((dev["host"], dev["port"]), timeout=5):
            return True
    except OSError as e:
        print(f"Cannot reach {dev['host']}:{dev['port']} ({e})")
        if dev["host"] != MGMT_IP:
            print("The VM has no route to this address. Fix it with:")
            print(f"  sudo ip route add {dev['host']}/32 via {MGMT_IP}")
            print(f"or set ROUTER_IP = \"{MGMT_IP}\" at the top of this file.")
        else:
            print(f"Check that the VM is in the same network as {MGMT_IP} "
                  f"and that SSH is enabled on the router.")
        return False


# ---------------------------------------------------------------------------
# 18.5 - Basic connection: explicit open() / close()
# ---------------------------------------------------------------------------
@scrapli_safe
def basic_connection():
    conn = Scrapli(**scrapli_args())
    conn.open()
    try:
        response = conn.send_command("display version")
        print(response.result)
    finally:
        conn.close()  # always close, even if the command failed


# ---------------------------------------------------------------------------
# 18.7 - Understanding Scrapli responses
# ---------------------------------------------------------------------------
@scrapli_safe
def understand_response():
    with Scrapli(**scrapli_args()) as conn:  # opens and closes automatically
        response = conn.send_command("display version")
        log_response(response)

        print("host         :", response.host)
        print("command sent :", response.channel_input)
        print("failed       :", response.failed)             # True / False
        print("elapsed time :", f"{response.elapsed_time:.2f}s")
        print("first lines  :")
        print("\n".join(response.result.splitlines()[:5]))   # raw output (string)


# ---------------------------------------------------------------------------
# 18.8 - Running multiple show commands
# ---------------------------------------------------------------------------
COMMANDS = [
    "display version",
    "display ip interface brief",
    "display ip routing-table",
    "display current-configuration | include sysname",
]


@scrapli_safe
def run_multiple_commands(commands=COMMANDS):
    with Scrapli(**scrapli_args()) as conn:
        for cmd in commands:
            response = conn.send_command(cmd)
            log_response(response)
            print(f"\n===== {cmd}  (failed={response.failed}, "
                  f"{response.elapsed_time:.2f}s) =====")
            print(response.result)


# ---------------------------------------------------------------------------
# 18.9 - Sending configuration commands   (CHANGES THE ROUTER - opt-in)
# ---------------------------------------------------------------------------
@scrapli_safe
def send_config_commands():
    config = [
        "interface LoopBack10",
        "ip address 10.10.10.1 255.255.255.0",
    ]
    with Scrapli(**scrapli_args()) as conn:
        # send_configs() enters system-view, sends every line, then leaves.
        responses = conn.send_configs(config)
        for r in responses:
            log_response(r)
            print(f"{r.channel_input!r:45} failed={r.failed}")
        print(conn.send_command("display current-configuration interface LoopBack10").result)


# ---------------------------------------------------------------------------
# 18.10 - Saving configuration   (WRITES TO THE ROUTER - opt-in)
# Scrapli has no save_config() helper; on VRP you answer the prompt yourself.
# ---------------------------------------------------------------------------
@scrapli_safe
def save_configuration():
    with Scrapli(**scrapli_args()) as conn:
        prompt = conn.get_prompt()  # for example <R1>
        response = conn.send_interactive(
            [
                ("save", "sure to continue", False),
                ("y", prompt, False),
            ]
        )
        log_response(response)
        print(response.result)


# ---------------------------------------------------------------------------
# 18.11 - Running on multiple devices (sync)
# ---------------------------------------------------------------------------
def multiple_devices_sync():
    for dev in DEVICES:
        print(f"\n===== {dev['host']} =====")
        run_one_device(dev)


@scrapli_safe
def run_one_device(dev):
    with Scrapli(**scrapli_args(dev)) as conn:
        print(conn.send_command("display ip interface brief").result)


# ---------------------------------------------------------------------------
# 18.12 - Async Scrapli (many devices at the same time)
# ---------------------------------------------------------------------------
async def async_one_device(dev):
    try:
        async with AsyncScrapli(**scrapli_args(dev, transport="asyncssh")) as conn:
            r = await conn.send_command("display version")
            log_response(r)
            return dev["host"], r.result
    except ScrapliAuthenticationFailed:
        return dev["host"], "FAILED: authentication"
    except ScrapliTimeout:
        return dev["host"], "FAILED: timeout"
    except ScrapliException as e:
        return dev["host"], f"FAILED: {e}"
    except Exception as e:
        return dev["host"], f"FAILED: {e}"


async def async_main():
    # gather() runs every device at the same time
    results = await asyncio.gather(*(async_one_device(d) for d in DEVICES))
    for host, output in results:
        print(f"\n===== {host} =====")
        print(output)


def async_multiple_devices():
    try:
        import asyncssh  # noqa: F401
    except ImportError:
        print("Skipped: 'asyncssh' is not installed. Run: pip install asyncssh")
        return
    asyncio.run(async_main())


# ---------------------------------------------------------------------------
# 18.13 - Parsing with TextFSM (structured data, no regex)
# ---------------------------------------------------------------------------
@scrapli_safe
def parse_with_textfsm():
    try:
        import ntc_templates  # noqa: F401
    except ImportError:
        print("Skipped: run  pip install textfsm ntc-templates")
        return

    with Scrapli(**scrapli_args()) as conn:
        # ntc-templates has Huawei templates for "display interface brief" and
        # "display version", but not for "display ip interface brief".
        response = conn.send_command("display interface brief")
        parsed = response.textfsm_parse_output()  # list of dictionaries
        if not parsed:
            print("TextFSM could not parse this output. Raw output:")
            print(response.result)
            return
        for row in parsed:
            print(row)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not preflight():
        raise SystemExit(1)

    print("--- 18.5  Basic connection (display version) ---")
    basic_connection()

    print("\n--- 18.7  Response object ---")
    understand_response()

    print("\n--- 18.8  Multiple show commands ---")
    run_multiple_commands()

    print("\n--- 18.11 Multiple devices (sync) ---")
    multiple_devices_sync()

    print("\n--- 18.12 Async ---")
    async_multiple_devices()

    print("\n--- 18.13 TextFSM parsing ---")
    parse_with_textfsm()

    # These CHANGE the router. Uncomment only when you want that:
    # send_config_commands()   # 18.9  creates LoopBack10 10.10.10.1/24
    # save_configuration()     # 18.10 runs "save"