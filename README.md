# 🚀 SpaceApps 2026: Astronaut Health Monitoring System

> **Challenge #5:** Create Software for Monitoring Astronaut Health During Space Missions 
> **Event:** NASA Space Apps Challenge 2026  

---

## 📌 Executive Summary
During long-duration missions to the Moon or Mars, astronauts face extreme hazards: cosmic radiation, prolonged isolation, microgravity, and severe physiological stress. In deep space, immediate assistance from Earth is impossible due to communication delays.

This project is an **integrated, real-time astronaut health monitoring system** designed to track vital signs, compute composite stress indices, detect health anomalies early, and provide actionable recommendations directly to the crew and mission control.

---

## 🏗 System Architecture_

The project is structured into independent modules to ensure clear boundaries and scalable development:

```text
 spaceapps-health-monitor/
 ├── 🎨 frontend/      # User Interface & Real-Time Dashboards
 ├── ⚙️ backend/       # Core Business Logic, Storage & API Gateway
 ├── 📊 analytics/     # Telemetry Processing & Anomaly Detection Pipeline
 ├── 📄 report/        # Synthetic-scenario report API and Gemini integration
 └── 📄 docs/          # Project Documentation & Pitch Presentation
```

## Roadmap

The shared, module-by-module development plan, checkpoints, and acceptance criteria are in [docs/ROADMAP.md](./docs/ROADMAP.md).

The presentation brief, product comparison, strengths, architecture, demo flow, and limitations are in [docs/PRESENTATION_REPORT_UK.md](./docs/PRESENTATION_REPORT_UK.md).

## Analytics demo

The synthetic telemetry simulator, nonlinear anomaly detector, JSON contract, and local API are documented in [analytics/README.md](./analytics/README.md).

The Django REST Framework backend setup, authentication, API contract, and analytics bridge are documented in [backend/README.md](./backend/README.md).

The Next.js dashboard setup and end-to-end simulator workflow are documented in [frontend/my-hub/README.md](./frontend/my-hub/README.md).

The separate synthetic-scenario report service, Gemini configuration, and API are documented in [report/README.md](./report/README.md).