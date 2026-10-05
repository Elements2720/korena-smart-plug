package com.homestrip.app;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.net.*;
import android.net.wifi.WifiNetworkSpecifier;
import android.os.*;
import android.text.InputType;
import android.view.View;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

public class MainActivity extends Activity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private ConnectivityManager connectivity;
    private ConnectivityManager.NetworkCallback callback;
    private EditText server, setupName, setupPassword, homeName, homePassword;
    private TextView status;
    private Button pair;
    private boolean running;
    private volatile boolean destroyed;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        connectivity = getSystemService(ConnectivityManager.class);
        ScrollView scroll = new ScrollView(this);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(24 * getResources().getDisplayMetrics().density);
        content.setPadding(pad, pad * 2, pad, pad);
        scroll.addView(content); setContentView(scroll);
        TextView title = new TextView(this); title.setText("Home Strip"); title.setTextSize(30); content.addView(title);
        TextView intro = new TextView(this);
        intro.setText("Pair your MTTL-W01 with your home’s 2.4 GHz Wi-Fi. Hold the strip’s main button for about 10 seconds first. Keep this screen open during pairing.");
        content.addView(intro);
        server = field(content, "Linux server IPv4 address", getPreferences(0).getString("server", "192.168.1.220"), false);
        setupName = field(content, "Strip setup Wi-Fi name", "TONLY_TAP_935CA80", false);
        setupPassword = field(content, "Strip setup Wi-Fi password", "LGU_935CA80", true);
        homeName = field(content, "Home Wi-Fi name (2.4 GHz)", "", false);
        homePassword = field(content, "Home Wi-Fi password", "", true);
        pair = new Button(this); pair.setText("Pair strip"); content.addView(pair);
        pair.setOnClickListener(v -> begin());
        Button controls = new Button(this); controls.setText("Open outlet controls"); content.addView(controls);
        controls.setOnClickListener(v -> {
            try { String ip = validIp(); getPreferences(0).edit().putString("server", ip).apply();
                startActivity(new android.content.Intent(android.content.Intent.ACTION_VIEW, Uri.parse("http://" + ip + ":8080")));
            } catch (IllegalArgumentException e) { status.setText(e.getMessage()); }
        });
        status = new TextView(this); status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        status.setText("Wi-Fi credentials stay on this phone and are sent only to the strip. Android will ask you to approve its setup network."); content.addView(status);
    }

    private EditText field(LinearLayout parent, String label, String value, boolean secret) {
        TextView caption = new TextView(this); caption.setText(label); parent.addView(caption);
        EditText input = new EditText(this); input.setSingleLine(); input.setText(value);
        input.setInputType(InputType.TYPE_CLASS_TEXT | (secret ? InputType.TYPE_TEXT_VARIATION_PASSWORD : InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS));
        input.setSaveEnabled(!secret); parent.addView(input); return input;
    }

    private String validIp() {
        String ip = server.getText().toString().trim();
        String[] parts = ip.split("\\.", -1);
        if (parts.length != 4) throw new IllegalArgumentException("Enter the server’s home-network IPv4 address.");
        int[] octets = new int[4];
        try { for (int i=0;i<4;i++) { if (!parts[i].matches("[0-9]{1,3}")) throw new NumberFormatException(); octets[i]=Integer.parseInt(parts[i]); if(octets[i]>255) throw new NumberFormatException(); } }
        catch(NumberFormatException e) { throw new IllegalArgumentException("Invalid IPv4 address."); }
        if (!(octets[0]==10 || (octets[0]==192 && octets[1]==168) || (octets[0]==172 && octets[1]>=16 && octets[1]<=31)))
            throw new IllegalArgumentException("Use a private home-network server address.");
        return octets[0]+"."+octets[1]+"."+octets[2]+"."+octets[3];
    }

    private void begin() {
        if (running) return;
        String permission = Build.VERSION.SDK_INT >= 33 ? Manifest.permission.NEARBY_WIFI_DEVICES : Manifest.permission.ACCESS_FINE_LOCATION;
        if (checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(Build.VERSION.SDK_INT >= 33 ? new String[]{permission} : new String[]{permission, Manifest.permission.ACCESS_COARSE_LOCATION}, 1);
            status.setText("Allow Wi-Fi permission, then tap Pair strip again. On Android 10–12, also enable Location in phone settings."); return;
        }
        try {
            String ip = validIp(), ssid = homeName.getText().toString(), password = homePassword.getText().toString();
            if (ssid.isEmpty() || ssid.getBytes(StandardCharsets.UTF_8).length > 32 || (ssid+password).matches("(?s).*[\\r\\n:\\x00].*"))
                throw new IllegalArgumentException("Enter a Wi-Fi name up to 32 bytes. Credentials cannot contain colons or line breaks.");
            WifiNetworkSpecifier spec = new WifiNetworkSpecifier.Builder().setSsid(setupName.getText().toString())
                .setWpa2Passphrase(setupPassword.getText().toString()).build();
            pairingSuffix = setupName.getText().toString().substring(setupName.getText().toString().lastIndexOf('_')+1).toUpperCase(Locale.ROOT);
            running = true; pair.setEnabled(false); getPreferences(0).edit().putString("server",ip).apply();
            status.setText("Checking the server before switching Wi-Fi…");
            worker.execute(() -> {
                try { readyDevices(ip); main.post(() -> requestSetup(spec,ip,ssid,password)); }
                catch (IOException | JSONException e) { finish("Cannot reach the Linux controller. Connect to your home network and check the server address before pairing."); }
            });
        } catch (IllegalArgumentException e) { status.setText(e.getMessage()); }
    }

    private void requestSetup(WifiNetworkSpecifier spec, String ip, String ssid, String password) {
        if (destroyed) return;
        status.setText("Approve Android’s connection to the strip. This network has no internet.");
        callback = new ConnectivityManager.NetworkCallback() {
            private boolean started;
            @Override public void onAvailable(Network network) {
                if (started) return; started = true;
                worker.execute(() -> provision(network,ip,ssid,password));
            }
            @Override public void onUnavailable() { finish("Setup Wi-Fi unavailable or approval cancelled. Check setup mode and try again."); }
        };
        NetworkRequest request = new NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).setNetworkSpecifier(spec).build();
        try { connectivity.requestNetwork(request,callback,45000); }
        catch (SecurityException | IllegalArgumentException e) { finish("Cannot request setup Wi-Fi. Check Wi-Fi permissions and Location settings on Android 10–12."); }
    }

    private void exchange(Network network, String command, String expected) throws IOException {
        try(Socket socket = network.getSocketFactory().createSocket()) {
            socket.connect(new InetSocketAddress("192.168.1.1",30300),8000); socket.setSoTimeout(8000);
            socket.getOutputStream().write((command+"\r\n").getBytes(StandardCharsets.UTF_8));
            ByteArrayOutputStream reply = new ByteArrayOutputStream();
            int value;
            while(reply.size()<4096 && (value=socket.getInputStream().read())!=-1) { if(value==10) break; if(value!=0) reply.write(value); }
            if(!reply.toString("UTF-8").trim().equals(expected)) throw new IOException("Unacknowledged setup command");
        }
    }

    private void provision(Network network, String ip, String ssid, String password) {
        try {
            main.post(() -> status.setText("Connected to setup Wi-Fi. Sending server address and home Wi-Fi settings…"));
            exchange(network,"up:ip:"+ip,"up:ip:ip_ok");
            exchange(network,"up:connect:"+ssid+":"+password,"up:connect:connect_ok");
        } catch(IOException e) { finish("The strip did not acknowledge pairing. It may have received settings; check the controls before retrying."); return; }
        main.post(() -> { release(); homePassword.setText(""); status.setText("Settings acknowledged. Reconnect to home Wi-Fi if needed. Checking the controller…"); });
        long deadline = System.currentTimeMillis()+90000;
        while(!destroyed && System.currentTimeMillis()<deadline) {
            try {
                Set<String> current = readyDevices(ip);
                String suffix = setupNameSuffix();
                for(String id:current) if(id.endsWith(suffix) && !suffix.isEmpty()) { finish("Pairing verified: your strip is reporting fresh outlet readings. Open outlet controls."); return; }
            } catch(IOException | JSONException ignored) { /* Home network may not have reconnected yet. */ }
            try { Thread.sleep(2500); } catch(InterruptedException e) { Thread.currentThread().interrupt(); return; }
        }
        finish("Settings were acknowledged, but connection was not verified. Rejoin home Wi-Fi and check outlet controls. Do not assume pairing failed.");
    }

    private String setupNameSuffix() {
        return pairingSuffix;
    }
    private String pairingSuffix = "";

    private Set<String> readyDevices(String ip) throws IOException, JSONException {
        HttpURLConnection connection = (HttpURLConnection)new URL("http://"+ip+":8080/api/state").openConnection();
        connection.setConnectTimeout(4000); connection.setReadTimeout(4000);
        try(InputStream input=connection.getInputStream()) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer=new byte[4096]; int n;
            while((n=input.read(buffer))!=-1) { bytes.write(buffer,0,n); if(bytes.size()>262144) throw new IOException("Response too large"); }
            JSONArray devices = new JSONObject(bytes.toString("UTF-8")).getJSONArray("devices");
            Set<String> result=new HashSet<>();
            for(int i=0;i<devices.length();i++) { JSONObject device=devices.getJSONObject(i); if(device.optBoolean("ready")) result.add(device.getString("id").toUpperCase(Locale.ROOT)); }
            return result;
        } finally { connection.disconnect(); }
    }

    private void release() { if(callback!=null) { try { connectivity.unregisterNetworkCallback(callback); } catch(IllegalArgumentException ignored) {} callback=null; } }
    private void finish(String message) { main.post(() -> { if(destroyed)return; release(); running=false; pair.setEnabled(true); status.setText(message); }); }
    @Override protected void onDestroy() { destroyed=true; release(); worker.shutdownNow(); super.onDestroy(); }
}
