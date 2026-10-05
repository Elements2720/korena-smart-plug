"use strict";

const deviceViews = new Map();
const pendingDevices = new Set();
let serverReachable = false;
let refreshing = false;
const byId = (id) => document.getElementById(id);
const formatReading = (reading, unit, digits = 1) =>
  reading === null ? "—" : `${reading.toLocaleString(undefined, { maximumFractionDigits: digits })} ${unit}`;

async function fetchJson(path, options = {}) {
  const response = await fetch(path, { ...options, signal: AbortSignal.timeout(options.method ? 10000 : 4000) });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Server returned ${response.status}.`);
  return payload;
}

function announce(message, kind = "") {
  const notice = byId("command-message");
  notice.textContent = message;
  notice.className = `notice ${kind}`;
  notice.hidden = false;
}

function createOutlet(deviceId, number) {
  const element = byId("outlet-template").content.firstElementChild.cloneNode(true);
  element.querySelector(".outlet-name").textContent = `Outlet ${number}`;
  const button = element.querySelector("button");
  button.addEventListener("click", () => {
    const device = deviceViews.get(deviceId).device;
    const outlet = device.outlets.find((outlet) => outlet.number === number);
    sendPower(deviceId, number, !outlet.on);
  });
  return element;
}

function createDevice(device) {
  const element = byId("device-template").content.firstElementChild.cloneNode(true);
  const outlets = new Map();
  for (const outlet of device.outlets) {
    const outletElement = createOutlet(device.id, outlet.number);
    outlets.set(outlet.number, outletElement);
    element.querySelector(".outlet-grid").append(outletElement);
  }
  element.querySelector(".all-on").addEventListener("click", () => sendPower(device.id, 0, true));
  element.querySelector(".all-off").addEventListener("click", () => sendPower(device.id, 0, false));
  byId("devices").append(element);
  const view = { element, outlets, device };
  deviceViews.set(device.id, view);
  return view;
}

function updateOutlet(element, outlet, device) {
  const pending = pendingDevices.has(device.id) || device.busy;
  const enabled = serverReachable && device.ready && !pending;
  const unknown = outlet.on === null;
  element.classList.toggle("active", outlet.on === true);
  element.querySelector(".outlet-state").textContent = unknown ? "Unknown" : outlet.on ? "On" : "Off";
  element.querySelector(".outlet-reading").textContent =
    `${formatReading(outlet.power_w, "W")} · ${formatReading(outlet.temperature_c, "°C", 0)}`;
  const button = element.querySelector("button");
  button.disabled = !enabled || unknown;
  button.setAttribute("aria-checked", String(outlet.on === true));
  button.setAttribute("aria-label", `Outlet ${outlet.number} power${unknown ? ", state unknown" : ""}`);
  element.querySelector(".button-label").textContent = unknown ? "Waiting" : outlet.on ? "Turn off" : "Turn on";
}

function stateNote(device, pending) {
  if (!serverReachable) return "Server unreachable. Controls are paused.";
  if (pending) return "Waiting for the strip to confirm…";
  if (device.status === "waiting") return "Connected. Waiting for all four outlet readings…";
  if (!device.ready) return "Last known readings. Controls resume when fresh readings arrive.";
  const reportedAt = new Date(device.last_report_at * 1000).toLocaleTimeString();
  return `Confirmed by the strip at ${reportedAt}`;
}

function updateDevice(device) {
  const view = deviceViews.get(device.id) || createDevice(device);
  view.device = device;
  const pending = pendingDevices.has(device.id) || device.busy;
  const text = (selector, content) => { view.element.querySelector(selector).textContent = content; };
  text(".device-title", "MTTL-W01");
  text(".device-subtitle", `4 outlets · ${device.id.slice(-7)}`);
  text(".state-note", stateNote(device, pending));
  const status = serverReachable ? device.status : "offline";
  const labels = { online: "Connected", waiting: "Connecting", stale: "Readings stale", offline: "Disconnected" };
  const badge = view.element.querySelector(".status-badge");
  badge.className = `status-badge ${status}`;
  text(".status-text", labels[status]);
  for (const outlet of device.outlets) updateOutlet(view.outlets.get(outlet.number), outlet, device);
  for (const button of view.element.querySelectorAll(".all-controls button")) {
    button.disabled = !serverReachable || !device.ready || pending;
    button.setAttribute("aria-label", `${button.classList.contains("all-on") ? "Turn on" : "Turn off"} all four outlets on ${device.name}`);
  }
  text(".total-power", formatReading(device.power_w, "W"));
  text(".total-energy", formatReading(device.energy_kwh, "kWh", 3));
  text(".voltage", formatReading(device.voltage_v, "V"));
  text(".signal", formatReading(device.rssi_dbm, "dBm", 0));
  text(".device-ip", device.ip);
  text(".firmware", device.firmware);
  text(".device-id", device.id);
}

function renderSnapshot(snapshot) {
  const currentIds = new Set(snapshot.devices.map((device) => device.id));
  for (const [id, view] of deviceViews) {
    if (!currentIds.has(id)) { view.element.remove(); deviceViews.delete(id); }
  }
  for (const device of snapshot.devices) updateDevice(device);
  byId("empty").hidden = snapshot.devices.length > 0;
  byId("setup-help").hidden = snapshot.devices.length === 0;
  byId("empty-status").textContent = "Server is ready. Waiting for your MTTL-W01.";
  byId("server-address").textContent = `Server ${snapshot.server_ip} · Device port ${snapshot.device_port}`;
  const command = `py .\\provision.py --server-ip ${snapshot.server_ip}`;
  byId("pair-command").textContent = command;
  byId("help-command").textContent = command;
}

async function refresh() {
  if (refreshing || document.hidden) return;
  refreshing = true;
  try {
    const snapshot = await fetchJson("/api/state");
    serverReachable = true;
    byId("server-error").hidden = true;
    renderSnapshot(snapshot);
  } catch (error) {
    serverReachable = false;
    byId("server-error").textContent = "Can't reach the server. Check your home-network connection and that server.py is running. Reconnecting automatically…";
    byId("server-error").hidden = false;
    byId("empty-status").textContent = "Server unreachable. Check the connection before pairing.";
    for (const view of deviceViews.values()) updateDevice(view.device);
  } finally {
    refreshing = false;
  }
}

async function sendPower(deviceId, outlet, on) {
  if (pendingDevices.has(deviceId) || !serverReachable) return;
  pendingDevices.add(deviceId);
  updateDevice(deviceViews.get(deviceId).device);
  const target = outlet === 0 ? "All four outlets" : `Outlet ${outlet}`;
  announce(`${target}: requesting ${on ? "on" : "off"}. Waiting for confirmation…`, "pending");
  try {
    const response = await fetchJson("/api/power", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId, outlet, on }),
    });
    updateDevice(response.device);
    announce(`${target}: ${on ? "on" : "off"}, confirmed by the strip.`);
  } catch (error) {
    const message = error.name === "TimeoutError" || error instanceof TypeError
      ? "Connection interrupted. The command may have reached the strip. Check the current readings before trying again."
      : error.message;
    announce(message, "error");
  } finally {
    pendingDevices.delete(deviceId);
    const view = deviceViews.get(deviceId);
    if (view) updateDevice(view.device);
    await refresh();
  }
}

refresh();
setInterval(refresh, 2000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
