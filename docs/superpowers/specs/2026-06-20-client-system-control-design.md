# Client System Control Design

## Goal

Add a client-side `system_control` capability that can control the Raspberry Pi's local system settings, starting with the Seeed audio card's playback volume. The same client-side capability must be reusable from both a future browser dashboard and the existing voice-assistant flow.

## Scope

### In scope for the first implementation

- Client-side system control service
- Client-local HTTP API
- Volume control for the Seeed sound card playback path
- Action/capability model that is extensible to future system controls
- WebSocket protocol extension design for server-to-client control dispatch

### Out of scope for the first implementation

- Full browser dashboard UI
- Brightness, Wi-Fi, Bluetooth, shutdown, reboot implementations
- Authentication or authorization
- Multi-client routing semantics on the server side

## Core Constraints

1. The controlled machine is the `client` device, not the `server`.
2. Real system commands must execute locally on the Raspberry Pi client.
3. The future browser frontend and the voice-assistant flow must share one control backend.
4. The first working implementation must target the Seeed audio card playback volume only.
5. Client-local HTTP API access is assumed to be limited to the local network for now; no auth is added in the first version.

## Architecture

The client becomes the host for local system capabilities. The client exposes a local service layer that owns all system-control logic. Two separate callers reuse that same service:

- The local browser dashboard calls the client-local HTTP API.
- The voice-assistant flow triggers server-side tool calls, which are forwarded over the existing WebSocket connection to the connected client, then executed locally by the client service.

The server must not execute local system commands itself.

## Components

### 1. Client system-control domain layer

New client-side module group:

- `client/system_control/models.py`
- `client/system_control/executor.py`
- `client/system_control/amixer_executor.py`
- `client/system_control/service.py`

Responsibilities:

- define request/response/state/capability models
- validate supported actions and parameters
- dispatch actions to the local executor
- isolate `amixer` parsing and command execution from HTTP and WebSocket layers

### 2. Client-local HTTP API

New client-local API module group:

- `client/local_api/app.py`
- optional supporting modules under `client/local_api/`

Responsibilities:

- expose capabilities, current state, and control execution via HTTP
- translate HTTP payloads into `system_control` service requests
- return structured JSON results

### 3. Client-local frontend host

A minimal static frontend shell will be hosted by the client-local API later, but the first implementation only needs the API shape to be stable for future dashboard work.

### 4. Server-to-client control dispatch

The server will gain a `system_control` tool later, but it must not run system commands. Instead:

- server tool call creates a client action request
- request is sent over the existing client WebSocket
- client executes locally through `system_control.service`
- client returns a structured result event
- server uses that result to respond to the user

## Data Model

### Control request

Canonical request shape:

```json
{
  "domain": "audio",
  "action": "set_volume",
  "target": "seeed_output",
  "params": {
    "percent": 50
  }
}
```

### Control result

```json
{
  "ok": true,
  "domain": "audio",
  "action": "set_volume",
  "target": "seeed_output",
  "state": {
    "volume_percent": 50,
    "muted": false
  }
}
```

### Failure result

```json
{
  "ok": false,
  "domain": "audio",
  "action": "set_volume",
  "target": "seeed_output",
  "error": {
    "code": "unsupported_action",
    "message": "Action set_volume is not supported for target seeed_output"
  }
}
```

### Capabilities

The first version exposes implemented and reserved capabilities explicitly.

Implemented:

- `audio.get_volume`
- `audio.set_volume`
- `audio.volume_up`
- `audio.volume_down`
- `audio.mute`
- `audio.unmute`

Reserved but not yet implemented:

- `display.set_brightness`
- `network.set_wifi`
- `network.set_bluetooth`
- `system.shutdown`
- `system.reboot`

## Seeed Audio Control Design

The first implementation must not rely on the default ALSA card. The target sound card and mixer control must be explicit client configuration.

Proposed client configuration:

- `SYSTEM_AUDIO_CARD=seeed2micvoicec`
- `SYSTEM_AUDIO_MIXER=Playback`

The mixer name may differ on the actual device, so configuration must allow override if `Playback` is not the correct ALSA control name.

### Command strategy

- get volume:
  - `amixer -c <card> sget <mixer>`
- set exact volume:
  - `amixer -c <card> sset <mixer> 50%`
- volume up:
  - `amixer -c <card> sset <mixer> 5%+`
- volume down:
  - `amixer -c <card> sset <mixer> 5%-`
- mute:
  - `amixer -c <card> sset <mixer> mute`
- unmute:
  - `amixer -c <card> sset <mixer> unmute`

The executor is responsible for parsing returned `amixer` output into a normalized state object:

- `volume_percent`
- `muted`
- optional raw command output for debugging

## HTTP API

### `GET /api/system/capabilities`

Purpose:

- allow the future frontend to know what this client can do

Response includes:

- supported domains/actions
- implemented vs reserved actions
- active audio target metadata

### `GET /api/system/state`

Purpose:

- return a snapshot suitable for dashboard rendering

First version includes at least:

- `audio.output.device`
- `audio.volume.percent`
- `audio.volume.muted`
- `client.connected_to_server`

### `POST /api/system/control`

Purpose:

- execute a client-local action request

Request body:

- canonical `domain` / `action` / `target` / `params` request model

Response body:

- canonical control result model

## WebSocket Event Extension

### Server to client

```json
{
  "event": "client_action",
  "id": "req_123",
  "domain": "audio",
  "action": "set_volume",
  "target": "seeed_output",
  "params": {
    "percent": 50
  }
}
```

### Client to server

```json
{
  "event": "client_action_result",
  "id": "req_123",
  "ok": true,
  "result": {
    "volume_percent": 50,
    "muted": false
  }
}
```

The client-side HTTP API and the WebSocket action handler must both call the same `system_control.service` entrypoint. No duplicate business logic is allowed.

## Agent and Tool Integration

Later, the server can expose a `system_control` tool to the agent layer. That tool should:

- validate request shape at the server boundary
- send a `client_action` event to the connected client
- await the `client_action_result`
- convert that result into a tool result suitable for spoken response

The tool should initially live alongside existing tools under `server/tools/`, but its execution backend must be a client-dispatch path, not a server-local shell command.

This tool can be attached to the existing `smart_home_agent` first rather than introducing a new dedicated system agent.

## Error Handling

The first implementation must distinguish these error classes:

- unsupported domain/action
- invalid parameter value
- unsupported target
- command execution failure
- `amixer` parsing failure
- local service unavailable
- no connected client available for server-dispatched actions

Errors must be structured, not free-form strings only.

## Testing Strategy

### Unit tests

- action/request validation
- `amixer` output parsing
- service dispatch behavior
- implemented vs reserved capability exposure

### HTTP tests

- `GET /api/system/capabilities`
- `GET /api/system/state`
- `POST /api/system/control`

### Integration tests

- local API uses the same service as the WebSocket dispatch path
- mock executor proves that frontend/API/voice share one backend

### Device validation

- read actual Seeed playback state via `amixer`
- set volume
- raise/lower volume
- mute/unmute

## Incremental Delivery Plan

### Phase 1

- build client-side `system_control` domain layer
- build client-local HTTP API
- support Seeed playback volume only

### Phase 2

- add minimal browser page shell hosted by the client-local API
- expose current volume and basic controls

### Phase 3

- extend server/client WebSocket protocol for `client_action`
- add server-side `system_control` tool dispatch
- allow voice commands to control client-local volume

### Phase 4

- implement additional domains such as brightness, Wi-Fi, Bluetooth, shutdown, reboot

## Rationale

This design keeps privileged system control on the Raspberry Pi client, avoids duplicating logic between voice and frontend features, and creates a stable API surface for the future local dashboard. It also avoids overbuilding a separate daemon before there is enough scope to justify it.
