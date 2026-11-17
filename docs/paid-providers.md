# Optional paid providers (task 5.4)

Everything works without them. They are **off by default**, are never part of `auto` selection, and need two things: choosing them in `.env` AND a key.

| Capability | Provider | Switch | Needs |
|---|---|---|---|
| Voice (typed script -> narration) | ElevenLabs | `TTS=elevenlabs` | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_EN` (a default is set), `ELEVENLABS_VOICE_UR` for Urdu, `ELEVENLABS_MODEL` (use one that supports Urdu) |
| Talking avatar | HeyGen | `AVATAR_RENDERER=heygen` | `HEYGEN_API_KEY` |
| Talking avatar (your own GPU / Colab) | `remote` service | `AVATAR_RENDERER=remote` | `AVATAR_URL`, `AVATAR_TOKEN` (docs/avatars.md); not paid by itself |

## What the app does about cost and privacy
- The UI shows a confirmation ("this is an outside paid service: your script/narration is sent to it and uses your quota") that must be ticked before a paid voice or avatar can be created.
- `GET /api/health` reports `speech_paid`, `GET /api/avatars` marks each avatar `paid`.
- Keys live only in `.env`; they are removed from every error text that goes to the browser; the avatar download address from HeyGen never receives the key.
- Long scripts are sent to ElevenLabs in chunks of at most 2,500 characters; HeyGen waits up to 20 minutes per video, then gives up.
- A quota/payment problem (HTTP 402/429), a refused key (401/403), network errors and unreadable answers each give a one-line explanation, not a stack trace.

## Honest status: NOT verified against the live services
Both providers were written from the public API descriptions and are tested with **mocked HTTP only** (request shape, polling, chunking, failures, key handling). No account was available, so nobody has
checked that, for example, HeyGen still accepts these field names or that the Urdu voice sounds good. When you add a key, try a short script first; if a request is refused, the error message
shows the HTTP status and the code to adjust is in `backend/app/providers/tts/elevenlabs.py` and `backend/app/providers/avatar_renderer/heygen.py` (one function each).
