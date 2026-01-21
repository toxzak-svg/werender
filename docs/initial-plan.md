This is a comprehensive product plan to build a Minimum Viable Product (MVP) for a Distributed Render Manager. The core philosophy of this plan is **"Zero-Config Peer-to-Peer,"** ensuring that non-technical animators can link computers simply by opening the app on the same Wi-Fi network.

### **1. High-Level Architecture**
To achieve "no technical setup," avoid a traditional static Server/Client model. Instead, use a **Hub-and-Spoke** model where the machine submitting the job temporarily becomes the "Coordinator," and all other available machines become "Workers."

*   **The Coordinator (User's Main PC):**
    *   Hosts the HTTP API & WebSocket Server.
    *   Holds the Job Queue.
    *   Acts as the File Server (serves the `.blend` file to workers).
*   **The Workers (Laptops, Old Desktops):**
    *   Run a lightweight "Listener" agent.
    *   Auto-discover the Coordinator via mDNS (Zeroconf).
    *   Download assets, render frames, and upload results.

***

### **2. Technology Stack**
*   **Core Language:** **Python 3.10+** (Industry standard for VFX pipelines).[1]
*   **Network Discovery:** **Zeroconf (mDNS)**. This allows computers to find each other (e.g., `render-node.local`) without typing IP addresses.[2][3]
*   **Communication:** **FastAPI (HTTP + WebSockets)**. HTTP for file transfers; WebSockets for real-time progress bars.
*   **Render Engine (MVP):** **Blender Cycles/Eevee**. It has the best CLI support for a proof-of-concept.
*   **Frontend UI:** **React (served locally)** or **PySide6 (Qt)**. *Recommendation: React.* It allows the user to monitor the render from their phone by visiting the Coordinator’s local IP.

***

### **3. MVP Development Phases**

#### **Phase 1: The Render Agent (The "Worker")**
*Goal: Build a Python script that can receive a command and render a specific frame.*
*   **Job Wrapper:** Create a Python class that wraps the Blender Command Line Interface (CLI).
*   **Logic:** The script accepts a frame number and a file path. It executes:
    `blender -b project.blend -f 120` (Render background, frame 120).[4][5]
*   **Output Validation:** The script must check if the output image file exists after the process finishes to confirm success.

#### **Phase 2: Network Discovery (The "Zero Setup" Magic)**
*Goal: Machines find each other automatically.*
*   **Service Registration:** When the app launches, it broadcasts a service type `_renderfarm._tcp.local.` using the `zeroconf` library.[2]
*   **Handshake:**
    *   **Coordinator:** "I have a job. Who is available?"
    *   **Workers:** "I am available. My specs are: 8-core CPU, RTX 3080."
*   **Asset Distribution (Crucial):**
    *   The Coordinator spins up a temporary HTTP file server.
    *   Workers download the `.blend` file to a temporary directory before starting. This avoids the complex setup of a Shared Network Drive (NAS).[6]

#### **Phase 3: The Scheduler & State Management**
*Goal: Manage the queue and distribute work.*
*   **Chunking:** The Scheduler breaks the animation into individual frames (e.g., Frames 1–100 become 100 individual tasks).
*   **Assignment Logic:**
    *   *Worker A (Fast PC):* Gets Frame 1.
    *   *Worker B (Old Laptop):* Gets Frame 2.
    *   *Worker A:* Finishes Frame 1, requests next available (Frame 3).
*   **Result Collection:** Workers upload the finished PNG/EXR image back to the Coordinator via HTTP POST.

#### **Phase 4: Fault Tolerance (Intelligent Fallback)**
*Goal: Handle crashes and disconnections.*
*   **Heartbeat System:** Workers send a "pulse" (ping) every 5 seconds via WebSocket.
*   **Timeout Logic:** If a worker misses 3 heartbeats (15 seconds) or takes 300% longer than the average render time of other nodes, the Coordinator marks the node as "Dead."
*   **Re-Queue:** The specific frame assigned to the dead node is immediately returned to the "Pending" queue to be picked up by the next available machine.

#### **Phase 5: User Interface (Dashboard)**
*Goal: Visualization.*
*   **Job List:** Shows active projects.
*   **Node Grid:** Visual cards for each connected machine showing:
    *   Status (Idle/Rendering).
    *   Current Frame.
    *   Temperature/CPU Usage (optional, via `psutil`).
*   **Controls:** A giant "Pause" button that sends a `SIGSTOP` or cancel command to all workers immediately.

***

### **4. Detailed Feature breakdown: "Zero Technical Setup"**

To truly achieve "no setup," you must handle the hardest part of rendering: **Dependencies (Textures/Assets).**

**The "Pack & Go" Strategy (Recommended for MVP):**
Instead of trying to sync folder paths across Windows/Mac/Linux, the MVP should force the user to use Blender's "Pack Resources" feature.
1.  **User Action:** User clicks "Queue Render."
2.  **System Action:** The app runs a background script to "Pack" external data (textures) into the `.blend` file.
3.  **Transfer:** This single, slightly larger file is sent to workers.
4.  **Benefit:** Zero "missing texture" errors; zero path configuration.

### **5. Roadmap Timeline**

| Sprint | Duration | Focus | Key Deliverable |
| :--- | :--- | :--- | :--- |
| **Sprint 1** | Week 1-2 | **Core Logic** | Python script that renders frame 1-10 on local loopback. |
| **Sprint 2** | Week 3-4 | **Networking** | Two computers discovering each other via Zeroconf. |
| **Sprint 3** | Week 5-6 | **Distribution** | Sending a file from PC A to PC B and getting a PNG back. |
| **Sprint 4** | Week 7-8 | **Resilience** | Unplugging a worker mid-render and watching the job re-queue. |
| **Sprint 5** | Week 9-10 | **UI/UX** | React Dashboard and "One-Click" Installer. |

### **6. Potential Pitfalls to Watch**
*   **Firewalls:** Windows Defender often blocks Python scripts listening on ports.
    *   *Solution:* Your installer script must add a Firewall Exception rule during installation.
*   **Version Mismatch:** If the Coordinator runs Blender 4.0 and a Worker runs Blender 3.6, the file might crash.
    *   *MVP Solution:* Strict version checking. Workers report their Blender version during the Handshake; if it doesn't match the Coordinator, they are rejected.
