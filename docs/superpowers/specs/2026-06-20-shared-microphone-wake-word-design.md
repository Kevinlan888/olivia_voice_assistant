# Shared Microphone Wake Word Design

Date: 2026-06-20

## Goal

Replace the current client-side wake word flow that opens one microphone stream for Porcupine and a second stream for recording. The new design must keep a single input stream open for the entire client session so wake word detection and utterance recording consume the same PCM frames.

This change is intended to eliminate audio loss that happens when switching microphone ownership between the wake word listener and the recorder.

## Current Problem

Today the client does this:

1. `WakeWordDetector` opens its own PyAudio input stream.
2. Porcupine blocks on that stream until the wake word is detected.
3. The wake word stream is closed.
4. `AudioRecorder` opens a new PyAudio input stream.
5. Recording starts after the device transition.

This creates a gap between detection and recording. If the user starts speaking immediately after the wake word, the first part of the utterance may be lost. The gap is especially visible on constrained devices and on systems where reopening PortAudio is slow or unstable.

## Scope

In scope:

- Client-side microphone capture flow
- Wake word processing path
- VAD-driven recording path
- Main client orchestration
- Tests for state transitions and audio accumulation behavior

Out of scope:

- Server protocol changes
- Web client changes
- TTS playback behavior
- Wake word model changes
- Changing the underlying wake word engine away from Porcupine

## Recommended Approach

Adopt a single long-lived microphone capture component and make all input-side consumers operate on externally supplied PCM chunks.

The recommended implementation keeps Porcupine and Silero VAD, but moves device ownership into one place:

- Add a shared microphone component that is the only code allowed to open the input device.
- Convert wake word detection into a chunk-driven recognizer.
- Convert recording into a chunk-driven state machine.
- Make `client/main.py` orchestrate the transition between idle listening, wake word detected, recording, and response playback.

This keeps the design close to the current codebase while removing the root cause of dropped audio.

## Alternatives Considered

### Alternative 1: Shared microphone with chunk-driven consumers

This is the recommended design.

Pros:

- Removes microphone handoff gaps completely
- Preserves existing Porcupine and Silero VAD logic
- Makes input ownership explicit and testable

Cons:

- Requires some class boundary changes in the client

### Alternative 2: Keep current classes but add a coordinator around them

In this variant, `WakeWordDetector` and `AudioRecorder` would still exist mostly as-is, but a new top-level state machine would try to coordinate them while gradually reducing direct device ownership.

Pros:

- Smaller first patch

Cons:

- High risk of leaving input ownership split across modules
- More confusing long-term maintenance

### Alternative 3: Keep dual streams and only add prebuffer compensation

In this variant, the wake word stream would remain separate, but recent frames would be copied into the recording start.

Pros:

- Minimal code change

Cons:

- Does not solve the stream-switching problem
- Still depends on opening a second capture stream reliably
- Treats the symptom rather than the cause

## Design

## Architecture

The client input path will be reorganized around a single shared capture stream.

New ownership model:

- `SharedMicrophone` owns the PyAudio input stream lifecycle.
- `WakeWordDetector` owns only Porcupine initialization and frame evaluation.
- `AudioRecorder` owns only VAD-based utterance assembly and completion rules.
- `main.py` owns the runtime state machine and decides which consumer receives each chunk.

No other module may call `pyaudio.open(..., input=True)` after this change.

## Components

### `SharedMicrophone`

Purpose:

- Open the input device once at startup
- Read fixed-size PCM chunks continuously
- Provide a single source of microphone frames to the client runtime

Responsibilities:

- Use the existing sample rate, channels, and chunk size from client settings
- Expose a `read_chunk()` or equivalent iterator-style API
- Handle stream shutdown cleanly on client exit
- Optionally recreate the input stream only after repeated read failures

Non-responsibilities:

- No wake word logic
- No VAD logic
- No upload logic

### `WakeWordDetector`

Purpose:

- Evaluate incoming PCM chunks with Porcupine

Responsibilities after refactor:

- Initialize Porcupine from current settings
- Accept externally supplied PCM chunks of exactly the required frame length
- Return a boolean or equivalent signal when the wake word is detected

Removed responsibilities:

- Opening and closing the microphone
- Blocking on its own input loop

### `AudioRecorder`

Purpose:

- Assemble one utterance from a stream of externally supplied PCM chunks

Responsibilities after refactor:

- Reset internal VAD state at the start of a new utterance
- Accept an initial prebuffer and subsequent live chunks
- Track speech start, silence duration, minimum duration, and maximum duration
- Return the completed utterance PCM once VAD decides the utterance is over
- Optionally invoke a callback for chunks that should be streamed to the server

Removed responsibilities:

- Opening or closing the microphone
- Running its own blocking capture loop

### `client/main.py`

Purpose:

- Coordinate the full runtime state machine

States:

- `idle`: microphone is live, wake word detector receives chunks
- `recording`: wake word has fired, prebuffer has been injected, recorder consumes chunks
- `waiting_response`: recording has finished, upload is complete, waiting for server audio

Responsibilities:

- Maintain the short rolling prebuffer while idle
- Trigger wake sound playback once detection occurs
- Start a new utterance recorder session
- Forward chunks to the server during recording when wake-word mode is active
- Return to `idle` when the response is complete or when no valid speech is found

## Data Flow

### Idle listening

1. `SharedMicrophone` reads one PCM chunk.
2. The chunk is appended to a rolling prebuffer.
3. The chunk is passed to `WakeWordDetector.process_chunk(...)`.
4. If no wake word is detected, continue reading.

### Wake word transition

1. `WakeWordDetector` reports a hit.
2. The client plays the acknowledgement beep.
3. The client creates or resets an `AudioRecorder` session.
4. The current prebuffer is injected as the beginning of the utterance.
5. State changes from `idle` to `recording`.

### Recording

1. The same `SharedMicrophone` continues to produce chunks without reopening the device.
2. Each new chunk is added to `AudioRecorder`.
3. Once speech has started, chunks are forwarded to the server as streaming upload data.
4. `AudioRecorder` uses Silero VAD hysteresis and silence thresholds to decide when the utterance is complete.

### Finish

1. `AudioRecorder` returns the final PCM for the utterance.
2. The client sends `END` to the server.
3. The client waits for streamed or full response audio as it does today.
4. When playback and response handling finish, state returns to `idle`.

## Prebuffer Strategy

To prevent cutting off speech that begins immediately after the wake word, the client will maintain a short ring buffer while in `idle`.

Recommended setting:

- Add `WAKE_WORD_PREBUFFER_SECONDS`, defaulting to a conservative value such as `0.75`

Behavior:

- The prebuffer stores the most recent microphone chunks while the client is listening for the wake word.
- On wake word detection, the entire prebuffer is prepended to the utterance.
- This does not require any second stream or replay from hardware; it is purely an in-memory carry-over of already captured frames.

## Push-To-Talk Compatibility

PTT mode stays supported, but it should also use the shared microphone ownership model.

Rules:

- PTT still bypasses wake word detection.
- PTT must not create a second input stream.
- If needed, `main.py` may branch on control mode while still reading chunks from the same shared microphone abstraction.

This avoids reintroducing the same input-device ownership problem through a second code path.

## Error Handling

### Startup failures

- If the shared microphone cannot be opened, client startup should fail immediately with a clear error.
- If Porcupine initialization fails, client startup should fail immediately.
- If Silero VAD initialization fails, client startup should fail immediately.

There should be no silent fallback that makes the client appear healthy while wake word or recording logic is broken.

### Runtime read failures

- Single transient read errors should be logged and the loop should continue.
- Repeated read errors should trigger controlled stream recreation inside `SharedMicrophone`.
- Stream recreation must remain localized to `SharedMicrophone`; callers should not manage hardware resets directly.

### Empty speech case

- If wake word is detected but no valid speech is assembled, discard the utterance and return to `idle`.
- The microphone remains open throughout.

## Testing Strategy

The main behavioral change is in state transitions and chunk ownership, so tests should focus on deterministic state-machine behavior instead of real audio hardware.

### Unit tests

Add unit tests for:

- `WakeWordDetector.process_chunk(...)` returning detection only for matching frames
- `AudioRecorder` starting with prebuffer data and appending later chunks
- `AudioRecorder` completing after sustained silence and trimming trailing silence
- The main orchestration flow not sending any audio before wake word detection
- The main orchestration flow sending streaming audio only after recording begins
- The main orchestration flow sending `END` exactly once per utterance

### Regression expectations

The most important regression to lock down is:

- If the user starts speaking immediately after the wake word, the returned utterance should contain the buffered leading audio rather than dropping the beginning of the first word

### Test design notes

- Prefer fake chunk sources over mocked PyAudio internals
- Keep the recorder and detector testable without opening real devices
- Treat the shared microphone as a thin adapter and test most logic above it

## Implementation Notes

Expected file-level impact:

- Add a new input-stream component under `client/`
- Refactor `client/wake_word.py` to remove stream ownership
- Refactor `client/audio_recorder.py` to remove stream ownership and expose chunk-driven APIs
- Refactor `client/main.py` into an explicit input state machine
- Update `client/config.py` with prebuffer configuration
- Add or update client tests for the new orchestration behavior

The server-side code and WebSocket protocol should remain unchanged for this work.

## Acceptance Criteria

The design is complete when all of the following are true:

- The client opens the microphone input stream once and reuses it across idle listening and recording
- Wake word detection consumes externally supplied PCM frames
- Recording consumes externally supplied PCM frames
- No client module other than the shared microphone component opens an input stream
- Wake word followed by immediate speech no longer loses the beginning of the utterance
- Existing response upload and playback behavior remains intact
- PTT mode remains supported without reintroducing a second input stream

## Risks

- The main loop becomes more stateful, so unclear boundaries could make regressions easy if responsibilities remain mixed
- Prebuffer injection can duplicate some audio around the wake point if not carefully bounded, though this is preferable to dropping leading speech
- Tests may require some lightweight refactoring to make orchestration code easier to drive without hardware

## Recommendation Summary

Proceed with a shared-microphone refactor that centralizes input-device ownership and converts both wake word detection and recording into chunk-driven consumers. This directly addresses the audio-loss root cause without requiring server changes or replacement of Porcupine and Silero VAD.
