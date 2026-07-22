# Loobric Server

> Application-agnostic REST API and database for tool data synchronization across CAM systems, CNC machines, and tool rooms.

[![License](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)


## Overview

Loobric Server is the central REST API and database system that provides a unified interface for managing tool data across manufacturing systems. It's designed to bridge the gap between CAM software, CNC machines, and tool rooms with a focus on real-time synchronization and data integrity.

### Key Features

- **RESTful API** with bulk operations for efficient data handling
- **Multi-tenant Architecture** with automatic data isolation
- **Security built in**: role-based access control, tag-scoped API keys, immutable audit log
- **Change detection** by version or timestamp for efficient client sync
- **Backup and restore** with versioned tool set history and rollback
- **Developer-Friendly** with OpenAPI documentation and a CLI

Planned work (standards import, more clients, hosted offering) lives in [ROADMAP.md](ROADMAP.md) — this README only claims what runs today.

## Quick Start Documentation

- [For Users and the curious](docs/QUICK_START.md)
- [For Developers](docs/DEVELOPMENT.md)

## How-to guides

Task-oriented walkthroughs for linking a CNC control and a CAM tool set:

- [Build a CAM tool set from your machine's tools](docs/HOWTO_BUILD_CAM_SET_FROM_MACHINE.md)
  — the machine has the tools; get them into your CAM tool set (control → CAM).
- [Match a machine and a CAM tool set you built separately](docs/HOWTO_MATCH_MACHINE_AND_CAM_TOOLS.md)
  — both sides exist; link them by identity and inherit the machine's numbering.
- Coming soon: the reverse direction (CAM → control) — push a CAM tool set down
  to a machine.

## Getting Help

- **Issues**: If you encounter any problems, please [open an issue](https://github.com/loobric/loobric-server/issues).
- **Discussion**: For questions and discussions, use [GitHub Discussions](https://github.com/loobric/loobric-server/discussions).

## Clients

This project was started out of a personal need to synchronize linuxcnc machine control with FreeCAD CAM workbenches. As such, these are the reference implementations of clients.  Additional clients are welcome and encouraged.

### **loobric-freecad** - FreeCAD CAM workbench integration

[loobric-freecad](https://github.com/loobric/loobric-freecad)

### **loobric-linuxcnc** - LinuxCNC controller integration

[loobric-linuxcnc](https://github.com/loobric/loobric-linuxcnc)

### **loobric-cli** - Python library and CLI

The reference Python client — an importable `Client` library and the `loobric_server`
command-line client. Lives in its own repo:
[loobric-cli](https://github.com/loobric/loobric-cli) (`pip install loobric-cli`).

## Contributing

We welcome contributions! Please see our [Contributing Guide](docs/CONTRIBUTING.md) for details on how to get started.