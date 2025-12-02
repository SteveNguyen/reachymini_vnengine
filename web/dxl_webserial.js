/**
 * Dynamixel Web Serial - Low-level serial port I/O only.
 * Protocol logic handled in Python (dynamixel.py).
 */

const PANEL_HTML = `
  <div class="dxl-card" id="dxl-panel">
    <h3>Dynamixel XL330 Control (Web Serial)</h3>
    <p class="camera-hint">
      Use Chrome/Edge desktop. Click Connect to pick your serial/USB adapter.
    </p>
    <div class="dxl-row">
      <label for="dxl-baud">Baud</label>
      <select id="dxl-baud">
        <option value="57600">57600</option>
        <option value="115200">115200</option>
        <option value="1000000" selected>1000000</option>
        <option value="2000000">2000000</option>
      </select>
      <button class="dxl-btn" id="dxl-connect">Connect serial</button>
    </div>
    <div class="dxl-status" id="dxl-status">Web Serial idle.</div>
  </div>
`;

class DxlWebSerial {
  constructor(statusNode) {
    this.statusNode = statusNode;
    this.port = null;
    this.writer = null;
    this.reader = null;
    this.connected = false;
  }

  status(msg) {
    if (this.statusNode) this.statusNode.textContent = msg;
  }

  async connect(baud) {
    if (!("serial" in navigator)) {
      this.status("Web Serial not supported.");
      return false;
    }
    if (this.connected) {
      await this.disconnect();
    }
    try {
      this.port = await navigator.serial.requestPort();
      await this.port.open({ baudRate: Number(baud) });
      this.writer = this.port.writable.getWriter();
      this.reader = this.port.readable.getReader();
      this.connected = true;
      this.status(`Connected at ${baud} bps.`);
      return true;
    } catch (err) {
      console.error(err);
      this.status(`Connect failed: ${err.message}`);
      this.connected = false;
      return false;
    }
  }

  async disconnect() {
    try {
      if (this.writer) this.writer.releaseLock();
      if (this.reader) this.reader.releaseLock();
      if (this.port) await this.port.close();
    } catch (err) {
      console.warn("Close error", err);
    } finally {
      this.writer = null;
      this.reader = null;
      this.port = null;
      this.connected = false;
      this.status("Disconnected.");
    }
  }

  async writeBytes(bytes) {
    if (!this.writer) throw new Error("Not connected.");
    await this.writer.write(new Uint8Array(bytes));
  }

  async readPacket(timeoutMs = 800) {
    if (!this.reader) throw new Error("No reader");
    const deadline = Date.now() + timeoutMs;
    const buf = [];

    while (Date.now() < deadline) {
      const { value, done } = await this.reader.read();
      if (done) break;
      if (value) buf.push(...value);

      // Look for Dynamixel Protocol 2.0 header and extract complete packet
      for (let i = 0; i < buf.length - 7; i += 1) {
        if (
          buf[i] === 0xff &&
          buf[i + 1] === 0xff &&
          buf[i + 2] === 0xfd &&
          buf[i + 3] === 0x00
        ) {
          const len = buf[i + 5] | (buf[i + 6] << 8);
          const end = i + 7 + len - 1;
          if (buf.length >= end + 1) {
            return buf.slice(i, end + 1);
          }
        }
      }
    }
    throw new Error("No response");
  }
}

// Global instance - expose on window for access from Gradio event handlers
let dxlSerial = null;
window.dxlSerial = null;

function mountDxlPanel() {
  const host = document.getElementById("dxl-panel-host");

  if (!host) return;

  // If already mounted, just ensure window.dxlSerial exists
  if (host.dataset.mounted === "1") {
    if (!window.dxlSerial) {
      const statusEl = document.getElementById("dxl-status");
      if (statusEl) {
        dxlSerial = new DxlWebSerial(statusEl);
        window.dxlSerial = dxlSerial;
      }
    }
    return;
  }

  host.dataset.mounted = "1";
  host.innerHTML = PANEL_HTML;

  const statusEl = document.getElementById("dxl-status");
  const connectBtn = document.getElementById("dxl-connect");
  const baudSelect = document.getElementById("dxl-baud");

  dxlSerial = new DxlWebSerial(statusEl);
  window.dxlSerial = dxlSerial;  // Expose globally

  connectBtn?.addEventListener("click", async () => {
    const baud = Number(baudSelect.value);
    if (dxlSerial.connected) {
      await dxlSerial.disconnect();
      connectBtn.textContent = "Connect serial";
      connectBtn.classList.remove("primary");
    } else {
      const connected = await dxlSerial.connect(baud);
      if (connected) {
        connectBtn.textContent = "Disconnect";
        connectBtn.classList.add("primary");
      }
    }
  });
}

function mountWhenReady() {
  mountDxlPanel();

  const observer = new MutationObserver(() => {
    mountDxlPanel();
  });
  observer.observe(document.body, { childList: true, subtree: true });

  const pollInterval = setInterval(() => {
    const host = document.getElementById("dxl-panel-host");
    if (host && !host.dataset.mounted) {
      const rect = host.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        mountDxlPanel();
      }
    }
    if (host?.dataset.mounted === "1") {
      clearInterval(pollInterval);
    }
  }, 500);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountWhenReady);
} else {
  mountWhenReady();
}
