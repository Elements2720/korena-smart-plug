# Home Strip for Android

Native Android pairing companion for the MTTL-W01. Requires Android 10 or newer. The owner verified physical pairing on a Samsung S21 FE running Android 16; earlier versions still need device testing.

## Pairing

Start on home Wi-Fi with the Linux controller running. Enter its IPv4 address (default `192.168.1.220`), the strip setup network and password, and your 2.4 GHz home Wi-Fi credentials. Hold the strip's main button for about 10 seconds, then tap **Pair strip** and approve Android's network prompt. Keep the app open. Android 10–12 require location permission and may require Location services enabled; Android 13+ require nearby Wi-Fi permission.

Setup commands use sockets explicitly bound to the strip's Wi-Fi. After configuration acknowledgements, the app releases that network and checks the controller for a ready device whose ID ends with the setup network suffix. This verifies current reporting, not a newly observed device identity. If verification times out, rejoin home Wi-Fi and check controls before repeating pairing.

Passwords are not persisted. The server address is saved. **Open outlet controls** opens the existing browser interface; the app does not host the controller.

## Build on Windows

Use JDK 21 and Android SDK API 36. In a Windows-local copy of this folder, create untracked `local.properties`:

```properties
sdk.dir=C\:/Users/shree/AppData/Local/Android/Sdk
```

From PowerShell with `JAVA_HOME` pointing to your JDK:

```powershell
.\gradlew.bat assembleDebug lintDebug
```

The test APK is `app\build\outputs\apk\debug\app-debug.apk`.

## Release signing

Set `HOME_STRIP_SIGNING_PROPERTIES` to an external properties file containing `storeFile`, `storePassword`, `keyAlias`, and `keyPassword`. Use forward slashes for the keystore path. Keep both this file and the keystore private and backed up; neither belongs in Git.

```powershell
$env:HOME_STRIP_SIGNING_PROPERTIES="$env:USERPROFILE\.home-strip-signing\release-signing.properties"
.\gradlew.bat assembleRelease lintRelease
```

The release APK is `app\build\outputs\apk\release\app-release.apk`. Without signing configuration, a distributable signed release cannot be produced.

The owner's Windows signing files are in `C:\Users\shree\.home-strip-signing`. Back up the entire folder securely. The first release uses a different certificate from the debug APK: uninstall the debug app before installing the release. Subsequent releases must use the same release key and a higher version code.

## Verification

Debug and release assembly and Android lint completed successfully; lint warnings remain. Release APK signature was verified with Android `apksigner`. Physical pairing was verified on Android 16 with the debug build; the release APK still needs installation and a smoke check. No automated Android UI or instrumentation tests have been run.
