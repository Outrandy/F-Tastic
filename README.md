F-Tastic 🚀
High-Speed, Zero-Configuration P2P File Sharing for Local Networks
F-Tastic is a lightweight desktop application designed to make moving files between computers on the same network effortless. No cloud, no external servers, and no USB drives required. Just launch, link a folder, and start transferring at full LAN speeds.

✨ Key Features
Zero-Config Discovery: Using mDNS (Multicast DNS), peers on your local network automatically appear in your "Network Peers" list—no setup required.

Identify at a Glance: Peers are displayed with their Computer Name and DHCP IP address, making it easy to know exactly who you are connecting to.

Hybrid Connectivity: If mDNS is blocked by a firewall, use the Manual IP Connection to connect directly to a specific device.

Full Folder Support: Transfer entire directory structures. F-Tastic recreates the folder hierarchy on the receiving end automatically.

Integrated Download Manager: Track progress with a real-time modal progress bar that calculates percentage completion for large files or batch transfers.

Active Transfer Indicators: Visual feedback (blinking arrows ▶ / ◀) next to peer names lets you know exactly when someone is downloading from you or when you are pulling a file.

Draggable Interface: Drag files directly from the app tree into your local OS folders.

Privacy-First: Files are streamed directly between devices (Point-to-Point). Your data never touches the internet or a third-party server.

🛠 How It Works
F-Tastic operates on a Client-Server Architecture where every instance of the app acts as both a sender and a receiver:

The Discovery Layer: Upon startup, the app registers an _ftastic._tcp service via Zeroconf. It listens for other instances on the network and populates the sidebar dynamically.

The Server Layer: A background TCP server listens on port 55555. When a peer clicks your name, your app sends a JSON-encoded manifest of your shared folder.

The Transfer Layer: Files are sent using a custom binary protocol. For efficiency and reliability, we implement a 4-byte length header for metadata and stream the actual file data in 1MB chunks to maximize throughput without hogging system memory.

System Awareness: The app is built with Windows 11 compatibility in mind, automatically filtering out hidden system files like desktop.ini or thumbs.db to keep your file lists clean.

🚀 Getting Started
Prerequisites
Python 3.8+

PyQt6

Zeroconf

Installation
Clone the repo:

Bash
git clone https://github.com/Outrandy/f-tastic.git
Install dependencies:

Bash
pip install -r requirements.txt
Run the application:

Bash
python ftastic.py
🛡 Safety Features
Closure Protection: If you try to close the app during an active transfer, a warning dialog appears to prevent accidental connection loss for your peers.

Path Validation: All file requests are normalized to your shared folder to prevent "Directory Traversal" security risks.
