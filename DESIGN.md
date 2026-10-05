---
name: Home Strip
description: Light home-network outlet controls
colors:
  canvas: "#eef2f4"
  surface: "#ffffff"
  surface-muted: "#f5f7f8"
  ink: "#182d38"
  muted: "#526570"
  line: "#d4dfe4"
  control-line: "#7e929b"
  active: "#11664c"
  active-soft: "#e9f4ee"
  warning: "#805109"
  warning-soft: "#fff4df"
  error: "#9d302c"
  error-soft: "#fcedeb"
typography:
  heading:
    fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif'
    fontSize: "clamp(28px, 4vw, 40px)"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.035em"
  body:
    fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif'
    fontSize: "16px"
    lineHeight: 1.55
rounded:
  panel: "20px"
  outlets: "14px"
  button: "9px"
components:
  power-button-on:
    backgroundColor: "{colors.active}"
    textColor: "{colors.surface}"
    rounded: "{rounded.button}"
  power-button-off:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.button}"
---

## Overview
The user chose a light outlet panel, ordered like the physical strip on desktop and stacked on phones. Control state and task clarity govern the interface. Extracted from `static/style.css` after desktop and mobile review.

## Colors
Active green is reserved for confirmed on states and successful commands. Warning tones indicate pending or stale state; error tones indicate failed requests. State also has a text label.

## Typography
System UI fonts avoid external font requests on the home LAN. Measurements use tabular numerals. Monospace is restricted to commands and setup credentials.

## Layout
Content has a 1104px maximum width with 32px desktop gutters. Outlets form one four-column panel, become two columns at 880px, and become stacked rows at 580px. The phone layout uses 20px outer gutters; telemetry becomes two columns. Setup steps follow reading order in a two-column desktop layout and a single-column mobile layout.

## Elevation & Depth
A single subtle offset shadow distinguishes the main panel from the canvas. Outlet divisions use borders and tonal state, not separate nested cards.

## Shapes
Rounded panel corners soften the control surface; buttons have a smaller radius. Socket diagrams share the outlined stroke language of the plug, Wi-Fi, and power symbols.

## Components
Power buttons are keyboard-operable switches with a minimum 48px height. Group actions have a minimum 44px height. Visible focus uses the active color with an outline offset. State is not optimistically switched; pending commands disable controls until a result arrives. Reduced motion removes transitions.

## Do's and Don'ts
- Keep the four outlet numbers in physical order.
- Preserve actual reported values and show unknown readings as a dash.
- Keep stale/disconnected readings clearly labeled and disable unavailable controls.
- Use text alongside state colors and preserve the native button semantics.
- Keep setup credentials on the provisioning computer; do not add them to the web API.
