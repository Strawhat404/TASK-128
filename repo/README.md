# CRHGC — Collegiate Resource & Housing Governance Console

**Project type:** desktop

Offline desktop application for US-based education providers to administer
student housing records, an academic resource catalog, and employer
onboarding/compliance — with a notification center, universal search,
encrypted local SQLite storage, and an immutable, hash-chained audit log.

The UI is built with **PyQt6** (keyboard-first, multi-window, system-tray
present) targeting **Windows 11**. The application also runs on Linux/macOS
for development.

## Architecture

```
                     +-----------------------+
                     |   PyQt6 GUI (frontend) |
                     |   MainWindow, Dialogs, |
                     |   Widgets, Tabs        |
                     +----------+------------+
                                |
                     +----------v------------+
                     |  Service Layer         |
                     |  (backend/services/)   |
                     |  Auth, Student, Housing|
                     |  Resource, Catalog,    |
                     |  Compliance, BOM,      |
                     |  Notification, Search, |
                     |  Reporting, Settings,  |
                     |  Checkpoint, Updater   |
                     +----------+------------+
                                |
              +-----------------+-----------------+
              |                 |                 |
     +--------v------+ +-------v-------+ +-------v-------+
     | Permissions    | | Event Bus     | | Audit Log     |
     | (RBAC guards) | | (pub/sub)     | | (hash-chained)|
     +--------+------+ +-------+-------+ +-------+-------+
              |                 |                 |
              +--------+--------+---------+-------+
                       |                  |
              +--------v--------+ +-------v-------+
              | Crypto (AES-GCM)| | SQLite + enc  |
              | field & at-rest | | (backend/db)  |
              +-----------------+ +---------------+
```

- **No HTTP endpoint layer.** The GUI communicates with the backend
  through direct in-process Python method calls on service objects
  (wired by `backend.app.Container`). There are no REST/GraphQL routes.
- **FE-BE boundary** is the `Container` instance passed into `MainWindow`.

## Repository Layout

```
repo/
+-- backend/            # Python service layer, persistence, crypto, events
|   +-- services/       # 14 service modules (auth, student, housing, ...)
|   +-- models/         # Shared DTOs and dataclasses
|   +-- app.py          # Container wiring, startup profiling
|   +-- db.py           # SQLite connection, migrations, at-rest encryption
|   +-- crypto.py       # AES-GCM field encryption, password hashing
|   +-- audit.py        # Append-only hash-chained audit log
|   +-- permissions.py  # RBAC Session, decorators
|   +-- events.py       # In-process event bus
|   +-- config.py       # Paths, tunables, constants
+-- frontend/           # PyQt6 windows, widgets, dialogs, stylesheet
|   +-- main_window.py  # MainWindow, tab widgets
|   +-- dialogs.py      # Login, Bootstrap, Unlock dialogs
|   +-- tabs_extra.py   # Catalog, Evidence, BOM, Updater tabs
|   +-- widgets/        # ResultsTable, SearchPalette
|   +-- windows/        # StudentProfileWindow (detached)
+-- database/
|   +-- migrations/     # SQL migrations (0001..0007)
|   +-- seed/           # seed_dev.sql, seed_extras.sql
+-- tests/              # pytest suite (unit, API, E2E, frontend)
+-- installer/          # Windows MSI installer scripts
+-- main.py             # GUI entry point
+-- verify.py           # Headless verification script (17 checks)
+-- Dockerfile          # Container image with all runtime deps
+-- docker-compose.yml  # App + test profiles
+-- run_tests.sh        # Unified test runner (delegates to Docker)
+-- requirements.txt
+-- README.md
```

## Prerequisites

- **Docker** and **Docker Compose** (v2) are the only local requirements.
- All runtime dependencies (Python 3.12, PyQt6, cryptography, pytest, Xvfb)
  are installed inside the Docker image at build time.
- No local `pip install` is needed.

## Setup and Startup

### 1. Build the container image

```bash
cd repo
docker compose build
```

This installs all dependencies from `requirements.txt` inside the image.

### 2. Launch the GUI (with X11 forwarding)

```bash
docker compose up app
```

Or run headless (no GUI, backend + verify only):

```bash
docker compose run --rm app python verify.py
```

### 3. First-run bootstrap and demo credentials

On the very first launch the database is empty. The application:

1. Creates the per-user data directory.
2. Applies SQLite migrations and seeds demo data (roles, permissions,
   buildings, rooms, beds, notification templates).
3. Opens a **Bootstrap dialog** prompting for the first administrator.

Use the following demo credentials to bootstrap and sign in:

| Step | Field | Value |
|------|-------|-------|
| Bootstrap (first run) | Full name | `Demo Admin` |
| | Username | `admin` |
| | Password | `DemoPassw0rd!` |
| Sign in | Username | `admin` |
| | Password | `DemoPassw0rd!` |

**Roles available after bootstrap:**

| Role | Permissions |
|------|-------------|
| `system_admin` | All permissions (full access) |
| `housing_coordinator` | `housing.write`, `student.pii.read` |
| `academic_admin` | `resource.write`, `resource.publish` |
| `compliance_reviewer` | `compliance.review`, `compliance.violation` |
| `operations_analyst` | `report.read`, `report.export` |

The bootstrapped user is automatically assigned `system_admin`.

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+K` | Universal search palette |
| `Ctrl+Shift+N` | Create new record (context-sensitive) |
| `Ctrl+E` | Export current result set |
| `Ctrl+L` | Lock session |
| `Ctrl+,` | Settings |
| `Esc` | Close active dialog / detached window |
| `F1` | About dialog |

### System tray

When you close the main window the app minimizes to the system tray; the
notification dispatcher continues to run. Right-click the tray icon for
*Open*, *Search...*, *Lock*, and *Quit*.

## Verification

### Headless smoke test

A scripted, headless smoke test exercises the major service flows
(bootstrap, login, masked PII reveal, bed assignment with triggered
notification, resource publishing, compliance approval, universal search,
audit chain verification, and occupancy reporting):

```bash
docker compose run --rm app python verify.py
```

Exit code is `0` on full success, `1` otherwise.

### Full test suite (containerized)

All tests run inside Docker with no local dependencies:

```bash
./run_tests.sh
```

This delegates to `docker compose --profile test run --rm test`, which:

1. Starts Xvfb for headless Qt rendering.
2. Runs `verify.py` (headless service flow checks).
3. Runs the full `pytest` suite.

Alternatively, run the pytest suite directly inside the container:

```bash
docker compose run --rm app python -m pytest -q --tb=short
```

### Test suite structure

The `tests/` directory contains a comprehensive pytest suite organized into:

| Category | Files | Scope |
|----------|-------|-------|
| **Unit tests** | `test_unit_crypto.py`, `test_unit_core.py`, `test_unit_app_models.py` | Crypto, config, events, permissions, Container boot, dataclass contracts |
| **Service API tests** | `test_api_auth.py`, `test_api_student.py`, `test_api_housing.py`, `test_api_resource.py`, `test_api_catalog.py`, `test_api_bom.py`, `test_api_compliance.py`, `test_api_notification.py`, `test_api_search.py`, `test_api_checkpoint.py`, `test_api_reporting_settings.py` | Every service method: success paths, error/validation paths, permission denial |
| **Security controls** | `test_security_controls.py`, `test_updater_signature.py`, `test_permissions.py`, `test_audit_redaction.py` | Evidence gates, fail-closed scanner, at-rest encryption, RSA signature enforcement, PII redaction |
| **Integration / E2E** | `test_e2e_workflows.py`, `test_e2e_desktop.py`, `test_integration_flow.py`, `test_governance_publish.py` | Multi-service lifecycle flows, seal/reopen round-trips, desktop packaging simulation |
| **Frontend** | `test_frontend_widgets.py`, `test_ui_smoke.py` | Dialog construction, widget rendering, search palette, student profile window, tab visibility, MainWindow boot |
| **Data I/O** | `test_xlsx_io.py`, `test_search_hidden_employers.py`, `test_scheduled_notifications.py` | Excel round-trip, employer visibility, cron rule firing |

Tests use isolated per-test SQLite databases via the `container` fixture
(`tests/conftest.py`). No external services or network access required.

## Feature Summary

- **Students & Housing** — CRUD, bulk CSV/XLSX import/export, bed
  assignment/vacancy/transfer, PII encryption (AES-GCM), masked field
  reveal with timed re-authentication.
- **Resource Catalog** — hierarchical folder tree, custom types with
  metadata templates (text/int/date/enum/url/file/markdown, regex
  validation, required flags), tags, relationships, reviewer approval,
  semantic-version bumps on publish.
- **Compliance** — employer onboarding cases, evidence file upload with
  SHA-256 fingerprints and 7-year retention, offline sensitive-word scanner
  (fail-closed), violation actions (`takedown`, `suspend`, `throttle`).
- **Styles / BOM / Routing** — multi-version BOM and process routing with
  two-step approval (first + final must be different users), automatic cost
  recalculation with audit trail, change requests against released versions.
- **Notifications** — template-based messaging, event-driven trigger rules,
  cron-scheduled rules, delivery queue with 3-attempt retry budget,
  dead-letter surfacing.
- **Search** — universal full-text search across students, resources,
  employers, and cases with synonym expansion, fuzzy matching, saved
  searches, and pinned sidebar.
- **Crash recovery** — workspace state persisted every 60 s, unsaved form
  drafts checkpointed and offered for restoration on next launch.
- **Updater** — import signed offline update packages (ZIP + RSA-PSS
  signature). DB snapshot taken before each apply; any package can be
  rolled back from the *Updates* tab. Unsigned packages are rejected at
  every layer (no UI bypass).
- **Audit log** — every mutating operation appends a row whose `this_hash`
  is `SHA-256(prev_hash || canonical_json(payload))`. Run
  `audit.verify_chain()` or the `verify.py` script to confirm integrity.

## Notes

- **At-rest encryption.** Sensitive fields (email, phone, SSN-last4) are
  encrypted with AES-GCM via the `cryptography` library, using a 32-byte
  key stored in the per-user data directory. If `cryptography` is missing,
  the application falls back to an obfuscation cipher and emits a warning
  — do not rely on this for production data.
- **Masked fields** are revealed only after a fresh password re-entry; the
  reveal expires after 5 minutes (configurable in `backend/config.py`).
- **Notification retries.** Failed local-queue writes are retried up to 3
  times at 5-minute intervals; persistently failing messages move to a
  dead-letter state surfaced in the *Notifications* tab.

## Uninstall / Reset

Delete the data directory (default `%LOCALAPPDATA%\CRHGC` on Windows or
`~/.local/share/CRHGC` on Linux) to wipe all local state, including the
encryption key. Or remove the Docker volume:

```bash
docker compose down -v
```
