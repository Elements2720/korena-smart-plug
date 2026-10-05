# Home Strip

<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
User-selected: Python standard library with plain HTML, CSS, and JavaScript.

## Users
The owner of an MTTL-W01 power strip, controlling it from browsers at home.

## Product Purpose
Connect the strip to a Linux server and switch its four outlets from the home network.

## Operating Context
The user has a Linux server connected to the router and a Windows PC. The strip broadcasts `TONLY_TAP_935CA80`. Setup happens from a Wi-Fi-capable device; the Linux server can remain on Ethernet.

## Capabilities and Constraints
Home-network access only. The strip uses 2.4 GHz Wi-Fi. Its reported stock protocol connects outward to a provisioned IPv4 address on TCP 10086; setup uses TCP 30300. These protocol details come from public research, and compatibility with the user's actual firmware remains unverified. The Linux server runs Lubuntu at `192.168.1.220`; its login username is not yet known.

## Evidence on Hand
Protocol reference: https://github.com/ahmedtohamy1/powerk . No physical-device verification has been performed.

## Product Principles
- Show confirmed device state, not guessed switch positions.
- Distinguish disconnected, stale, and unconfirmed commands.
- Keep deployment dependency-free and pairing usable from Windows.
