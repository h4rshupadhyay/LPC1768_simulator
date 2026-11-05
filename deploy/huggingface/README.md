---
title: Lpc1768 Simulator
emoji: ⚡
colorFrom: purple
colorTo: purple
sdk: gradio
sdk_version: 6.31.0
python_version: '3.12'
app_file: app.py
pinned: false
short_description: LPC1768 kit simulator backend with a 3D Workbench
---

# LPC1768 Simulator backend

Backend for https://lpc-1768-simulator-extended.vercel.app: compiles Embedded C for an
emulated Cortex-M3 and simulates the ALS LPC1768 kit and external parts.

`app.py` clones https://github.com/KavyPings/LPC1768_simulator_extended at startup and
serves its API in public mode (one simulator per visitor, restricted compilation).
Restart the Space to pick up new commits.
