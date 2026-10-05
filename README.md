# Home Strip

## Android pairing app

The [Android companion](android/README.md) bundles pairing without Python on the phone. Supports Android 10+; physical pairing has been verified on an S21 FE running Android 16. The Linux controller is still required for outlet control.

A home-network browser controller for the LG U+ / TONLY MTTL-W01 power strip. Runs on a Linux server with Python 3.9+ and no third-party runtime packages.

Controls: four outlet switches, all on/off, confirmed states, connection status, and power, energy, temperature, voltage, and Wi-Fi readings when the firmware supplies them. Energy is the device's reported counter, not a daily total. No history is stored.

The native-protocol reference is [powerk](https://github.com/ahmedtohamy1/powerk). This implementation was written for this project from its documented wire format. The actual strip's firmware compatibility still needs a hardware test.

## 1. Run on the Linux server

Copy this project folder to your Linux server. The server can stay connected by Ethernet.

Find its home-network IPv4 address:

```bash
hostname -I
```

Choose the router-facing address, typically `192.168.x.x` or `10.x.x.x`, rather than a Docker, VPN, or loopback address. Give it a DHCP reservation in your router so the address stays fixed.

From the project folder, start the controller (replace the example IP):

```bash
python3 server.py --server-ip 192.168.1.50
```

Open `http://192.168.1.50:8080` from your Windows PC. Before pairing, the page displays setup instructions. Keep the process running; the strip needs it for browser control.

The server listens on TCP **10086** for the strip and **8080** for browsers. If a firewall is enabled, allow both from your home subnet. For example, **only if your server uses UFW and your home subnet is 192.168.1.0/24**:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 10086 proto tcp
sudo ufw allow from 192.168.1.0/24 to any port 8080 proto tcp
```

The app is intended for a trusted home LAN and has no login. Do not forward these ports to the internet.

## 2. Pair from the Windows PC

The PC needs Wi-Fi and Python 3.9+. Before disconnecting from your home network, download **provision.py** using the app's download link, or copy that file to the PC. It is standalone.

1. Hold the strip's main button for about 10 seconds until the LED flashes quickly.
2. Connect the PC to **TONLY_TAP_935CA80**. The publicly documented password pattern gives **LGU_935CA80**. Lack of internet on this network is normal.
3. In PowerShell, go to the directory containing `provision.py` and run (replace the IP with the **Linux server's** home-network address):

```powershell
py .\provision.py --server-ip 192.168.1.50
```

If your Python installation provides `python` rather than `py`, use that command instead.

4. Enter your **2.4 GHz** home Wi-Fi name and password when prompted. The password is entered locally, hidden, and is not saved by this project. The strip's setup protocol cannot carry a colon, newline, or NUL in either credential.
5. Expect `Server address acknowledged.` and `Wi-Fi settings acknowledged.`. These acknowledge configuration, not a completed connection to your home Wi-Fi.
6. Reconnect the PC to your normal home network. Watch the Linux terminal for `Strip ... connected; firmware ...`. Return to the browser; the controls appear automatically.

**First hardware check:** choose an outlet whose connected device can be switched off, toggle it, and verify both the physical outlet and the browser state. Test all four outlets individually. Simulator checks do not establish hardware compatibility.

You can repeat pairing to change the Wi-Fi network or controller IP. The strip stores a single controller address.

## 3. Start automatically on Linux (optional)

On a systemd-based server, copy `deploy/home-strip.service` to `/etc/systemd/system/home-strip.service`. First edit `User`, `WorkingDirectory`, and `ExecStart` to match your server, project path, and home-network IP. Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now home-strip
sudo journalctl -u home-strip -f
```

This starts the application's server at boot. The template is not installed automatically.

## Behavior and troubleshooting

- Outlet reports are polled every five seconds; the browser checks server state every two seconds while its tab is visible.
- Switches change only when reported by the strip. A command succeeds only after fresh reports show the requested state for every targeted outlet. Commands are serialized per strip.
- No confirmation: the page reports an error and does not retry the command automatically. Some outlets may already have changed, particularly with all-on/off. Check current readings before retrying.
- TCP connected but readings older than 20 seconds: controls pause and show **Readings stale**. The server also drops sessions that send no line for 30 seconds. It accepts a new connection when the strip reconnects.
- No strip appears: check 2.4 GHz Wi-Fi, the provisioned Linux server IP, TCP 10086 firewall rules, and whether the server is running. Guest-network or access-point client isolation can prevent the strip from reaching the server.
- Setup cannot connect: verify that the Windows PC is still on the strip's network, and that its gateway is `192.168.1.1`. The tool has `--host` for a different setup address. Acknowledgement failures do not print the response, since a firmware response could contain credentials.
- Browser cannot reach server: check TCP 8080, its LAN IP, and `server.py`'s terminal output. A VM/WSL IP detected automatically may not be reachable from the strip; run on the home Linux server with an explicit `--server-ip`.
- A changed controller IP requires pairing again. A restarted server forgets previous session metadata; the strip must reconnect and provide fresh reports.

## Checks

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q server.py protocol.py provision.py web.py
node --check static/app.js
```

Node is only needed for the JavaScript syntax check, not to run the app. Tests use actual loopback TCP/HTTP connections and a test-only device simulator, including unconfirmed commands, reconnection, stale readings, request validation, and pairing acknowledgements. Test code uses Python 3.11+; the application uses Python 3.9+ syntax and standard-library APIs.

For the optional headless-browser check on Linux, install Playwright outside the project:

```bash
npm install --prefix /tmp/home-strip-qa playwright
node /tmp/home-strip-qa/node_modules/playwright/cli.js install chromium
NODE_PATH=/tmp/home-strip-qa/node_modules node tests/browser_check.cjs
```

This starts temporary loopback listeners on ports 8180 and 10086, drives a test-only strip simulator, checks browser behavior and responsive layouts, writes screenshots to `.impeccable/review/`, and stops its processes afterward. Stop the real controller first to free TCP 10086. The check requires a Linux environment with Chromium's system libraries available. Screenshots contain simulated readings, not readings from physical hardware.

## HTTP API

- `GET /api/state`: server address and device snapshots. Unknown readings are `null`; `ready` means all four outlet reports are recent and the session is connected.
- `POST /api/power`: JSON `{"device_id":"AABBC935CA80","outlet":1,"on":true}` (replace the example ID with your strip's ID from `/api/state`). Outlet `0` targets all four. Returns `confirmed: true` with a device snapshot only after fresh matching reports; failures return non-200 JSON with an `error` message.
- `GET /provision.py`: standalone setup tool download.

Device MAC addresses identify sessions; they are not authentication credentials. The app serves only its explicit static routes, not the project directory.
