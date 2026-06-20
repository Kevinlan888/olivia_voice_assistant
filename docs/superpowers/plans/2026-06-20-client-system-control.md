# Client System Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a client-side `system_control` capability for the Raspberry Pi client, expose it through a local HTTP API, and prepare a clean path for future voice-triggered client control.

**Architecture:** Keep all privileged system execution on the client. Add a client-local domain/service layer for system control, then expose that through a client-local HTTP API. Defer server-to-client control dispatch to a later task so the first working increment is a stable local control backend for both future frontend and voice integration.

**Tech Stack:** Python 3, FastAPI, subprocess/`amixer`, unittest

---

## File Structure

### New files

- `client/system_control/models.py`
  Shared request/response/state/capability data models.
- `client/system_control/executor.py`
  Abstract executor interface and shared executor utilities.
- `client/system_control/amixer_executor.py`
  Concrete Seeed audio control executor based on `amixer`.
- `client/system_control/service.py`
  Action validation and dispatch layer reused by HTTP and future WebSocket control paths.
- `client/local_api/app.py`
  Client-local FastAPI app exposing `capabilities`, `state`, and `control`.
- `tests/test_system_control_service.py`
  Unit tests for request validation, capability reporting, and action dispatch.
- `tests/test_amixer_executor.py`
  Unit tests for `amixer` command generation and output parsing.
- `tests/test_local_api.py`
  API tests for client-local HTTP routes.

### Modified files

- `client/config.py`
  Add client-local system control configuration such as Seeed card/mixer identifiers and local API bind settings.
- `client/main.py`
  Optionally start/stop the local API alongside the client process, or wire in a bootstrap hook if the team prefers explicit startup.
- `client/__init__.py`
  Only if needed for package-level imports; otherwise leave untouched.

### Future-phase files

- `server/tools/system_control.py`
- `server/tools/__init__.py`
- `server/agents/smart_home_agent.py`
- `server/main.py`
- `client/ws_client.py`

These are intentionally excluded from the first working increment unless the human explicitly asks to implement the server dispatch phase immediately.

---

### Task 1: Add the shared client system-control models

**Files:**
- Create: `client/system_control/models.py`
- Modify: `client/config.py`
- Test: `tests/test_system_control_service.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from client.system_control.models import ControlRequest


class TestControlRequest(unittest.TestCase):
    def test_audio_set_volume_request_keeps_domain_action_target(self):
        req = ControlRequest(
            domain="audio",
            action="set_volume",
            target="seeed_output",
            params={"percent": 50},
        )

        self.assertEqual(req.domain, "audio")
        self.assertEqual(req.action, "set_volume")
        self.assertEqual(req.target, "seeed_output")
        self.assertEqual(req.params["percent"], 50)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_system_control_service.TestControlRequest.test_audio_set_volume_request_keeps_domain_action_target -v`
Expected: FAIL with `ModuleNotFoundError` for `client.system_control.models`

- [ ] **Step 3: Write minimal implementation**

```python
from dataclasses import dataclass, field


@dataclass
class ControlRequest:
    domain: str
    action: str
    target: str
    params: dict = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_system_control_service.TestControlRequest.test_audio_set_volume_request_keeps_domain_action_target -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/system_control/models.py client/config.py tests/test_system_control_service.py
git commit -m "feat: add client system control models"
```

---

### Task 2: Add the abstract executor and the Seeed `amixer` executor

**Files:**
- Create: `client/system_control/executor.py`
- Create: `client/system_control/amixer_executor.py`
- Modify: `client/config.py`
- Test: `tests/test_amixer_executor.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from unittest.mock import patch

from client.system_control.amixer_executor import AmixerSystemExecutor


class TestAmixerExecutor(unittest.TestCase):
    @patch("client.system_control.amixer_executor.subprocess.run")
    def test_set_volume_uses_explicit_card_and_mixer(self, mock_run):
        mock_run.return_value.stdout = "Mono: Playback 50 [50%] [-20.00dB] [on]"
        executor = AmixerSystemExecutor(card="seeed2micvoicec", mixer="Playback")

        executor.set_volume(50)

        args = mock_run.call_args[0][0]
        self.assertEqual(args, ["amixer", "-c", "seeed2micvoicec", "sset", "Playback", "50%"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_amixer_executor.TestAmixerExecutor.test_set_volume_uses_explicit_card_and_mixer -v`
Expected: FAIL with `ModuleNotFoundError` for `client.system_control.amixer_executor`

- [ ] **Step 3: Write minimal implementation**

```python
import subprocess


class AmixerSystemExecutor:
    def __init__(self, card: str, mixer: str):
        self.card = card
        self.mixer = mixer

    def set_volume(self, percent: int):
        subprocess.run(
            ["amixer", "-c", self.card, "sset", self.mixer, f"{percent}%"],
            check=True,
            capture_output=True,
            text=True,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_amixer_executor.TestAmixerExecutor.test_set_volume_uses_explicit_card_and_mixer -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/system_control/executor.py client/system_control/amixer_executor.py client/config.py tests/test_amixer_executor.py
git commit -m "feat: add amixer-based client system executor"
```

---

### Task 3: Add the client system-control service layer

**Files:**
- Create: `client/system_control/service.py`
- Modify: `client/system_control/models.py`
- Modify: `client/system_control/amixer_executor.py`
- Test: `tests/test_system_control_service.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from client.system_control.models import ControlRequest
from client.system_control.service import SystemControlService


class _FakeExecutor:
    def set_volume(self, percent: int):
        return {"volume_percent": percent, "muted": False}


class TestSystemControlService(unittest.TestCase):
    def test_service_dispatches_audio_set_volume(self):
        service = SystemControlService(executor=_FakeExecutor())
        result = service.execute(
            ControlRequest(
                domain="audio",
                action="set_volume",
                target="seeed_output",
                params={"percent": 35},
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["volume_percent"], 35)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_system_control_service.TestSystemControlService.test_service_dispatches_audio_set_volume -v`
Expected: FAIL with `ModuleNotFoundError` for `client.system_control.service`

- [ ] **Step 3: Write minimal implementation**

```python
class SystemControlService:
    def __init__(self, executor):
        self._executor = executor

    def execute(self, request):
        if request.domain == "audio" and request.action == "set_volume":
            state = self._executor.set_volume(int(request.params["percent"]))
            return {
                "ok": True,
                "domain": request.domain,
                "action": request.action,
                "target": request.target,
                "state": state,
            }
        return {
            "ok": False,
            "domain": request.domain,
            "action": request.action,
            "target": request.target,
            "error": {"code": "unsupported_action", "message": "unsupported action"},
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_system_control_service.TestSystemControlService.test_service_dispatches_audio_set_volume -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/system_control/service.py client/system_control/models.py client/system_control/amixer_executor.py tests/test_system_control_service.py
git commit -m "feat: add client system control service"
```

---

### Task 4: Add the client-local HTTP API

**Files:**
- Create: `client/local_api/app.py`
- Modify: `client/system_control/service.py`
- Modify: `client/config.py`
- Test: `tests/test_local_api.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from fastapi.testclient import TestClient

from client.local_api.app import create_app


class _FakeService:
    def capabilities(self):
        return {"implemented": ["audio.set_volume"]}


class TestLocalAPI(unittest.TestCase):
    def test_capabilities_route_returns_json(self):
        app = create_app(system_service=_FakeService())
        client = TestClient(app)

        response = client.get("/api/system/capabilities")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["implemented"], ["audio.set_volume"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_local_api.TestLocalAPI.test_capabilities_route_returns_json -v`
Expected: FAIL with `ModuleNotFoundError` for `client.local_api.app`

- [ ] **Step 3: Write minimal implementation**

```python
from fastapi import FastAPI


def create_app(system_service):
    app = FastAPI()

    @app.get("/api/system/capabilities")
    def get_capabilities():
        return system_service.capabilities()

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_local_api.TestLocalAPI.test_capabilities_route_returns_json -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/local_api/app.py client/system_control/service.py client/config.py tests/test_local_api.py
git commit -m "feat: add client local system control api"
```

---

### Task 5: Complete the first implemented audio actions and state routes

**Files:**
- Modify: `client/system_control/amixer_executor.py`
- Modify: `client/system_control/service.py`
- Modify: `client/system_control/models.py`
- Modify: `client/local_api/app.py`
- Test: `tests/test_amixer_executor.py`
- Test: `tests/test_system_control_service.py`
- Test: `tests/test_local_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_state_route_returns_current_audio_state(self):
    class _FakeService:
        def state(self):
            return {
                "audio": {
                    "output": {"device": "seeed_output"},
                    "volume": {"percent": 55, "muted": False},
                },
                "client": {"connected_to_server": True},
            }

    app = create_app(system_service=_FakeService())
    client = TestClient(app)

    response = client.get("/api/system/state")

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()["audio"]["volume"]["percent"], 55)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_local_api.TestLocalAPI.test_state_route_returns_current_audio_state -v`
Expected: FAIL with `404 != 200`

- [ ] **Step 3: Write minimal implementation**

```python
    @app.get("/api/system/state")
    def get_state():
        return system_service.state()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_local_api.TestLocalAPI.test_state_route_returns_current_audio_state -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/system_control/amixer_executor.py client/system_control/service.py client/system_control/models.py client/local_api/app.py tests/test_amixer_executor.py tests/test_system_control_service.py tests/test_local_api.py
git commit -m "feat: implement seeed volume control actions"
```

---

### Task 6: Prepare the future browser dashboard host without building the dashboard

**Files:**
- Modify: `client/local_api/app.py`
- Create: `client/local_api/static/.gitkeep`
- Test: `tests/test_local_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_static_mount_exists_for_future_dashboard(self):
    app = create_app(system_service=_FakeService())
    static_paths = [route.path for route in app.routes]
    self.assertIn("/dashboard", static_paths)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_local_api.TestLocalAPI.test_static_mount_exists_for_future_dashboard -v`
Expected: FAIL because `/dashboard` is absent

- [ ] **Step 3: Write minimal implementation**

```python
from fastapi.staticfiles import StaticFiles

app.mount("/dashboard", StaticFiles(directory="client/local_api/static"), name="dashboard")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_local_api.TestLocalAPI.test_static_mount_exists_for_future_dashboard -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/local_api/app.py client/local_api/static/.gitkeep tests/test_local_api.py
git commit -m "feat: prepare local dashboard host"
```

---

### Task 7: Write the follow-up integration plan for server-to-client dispatch

**Files:**
- Modify: `docs/superpowers/specs/2026-06-20-client-system-control-design.md`
- Create: `docs/superpowers/plans/2026-06-20-client-system-control-server-dispatch.md`

- [ ] **Step 1: Write the failing test**

No automated code test for this documentation-only follow-up task. Instead, create the plan file with explicit implementation tasks for:

- `server/tools/system_control.py`
- `server/tools/__init__.py`
- `server/agents/smart_home_agent.py`
- `server/main.py`
- `client/ws_client.py`

- [ ] **Step 2: Run verification to confirm the follow-up plan file is absent**

Run: `test -f docs/superpowers/plans/2026-06-20-client-system-control-server-dispatch.md`
Expected: exit code `1`

- [ ] **Step 3: Write minimal implementation**

Create the follow-up plan file documenting the server-dispatch phase separately so the local client-control increment can ship independently.

- [ ] **Step 4: Run verification to confirm the file exists**

Run: `test -f docs/superpowers/plans/2026-06-20-client-system-control-server-dispatch.md`
Expected: exit code `0`

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-06-20-client-system-control-design.md docs/superpowers/plans/2026-06-20-client-system-control-server-dispatch.md
git commit -m "docs: plan client system control server dispatch phase"
```

---

## Self-Review

### Spec coverage

- Client-local service layer: covered by Tasks 1–3
- Client-local HTTP API: covered by Tasks 4–6
- Seeed volume control: covered by Tasks 2 and 5
- Shared backend for future frontend and voice integration: covered by Tasks 3–6
- WebSocket/server dispatch design: deferred explicitly and captured by Task 7

### Placeholder scan

- No `TODO` or `TBD` placeholders remain in the plan
- Each task has exact file paths
- Each code-changing task contains concrete test and implementation examples

### Type consistency

- Canonical request fields are `domain`, `action`, `target`, `params`
- Canonical result fields are `ok`, `domain`, `action`, `target`, `state` or `error`
- Service entrypoint is consistently named `execute`

