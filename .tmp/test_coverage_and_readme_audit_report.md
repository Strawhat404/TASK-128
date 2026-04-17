# Test Coverage Audit

## Project Type Detection
- Declared type: `desktop`.
- Evidence: `repo/README.md` top block (`**Project type:** desktop`).

## Backend Endpoint Inventory
- Endpoint inventory result: **No HTTP endpoints found**.
- Evidence:
  - `repo/README.md` explicitly states no HTTP endpoint layer and no REST/GraphQL routes.
  - HTTP route pattern scan across `repo/backend`, `repo/main.py`, `repo/tests` returned no `Flask/FastAPI/APIRouter/Blueprint/@route` declarations.

## API Test Mapping Table
| Endpoint (`METHOD + PATH`) | Covered | Test Type | Test Files | Evidence |
|---|---|---|---|---|
| None (0 endpoints discovered) | N/A | N/A | N/A | `repo/README.md` architecture section + no route declarations in `repo/backend` |

## API Test Classification
All API-designated files are **Non-HTTP (unit/integration without HTTP)**.

1. `repo/tests/test_api_auth.py` → direct calls to `container.auth.*` (`test_login_success`, `test_bootstrap_admin_creates_user`).
2. `repo/tests/test_api_student.py` → direct calls to `container.students.*` (`test_create_student`, `test_search_by_text`).
3. `repo/tests/test_api_housing.py` → direct calls to `container.housing.*` (`test_assign_bed`, `test_transfer`).
4. `repo/tests/test_api_resource.py` → direct calls to `container.resources.*` (`test_create_resource`, `test_publish_requires_catalog_attachment`).
5. `repo/tests/test_api_catalog.py` → direct calls to `container.catalog.*` (`test_create_and_list_tree`, `test_publish_with_semver`).
6. `repo/tests/test_api_bom.py` → direct calls to `container.bom.*` (`test_create_style`, `test_final_approve_different_user`).
7. `repo/tests/test_api_compliance.py` → direct calls to `container.compliance/evidence/sensitive/violations.*` (`test_creates_employer_and_case`, `test_scan_*`, `test_*violation*`).
8. `repo/tests/test_api_notification.py` → direct calls to `container.notifications.*` (`test_enqueue_creates_queued_messages`, `test_drain_delivers`).
9. `repo/tests/test_api_search.py` → direct calls to `container.search.*` (`test_*global_search*`, `test_save_search*`).
10. `repo/tests/test_api_checkpoint.py` → direct calls to `container.checkpoints.*` (`test_save_and_load`, `test_discard_all`).
11. `repo/tests/test_api_reporting_settings.py` → direct calls to `container.reporting.*`, `container.settings.*` (`test_returns_report`, `test_get_set_roundtrip`).

Classification totals:
- True No-Mock HTTP: **0**
- HTTP with Mocking: **0**
- Non-HTTP: **11 files**

## Mock Detection
Detected stubbing/overrides (non-HTTP context):
1. Environment/fixture patching via `monkeypatch` in `repo/tests/conftest.py` (`container` fixture).
2. Additional `monkeypatch` branch tests in `repo/tests/test_unit_core.py` (`_isolate_config`, `test_db_path_override`).
3. `monkeypatch` branch tests in `repo/tests/test_unit_branches.py` (`test_key_truncated_to_32_when_file_larger`, `test_db_path_override_via_env`, etc.).
4. Source-policy assertions against unsafe flag in:
   - `repo/tests/test_security_controls.py` (`test_update_tab_does_not_pass_allow_unsigned`)
   - `repo/tests/test_frontend_widgets.py` (`test_updater_tab_no_allow_unsigned_in_source`)

Not detected:
- `jest.mock`, `vi.mock`, `sinon.stub`, `TestClient`, `requests/httpx` HTTP transport tests.

## Coverage Summary
- Total endpoints: **0**
- Endpoints with HTTP tests: **0**
- Endpoints with TRUE no-mock HTTP tests: **0**
- HTTP coverage %: **N/A (no HTTP endpoint surface)**
- True API coverage %: **N/A (no HTTP endpoint surface)**

## Unit Test Summary

### Backend Unit Tests
Backend unit test files (current):
1. `repo/tests/test_unit_crypto.py`
2. `repo/tests/test_unit_core.py`
3. `repo/tests/test_unit_app_models.py`
4. `repo/tests/test_unit_db.py`
5. `repo/tests/test_unit_branches.py`

Modules covered:
- Controllers: N/A (no controller/router layer present).
- Services: auth, student, housing, resource, catalog, bom, compliance, compliance_ext, notification, reporting, settings, search, checkpoint, updater (via `test_api_*`, integration, e2e, security tests).
- Repositories/data layer: `backend/db.py` now directly unit-tested (`repo/tests/test_unit_db.py`, `repo/tests/test_unit_branches.py`).
- Auth/guards/middleware equivalents: `backend/permissions.py` covered (`repo/tests/test_unit_core.py`, `repo/tests/test_permissions.py`, `repo/tests/test_unit_branches.py`).

Important backend modules not strongly direct-unit tested:
1. `repo/backend/app.py` GUI bootstrap/runtime branch behavior beyond import/wiring checks.
2. `repo/backend/services/__init__.py` (barrel export; low risk).

### Frontend Unit Tests
Frontend test files:
1. `repo/tests/test_frontend_widgets.py`
2. `repo/tests/test_ui_smoke.py`

Frameworks/tools detected:
- `pytest` (`def test_*` in both files)
- `PyQt6` imports in both files
- `pytest-qt` compatibility path in `test_ui_smoke.py` (`pytestqt`, `qtbot` shim/fixture flow)

Components/modules covered (direct imports/assertions):
1. `frontend/main_window.py`
2. `frontend/dialogs.py`
3. `frontend/tabs_extra.py`
4. `frontend/widgets/results_table.py`
5. `frontend/widgets/search_palette.py`
6. `frontend/windows/student_profile.py`
7. `frontend/style.qss`

Important frontend components/modules not deeply tested:
1. System-tray lifecycle edge cases under real OS integration (tests are static/headless-focused).
2. Some long multi-step UI workflows still rely more on smoke/assertion-level checks than full interaction-path assertions.

Mandatory verdict: **Frontend unit tests: PRESENT**

### Cross-Layer Observation
- Desktop FE+BE test balance is materially improved: backend has broad service + new branch-level unit coverage, and frontend has extensive PyQt component/window/tab tests.
- No backend-heavy/frontend-empty imbalance detected.

## API Observability Check
- Result: **WEAK for HTTP observability (structurally N/A)**.
- Evidence: tests do not exercise `METHOD + PATH`; they invoke service methods directly via `container.<service>.<method>`.

## Tests Check
- Success paths: present across service APIs and UI components.
- Failure cases: present (validation errors, permission denied, weak password, signature rejection, compliance gates).
- Edge cases: present (crypto branches, audit-chain corruption detection, db corruption/reseal/reset branches, cron and retry behavior).
- Validation/auth/permissions: present in `test_api_*`, `test_permissions.py`, `test_security_controls.py`.
- Integration boundaries: present in `test_integration_flow.py`, `test_e2e_workflows.py`, `test_e2e_desktop.py`.
- Assertion depth: mostly meaningful and state-based.
- `run_tests.sh`: Docker-based delegation and in-container execution; local runtime dependency install is not required.

## Test Coverage Score (0–100)
- **91/100**

## Score Rationale
- Upward change supported by new direct branch/data-layer unit coverage (`test_unit_db.py`, `test_unit_branches.py`) and expanded frontend widget/window/tab assertions.
- Deduction remains for strict endpoint-based HTTP criteria: no HTTP API layer exists, so true HTTP endpoint coverage is unavailable by architecture.

## Key Gaps
1. No HTTP endpoint layer; endpoint-level API coverage metrics remain inapplicable.
2. `backend/app.py` runtime GUI failure-path branches are less directly unit-tested than other core modules.
3. Some UI workflows remain smoke-level rather than deeply event-sequenced.

## Confidence & Assumptions
- Confidence: **High**.
- Assumptions:
  - Static-only audit; no runtime/test execution performed.
  - Current repository state at audit time is authoritative.

## Test Coverage Verdict
- **PASS** (strong for current desktop architecture; HTTP endpoint criteria structurally not applicable).

---

# README Audit

## README Location
- Required file `repo/README.md`: **Present**.

## Hard Gate Evaluation

### Formatting
- **PASS**.
- Evidence: structured markdown headings, tables, command blocks.

### Startup Instructions
- Project type is `desktop`; desktop run/build instructions are present.
- **PASS**.
- Evidence: `docker compose build`, `docker compose up app`, optional headless run command.

### Access Method
- **PASS**.
- Evidence: desktop launch behavior and interaction guidance (keyboard shortcuts, tray behavior).

### Verification Method
- **PASS**.
- Evidence: explicit verification commands (`docker compose run --rm app python verify.py`, `./run_tests.sh`, in-container pytest command).

### Environment Rules (STRICT)
- **PASS**.
- Evidence: README states Docker/Compose are the only local prerequisites; no local `npm install` / `pip install` / `apt-get` runtime setup instructions.

### Demo Credentials (Conditional Auth Gate)
- Auth exists and credentials are explicitly documented.
- **PASS**.
- Evidence: bootstrap/sign-in credentials (`admin` / `DemoPassw0rd!`) plus role list (`system_admin`, `housing_coordinator`, `academic_admin`, `compliance_reviewer`, `operations_analyst`).

## Engineering Quality
- Tech stack clarity: strong.
- Architecture explanation: strong (diagram + FE/BE boundary + service list).
- Testing instructions: strong and reproducible.
- Security/roles/workflows: explicit and operationally clear.
- Presentation quality: high readability.

## High Priority Issues
- None.

## Medium Priority Issues
- None.

## Low Priority Issues
1. “API tests” terminology may be misread as HTTP API tests despite explicitly documented in-process service architecture.

## Hard Gate Failures
- None.

## README Verdict
- **PASS**.

---

## Final Combined Verdicts
1. **Test Coverage Audit:** PARTIAL PASS
2. **README Audit:** PASS
