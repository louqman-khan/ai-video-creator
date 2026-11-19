# AI Video Creator: what we built, and what comes from other tools

*Status: 19 November 2026. Written for the owner. Facts are taken from the project's roadmap and decisions (`ROADMAP.md`, `decisions.md`).*

## 1. What the product is

A website (and an optional desktop app) that turns **spoken narration or a typed script, in Urdu or English, into a finished video**. It finds legal pictures and clips, times them to the audio, adds captions, cleans the sound, and then lets the user refine everything in a professional timeline editor and export it.

Main difference from other tools: **Urdu is first class**: Urdu speech recognition, correct right-to-left captions in Nastaliq script, an Urdu interface for sign-in, and Urdu e-mails.

## 2. What we built ourselves

| Area | What it does |
|---|---|
| **Automatic pipeline** | Audio or script in; recognizes the speech; plans scenes; finds and ranks pictures; times them to the narration; adds captions; builds the video. |
| **Exact captions** | A user's own script is matched to the audio so captions use the exact words, while the timing comes from the audio. Words the recognizer was unsure about are marked "please check". |
| **Text clean-up** | Optional correction of recognized text with a language model, with safety checks so it cannot rewrite the speech. |
| **Editor** | Multi-track timeline: cut, trim, split, merge, move or delete several clips together, transitions, effects, music, crop and resize, frame shapes (16:9, 9:16, 1:1, 4:5), green screen (with edge clean-up), smart crop, undo and redo, autosave. |
| **Live preview** | An instant in-browser preview that matches the final render, checked automatically against it. |
| **Rendering** | Plans and caches the video in segments, exports at several sizes, uses hardware encoders when present. |
| **Urdu support** | Right-to-left captions in Nastaliq, a language switch (English / اردو), translated sign-in pages and e-mails. |
| **Website accounts** | Sign-up and log-in with a six-digit e-mail code, password reset, per-user limits and **monthly credits**, an operator page (accounts, bonus credits, switch an account off), security rules (ownership of every project, protection against forged requests, safe downloads). |
| **Desktop app** | A native window around the same app, and a builder for macOS and Windows installers (built on GitHub; the Windows one has not been run by a person yet). |
| **Design** | The whole interface (teal theme, sidebar, project grid, one-screen editor, light and dark mode), checked for accessibility. |
| **Quality checks** | About 520 automated tests, plus browser scripts that drive the real site. |

## 3. What comes from other tools

| What it does | Source | Cost / licence note |
|---|---|---|
| Speech to text | **Whisper** (OpenAI), through faster-whisper, running on our own computer | Free, open licence |
| Scene ideas, text clean-up | **Google Gemini**, an online service | Free tier today; the only service that could start charging |
| Pictures and videos | **Pixabay, Openverse, Wikimedia Commons** | Free; each item's licence and credit is stored with it |
| Choosing the best picture | **CLIP** (OpenAI), a small model on our own computer | Free, MIT licence |
| Noise removal | **RNNoise** model | Free |
| Building video, loudness, burning in captions | **FFmpeg** (with libass) | Free; the bundled build is GPL, so check before giving the installer to others |
| Voices for typed scripts | **Meta MMS** (Urdu) and **Piper** (English), on our own computer | **MMS is non-commercial only**; the English voice's licence is unclear. Not allowed on a paid public site. |
| Finding faces for crop | **UltraFace** model | Free, MIT licence |
| Software underneath | FastAPI, React, Vite, SQLAlchemy, Tauri (desktop window) | Free, open source |
| Fonts | Noto Nastaliq Urdu, Gulzar, DM Sans, Space Grotesk | Free (SIL Open Font License) |
| Sending e-mail | The owner's own mail account (alfinora.com) | Existing account |
| Look and layout ideas | Studied Descript, Adobe Firefly, VEED and the Manus and Lovable mock-ups | Inspiration only, nothing copied |

## 4. What we have not built

- **Plans and payment.** Credits and limits exist; nothing can be bought. Decided: not for now.
- **Real lip-synced avatars.** The avatar is a simple cartoon. The real thing needs a graphics card.
- **AI-generated images.** Needs a graphics card.
- **A live website.** Everything has been run and tested on one computer. Hosting is deferred until the project is complete.
- **A commercially usable voice.** See section 5.
- **Paid voice and avatar services** (ElevenLabs, HeyGen). The code exists and is off by default, but it has only been tested against simulated responses.
- **Urdu for the editor.** Only the sign-in pages and e-mails are translated; the editor is English.

## 5. Open question: a free voice for typed scripts

On a public site the free Urdu voice cannot be used (non-commercial licence), so "Type a script" would be unavailable and users would upload a recording instead. Everything else still works. Free options under consideration:

1. **English:** Kokoro-82M (Apache 2.0, runs on an ordinary computer). Caveat: it uses espeak-ng, which is GPL-licensed. Fine for a site we run ourselves; check before shipping it inside an installer.
2. **Urdu:** Indic Parler-TTS (lists Urdu, Apache 2.0) but it is large and wants a graphics card. Piper Urdu voices exist, but their licences are unclear and must be read one by one.
3. **Our own voice:** one speaker records about 2 to 3 hours of clean speech and we train a small voice on a free Colab/Kaggle GPU. Free, with a licence we fully control, but it needs the speaker's time and written permission.

Proposed next step: read the real licence files, listen to samples of each, then decide.

## 6. Risks to keep in mind

- **Free online tiers** (Gemini, Pixabay) can change their limits.
- **Mail delivery** from the development network was unreliable; mail is sent in the background with retries.
- **Unsigned installers** show a security warning on macOS and Windows until they are signed (costs money).
- **Urdu accuracy** is about 21% word errors after the clean-up on one 10-minute test. The "please check" marks and exact-script matching are how we cover that.
