from netmiko import ConnectHandler
import getpass
import time
import base64

print("\n--- BGP/WireGuard P2P Enterprise Mesh Controller ---")

# ==========================================
# THE SECRETS VAULT - CRYPTO KEYS LOCKED
# ==========================================
KEYS = {
    "A": {
        "priv": "MNxzIPXqtMjBBtoSToT855T+y/yBFVpxKxzL4zIURWA=",
        "pub": "xr+/RyHE21UuSe+xsb6rxUf02UjVVOS5xfYAinjERCM="
    },
    "B": {
        "priv": "eJBA2Ufk+ie2w6TjrApbxoKojW4vHDrTPhjq+u1KH0g=",
        "pub": "2/Mlp1Bk++F0BoHgjECGmBD1dR35tHS6P9eAzJWfB0Y="
    },
    "C": {
        "priv": "YP/G7C8nrrSTJVgPnBh+1PlugR9D7XQXFf/YdG+4j1k=",
        "pub": "pRFCxIA4zcVVk9CVndXWuj5BbhQml6neFFM4UaWASjs="
    }
}

# Gather physical IP addresses
ip_a = input("Enter Node A Hotspot IP: ")
ip_b = input("Enter Node B Hotspot IP: ")
ip_c = input("Enter Node C Hotspot IP (e.g. 10.195.96.127): ")
sudo_pass = getpass.getpass("Enter the sudo password for the nodes: ")


# ==========================================
# CONFIGURATION GENERATORS (POINT-TO-POINT)
# ==========================================
def generate_wg_confs(node_id):
    """Generates dual P2P WireGuard interfaces with routing stripped (Table = off)"""
    if node_id == "A":
        return {
            "wg_b": f"""[Interface]
PrivateKey = {KEYS['A']['priv']}
Address = 10.254.1.1/30
ListenPort = 51821
Table = off

[Peer]
PublicKey = {KEYS['B']['pub']}
Endpoint = {ip_b}:51821
AllowedIPs = 0.0.0.0/0
""",
            "wg_c": f"""[Interface]
PrivateKey = {KEYS['A']['priv']}
Address = 10.254.3.1/30
ListenPort = 51822
Table = off

[Peer]
PublicKey = {KEYS['C']['pub']}
Endpoint = {ip_c}:51822
AllowedIPs = 0.0.0.0/0
"""
        }
    elif node_id == "B":
        return {
            "wg_a": f"""[Interface]
PrivateKey = {KEYS['B']['priv']}
Address = 10.254.1.2/30
ListenPort = 51821
Table = off

[Peer]
PublicKey = {KEYS['A']['pub']}
Endpoint = {ip_a}:51821
AllowedIPs = 0.0.0.0/0
""",
            "wg_c": f"""[Interface]
PrivateKey = {KEYS['B']['priv']}
Address = 10.254.2.1/30
ListenPort = 51823
Table = off

[Peer]
PublicKey = {KEYS['C']['pub']}
Endpoint = {ip_c}:51823
AllowedIPs = 0.0.0.0/0
"""
        }
    elif node_id == "C":
        return {
            "wg_a": f"""[Interface]
PrivateKey = {KEYS['C']['priv']}
Address = 10.254.3.2/30
ListenPort = 51822
Table = off

[Peer]
PublicKey = {KEYS['A']['pub']}
Endpoint = {ip_a}:51822
AllowedIPs = 0.0.0.0/0
""",
            "wg_b": f"""[Interface]
PrivateKey = {KEYS['C']['priv']}
Address = 10.254.2.2/30
ListenPort = 51823
Table = off

[Peer]
PublicKey = {KEYS['B']['pub']}
Endpoint = {ip_b}:51823
AllowedIPs = 0.0.0.0/0
"""
        }


def generate_frr_conf(node_id):
    """Dynamically generates the true P2P BGP routing table"""
    if node_id == "A":
        return """router bgp 65001
 bgp router-id 192.168.1.1
 no bgp ebgp-requires-policy
 neighbor 10.254.1.2 remote-as 65002
 neighbor 10.254.3.2 remote-as 65003
 address-family ipv4 unicast
  network 192.168.1.0/24
  neighbor 10.254.1.2 activate
  neighbor 10.254.3.2 activate
 exit-address-family"""
    elif node_id == "B":
        return """router bgp 65002
 bgp router-id 10.0.1.1
 no bgp ebgp-requires-policy
 neighbor 10.254.1.1 remote-as 65001
 neighbor 10.254.2.2 remote-as 65003
 address-family ipv4 unicast
  network 10.0.1.0/24
  neighbor 10.254.1.1 activate
  neighbor 10.254.2.2 activate
 exit-address-family"""
    elif node_id == "C":
        return """router bgp 65003
 bgp router-id 10.0.2.1
 no bgp ebgp-requires-policy
 neighbor 10.254.3.1 remote-as 65001
 neighbor 10.254.2.1 remote-as 65002
 address-family ipv4 unicast
  network 10.0.2.0/24
  neighbor 10.254.3.1 activate
  neighbor 10.254.2.1 activate
 exit-address-family"""


# ==========================================
# THE DEPLOYMENT ENGINE
# ==========================================
def inject_file(net_connect, filepath, content):
    """Encodes multiline files to Base64 to bypass SSH formatting issues"""
    b64_content = base64.b64encode(content.encode()).decode()
    cmd = f"echo '{sudo_pass}' | sudo -S sh -c 'echo {b64_content} | base64 -d > {filepath}'"
    net_connect.send_command_timing(cmd)


def provision_node(node_id, host_ip, username, local_loopback, post_commands=None):
    print(f"\n[*] Provisioning Node {node_id} ({host_ip})...")
    device = {"device_type": "linux", "host": host_ip, "username": f"node{node_id.lower()}", "password": sudo_pass}

    try:
        net_connect = ConnectHandler(**device)
        print("    [+] SSH Connected. Purging legacy infrastructure...")

        # Scorched Earth Teardown
        for wg_iface in ["wg0", "wg_a", "wg_b", "wg_c"]:
            net_connect.send_command_timing(
                f"echo '{sudo_pass}' | sudo -S wg-quick down {wg_iface} 2>/dev/null || true")
            net_connect.send_command_timing(
                f"echo '{sudo_pass}' | sudo -S ip link delete {wg_iface} 2>/dev/null || true")
        time.sleep(2)

        print("    [+] Injecting Base64 Dual-P2P Configurations...")
        wg_confs = generate_wg_confs(node_id)

        # Inject and bring up dual WireGuard interfaces
        for iface_name, conf_data in wg_confs.items():
            inject_file(net_connect, f"/etc/wireguard/{iface_name}.conf", conf_data)
            net_connect.send_command_timing(f"echo '{sudo_pass}' | sudo -S wg-quick up {iface_name}")

        # Inject FRR
        frr_conf = generate_frr_conf(node_id)
        inject_file(net_connect, "/etc/frr/frr.conf", frr_conf)

        print("    [+] Rebuilding Routing Engine and Firewalls...")
        commands = [
            f"echo '{sudo_pass}' | sudo -S ip addr add {local_loopback} dev lo 2>/dev/null || true",
            # The + wildcard allows traffic on all wg_a, wg_b, wg_c interfaces simultaneously
            f"echo '{sudo_pass}' | sudo -S iptables -I INPUT -i wg+ -j ACCEPT",
            f"echo '{sudo_pass}' | sudo -S iptables -I OUTPUT -o wg+ -j ACCEPT",
            f"echo '{sudo_pass}' | sudo -S iptables -I FORWARD -i wg+ -j ACCEPT",
            f"echo '{sudo_pass}' | sudo -S iptables -I FORWARD -o wg+ -j ACCEPT",
            f"echo '{sudo_pass}' | sudo -S systemctl restart frr"
        ]

        for cmd in commands:
            net_connect.send_command_timing(cmd)

        if post_commands:
            print("    [+] Executing post-commands (Docker)...")
            for cmd in post_commands:
                net_connect.send_command_timing(cmd)

        print(f"    [!] Node {node_id} is successfully meshed.")
        net_connect.disconnect()

    except Exception as e:
        print(f"    [-] Failed to configure Node {node_id}: {e}")


# ==========================================
# EXECUTION
# ==========================================
provision_node("A", ip_a, "nodea", "192.168.1.1/24")
provision_node("B", ip_b, "nodeb", "10.0.1.1/24",
               post_commands=[f"echo '{sudo_pass}' | sudo -S docker restart cloud-web-server"])
provision_node("C", ip_c, "nodec", "10.0.2.1/24")

print("\n[!] The Enterprise P2P Triangle is active. Standby for BGP Convergence.")