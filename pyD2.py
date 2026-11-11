
#Network Example — Full Netmiko With argparse

from netmiko import ConnectHandler
from getpass import getpass

ip = input("Router IP [192.168.74.215]: ") or "192.168.74.215"
username = input("Username [ovi123]: ") or "ovi123"
password = getpass("Password: ")
cmd = input("Command [display ip interface brief]: ") or "display ip interface brief"

device = {
    "device_type": "huawei_vrpv8",
    "host": ip,
    "port": 22,
    "username": username,
    "password": password,
    "conn_timeout": 30,
}

with ConnectHandler(**device) as conn:
    output = conn.send_command(cmd)

print(output)