// Optional browser integration check. Playwright is a development-only tool.
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { mkdir } = require("node:fs/promises");
const { chromium } = require("playwright");

const baseUrl = "http://127.0.0.1:8180";
const children = [];
const failures = [];

function startPython(...args) {
  const child = spawn("python3", args, { stdio: ["ignore", "pipe", "pipe"] });
  children.push(child);
  child.stderr.on("data", (chunk) => process.stderr.write(chunk));
  return child;
}

async function stop(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  await new Promise((resolve) => { child.once("exit", resolve); child.kill("SIGTERM"); });
}

async function waitForServer() {
  for (let attempt = 0; attempt < 50; attempt++) {
    try { if ((await fetch(`${baseUrl}/api/state`)).ok) return; }
    catch (error) { if (!(error instanceof TypeError)) throw error; }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("QA server did not start.");
}

async function assertFits(page) {
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Horizontal overflow");
  for (const button of await page.locator("button:visible").all()) {
    assert((await button.boundingBox()).height >= 44, "Undersized button");
  }
}

async function captureViewports(page, prefix) {
  for (const [name, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844]]) {
    await page.setViewportSize({ width, height });
    await assertFits(page);
    await page.screenshot({ path: `.impeccable/review/${prefix}${name}.png`, fullPage: true });
  }
  for (const [width, height] of [[375, 812], [844, 390], [768, 1024]]) {
    await page.setViewportSize({ width, height });
    await assertFits(page);
  }
}

async function checkControls(page) {
  const first = page.getByRole("switch", { name: "Outlet 1 power", exact: true });
  await first.click();
  await page.waitForFunction(() => document.getElementById("command-message").textContent.includes("confirmed by the strip"));
  assert.equal(await first.getAttribute("aria-checked"), "true");
  await first.focus();
  await page.keyboard.press("Space");
  await page.waitForFunction(() => document.querySelector('[role="switch"]').getAttribute("aria-checked") === "false");
  await page.getByRole("button", { name: /^Turn on all four/ }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('[role="switch"]')].every((button) => button.getAttribute("aria-checked") === "true"));
  await page.getByRole("button", { name: /^Turn off all four/ }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('[role="switch"]')].every((button) => button.getAttribute("aria-checked") === "false"));
  await page.waitForFunction(() => !document.querySelector('[role="switch"]').disabled);
}

async function main() {
  await mkdir(".impeccable/review", { recursive: true });
  let browser;
  try {
    const server = startPython("server.py", "--bind", "127.0.0.1", "--server-ip", "192.168.1.50", "--web-port", "8180");
    await waitForServer();
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ reducedMotion: "reduce" });
    page.on("pageerror", (error) => failures.push(error.message));
    page.on("console", (message) => { if (message.type() === "error" && !message.text().includes("Failed to load resource")) failures.push(message.text()); });
    await page.goto(baseUrl);
    await page.getByText("Server is ready. Waiting for your MTTL-W01.").waitFor();
    assert((await page.locator("#pair-command").textContent()).includes("192.168.1.50"));
    await captureViewports(page, "setup-");

    let simulator = startPython("tests/simulator.py");
    await page.getByText("Connected", { exact: true }).waitFor();
    assert.equal(await page.getByRole("switch").count(), 4);
    await captureViewports(page, "");
    await checkControls(page);
    await stop(simulator);
    await page.getByText("Disconnected", { exact: true }).waitFor();
    assert(await page.getByRole("switch").first().isDisabled());

    simulator = startPython("tests/simulator.py", "--ignore-outlet", "3");
    await page.getByText("Connected", { exact: true }).waitFor();
    await page.getByRole("button", { name: /^Turn on all four/ }).click();
    await page.getByText("The strip did not confirm the requested state. Check the outlets before trying again.", { exact: true }).waitFor();
    assert.equal(await page.getByRole("switch", { name: "Outlet 3 power", exact: true }).getAttribute("aria-checked"), "false");
    await stop(simulator);
    await stop(server);
    await page.locator("#server-error:not([hidden])").waitFor();
    assert(await page.getByRole("switch").first().isDisabled());
    assert.deepEqual(failures, [], "Browser JavaScript errors");
    console.log("Browser checks passed: setup, responsive layouts, keyboard control, individual/all switches, disconnect/reconnect, unconfirmed command, server loss.");
  } finally {
    if (browser) await browser.close();
    await Promise.all(children.map(stop));
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
