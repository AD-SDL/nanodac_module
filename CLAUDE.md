# AGENTS.md/CLAUDE.md

This file provides guidance to AI agents. Note that CLAUDE.md and AGENTS.md are symlinked together.

## Overview

MADSci node module for the **Eurotherm nanodac** temperature/process controller. Exposes a FastAPI REST server (via MADSci's `RestNode`) that translates MADSci actions into **Modbus/TCP** reads/writes to the instrument. Built for APS beamline 9-BM.

## Installation and Running

```bash
# Install (creates .venv, installs deps + dev group)
pdm install

# Run the REST node
pdm run python -m nanodac_rest_node

# Or via Docker
docker compose up
```

Configuration is loaded via MADSci's walk-up settings discovery (`node.settings.yaml` / `settings.yaml` / env vars). At minimum set `nanodac_ip` (or the `NODE_NANODAC_IP` env var).

## Linting

```bash
ruff check src/
ruff format src/
pre-commit run --all-files
```

`docs/Configuration.md` and `.env.example` are **auto-generated** from `NanodacNodeConfig` by `pydantic-settings-export` (wired into `pyproject.toml` and a pre-commit hook) — do not edit them by hand; regenerate with `pdm run pydantic-settings-export`.

## Code Architecture

Two layers:

### 1. `src/nanodac_rest_node.py` — MADSci REST node
`NanodacNode(RestNode)`:
- `startup_handler` opens the Modbus connection (instantiates `Nanodac`) and raises on failure, so the framework marks the node errored rather than falsely "ready".
- `state_handler` polls the loop and publishes `node_state` (`nanodac_status_code`, temperature, setpoints, output, mode).
- Actions (`@action`): `get_temperature`, `get_setpoint`, `set_temperature`, `get_output` — each accepts an optional `loop` (1 or 2).
- Config via `NanodacNodeConfig(RestNodeConfig)`: `nanodac_ip`, `nanodac_port` (502), `unit_id` (1), `loop` (1).
- **No MADSci resource tracking** — this is a simple device.

### 2. `src/nanodac_interface.py` — driver
`Nanodac` — pure Modbus/TCP via `pymodbus`, no MADSci dependency (reusable by any orchestrator). Methods: `connect` / `disconnect`, `get_status`, and `get_temperature` / `get_target_temperature` / `get_working_setpoint` / `get_output` / `get_mode` / `set_temperature`.

## nanodac Modbus specifics (confirmed on firmware v5.50)

- Loop.1.Main is at **base address 512** (Loop.2 at 640, +128 apart) — NOT the canonical register 1. Verified via iTools Parameter Explorer.
- REAL (float) parameters are read through the **IEEE float mirror**: `int_address + 0x8000`, two 16-bit registers, big-endian high-word-first.
- An unwritten float reads back as the sentinel `(0x0000, 0x8000)` (~4.59e-41), mapped to `None`.
- Bool/enum params (AutoMan, Inhibit, IntHold) are plain 1-register int reads.
- `pymodbus` calls use `device_id=` (with a `slave=` fallback for older versions).

### Known limitation: setpoint writes
`set_temperature` is **experimental / unverified** on v5.50. The IEEE float mirror rejects writes (Modbus `exception_code=2`, illegal data address), and writing the scaled integer at the base address is accepted but does not cleanly/consistently drive the setpoint. The correct writable SP parameter and scaling need confirmation via the Eurotherm nanodac comms manual (**HA030554**) and iTools (watch TargetSP while writing; check SP-select / SP-rate / comms write-enable). Reads are fully validated.

## Notes
- Python 3.10–3.12.
- Use `pdm` for dependency management; the MADSci packages (`madsci-node-module`, `madsci-common`, `madsci-client`) are on PyPI.
- On a private-subnet host with no direct internet, install through a SOCKS proxy: `export ALL_PROXY=socks5h://<proxy-host>:<port>` (and `HTTP(S)_PROXY`).
