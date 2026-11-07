from netmiko import ConnectHandler
from datetime import datetime
import os

# 1. Ensure backup directory exists
os.makedirs("backups", exist_ok=True)

device = {
    "device_type": "huawei_vrpv8",
    "host": "1.11.11.22",
    "port": 22,
    "username": "ovi123",
    "password": "Test@123",
    "conn_timeout": 60,
}

# 2. Pull live running-configuration
with ConnectHandler(**device) as conn:
    config = conn.send_command("display current-configuration")

# 3. Save with timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = f"backups/R1_{timestamp}.txt"

with open(backup_path, "w") as f:
    f.write(config)

print(f"Config successfully backed up to: {backup_path}")


## For Netmiko Library ~/netenv/bin/python /home/ovi/auto1.py