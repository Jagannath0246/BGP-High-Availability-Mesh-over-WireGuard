# Enterprise SD-WAN: BGP High-Availability Mesh over WireGuard

![Architecture: 3-Node Mesh](https://img.shields.io/badge/Architecture-3--Node_Mesh-blue)
![Routing: BGP](https://img.shields.io/badge/Routing-BGP-orange)
![Encryption: WireGuard](https://img.shields.io/badge/Encryption-WireGuard-red)
![Automation: Python IaC](https://img.shields.io/badge/Automation-Python_Netmiko-brightgreen)

## 📌 Overview
This project demonstrates a fully automated, carrier-grade Software-Defined WAN (SD-WAN). It utilizes a custom Python Infrastructure-as-Code (IaC) controller to deploy a High Availability (HA) triangle mesh across three Linux nodes. 

By stripping routing intelligence away from WireGuard and handing 100% of the control plane to FRRouting (BGP), the network is capable of real-time, self-healing failover. If a primary direct link between two nodes suffers a catastrophic failure, BGP instantly reconverges and detours traffic through the third node without dropping application availability.

## 🏗️ Architecture & Topology

The infrastructure relies on pure Point-to-Point (P2P) cryptographic tunnels to bypass WireGuard's static routing limitations, allowing BGP to dynamically manage the pathing to isolated loopback application targets.

### Node Infrastructure
| Node | Role | BGP ASN | Loopback (App Target) | 
| :--- | :--- | :--- | :--- |
| **Node A** | Local Gateway | `AS 65001` | `192.168.1.1/24` |
| **Node B** | Cloud Web Server (Docker/Nginx) | `AS 65002` | `10.0.1.1/24` |
| **Node C** | Failover Router | `AS 65003` | `10.0.2.1/24` |

### The Point-to-Point Cryptographic Mesh (`/30` Subnets)
| Link | Interface 1 | Interface 2 | Subnet |
| :--- | :--- | :--- | :--- |
| **Node A ↔ Node B** | `wg_b` (`10.254.1.1`) | `wg_a` (`10.254.1.2`) | `10.254.1.0/30` |
| **Node B ↔ Node C** | `wg_c` (`10.254.2.1`) | `wg_b` (`10.254.2.2`) | `10.254.2.0/30` |
| **Node C ↔ Node A** | `wg_a` (`10.254.3.2`) | `wg_c` (`10.254.3.1`) | `10.254.3.0/30` |

---

## 🚀 Features

* **Zero-Touch Provisioning:** A Python controller utilizing `netmiko` completely tears down and rebuilds the encryption and routing infrastructure in under 10 seconds.
* **Base64 Configuration Injection:** Bypasses SSH multiline formatting limitations by dynamically encoding complex BGP/WireGuard templates in Python and decoding them directly onto the Linux filesystem.
* **Carrier-Grade Failover:** Validated sub-10-second BGP reconvergence. When the direct link `A ↔ B` is severed, traffic is seamlessly routed via `A ↔ C ↔ B`.
* **Zero-Trust Override:** FRR eBGP policies are explicitly managed to allow private mesh prefix sharing.

---

## 📸 Proof of Concept

### 1. Active BGP Peer Mesh
*(This screenshot proves the cryptographic tunnels are active and FRRouting is exchanging prefixes across the HA triangle).*
<br>
![BGP Summary](images/bgp_peers.png)

### 2. Infrastructure as Code (IaC) Execution
*(The custom Python controller rebuilding the mesh and restarting the Docker payload).*
<br>
![IaC Deployment](images/iac_deployment.png)

### 3. Real-Time Self-Healing (The Failover)
*(Sabotaging the primary BGP link and watching the routing table instantly shift the payload to the backup Node C detour).*
<br>
![Failover Proof](images/failover_proof.png)

### 4. Encrypted Payload Delivery
*(Fetching the Nginx web server payload exclusively over the custom loopback interfaces).*
<br>
![Payload Delivery](images/payload_delivery.png)

---

## 🛠️ Challenges & Engineering Solutions

Building this architecture presented several advanced networking challenges that required bridging the gap between static Linux networking and dynamic routing protocols.

### 1. The WireGuard Static Route Trap
* **The Problem:** By default, WireGuard reads the `AllowedIPs` configuration and aggressively injects static routes (Administrative Distance 0) into the Linux kernel. This completely blinded the BGP daemon (Distance 20). Even if BGP detected a link failure, the Linux kernel kept throwing packets down the dead tunnel.
* **The Solution:** Transitioned the architecture from a single multi-peer interface (`wg0`) to dual Point-to-Point interfaces (`wg_a`, `wg_b`). Injected `Table = off` to strip WireGuard's routing capabilities, and set `AllowedIPs = 0.0.0.0/0` to turn the interfaces into pure, "dumb" encryption pipes. This handed 100% routing authority back to BGP.

### 2. The SSH Race Condition
* **The Problem:** The initial Python automation script blasted 12 setup commands into the SSH sessions simultaneously. The Linux kernel could not tear down the old UDP sockets fast enough, causing the script to fail silently and drop the loopback IPs.
* **The Solution:** Replaced regex-based execution (`expect_string=r".*"`) with Netmiko's `send_command_timing()`. Introduced a hard `time.sleep(3)` phase mid-deployment to allow the kernel to release the UDP bindings before the script rebuilt the interfaces.

### 3. FRRouting "Zero Trust" Blocking
* **The Problem:** Once the 3-way mesh was established, the BGP neighbors connected successfully but refused to share IP addresses. The `show ip bgp summary` command listed `(Policy)` instead of the number of prefixes received.
* **The Solution:** Modern FRR implementations enforce RFC 8212 (Zero Trust). Since this is a private encrypted mesh, I injected `no bgp ebgp-requires-policy` into the FRR configuration generator to bypass the filter and merge the routing tables.

### 4. Docker Network Race Conditions
* **The Problem:** When the VMs rebooted, the Docker daemon attempted to start the `cloud-web-server` container before the Python script mapped the custom `10.0.1.1` loopback IP to the system, resulting in dropped port bindings and a "dead" web server.
* **The Solution:** Added an optional `post_commands` parameter to the Python deployment engine. The script now fully stabilizes the network and BGP handshakes first, and then explicitly sends a Docker restart payload strictly to Node B as the final deployment step.
