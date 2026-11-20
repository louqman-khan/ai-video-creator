# Speech: typed script -> narration (task 5.1)

## Using it
- Web: *New project* > **Speak my script with a computer voice**, type the script, choose English or Urdu, create.
- CLI: `avc speak narration.wav --lang ur --file script.txt`, then `avc make narration.wav --script script.txt`.
- API: `POST /api/projects` with `script` and `language` (`en` / `ur`) and no `file`.
`GET /api/health` -> `speech: ["ur", "en"]` lists what is installed; `avc doctor` shows it too.

## Where the voices live (`assets/models/tts/`, not committed)
| Language | Folder | Engine | How to get it |
|---|---|---|---|
| Urdu | `mms-urd/` (`model.onnx`, `vocab.json`, `voice.json`) | Meta MMS-TTS (VITS) | convert once: `python -m venv /tmp/conv && /tmp/conv/bin/pip install torch "transformers==4.46.3" "numpy<2" "onnx<1.18" onnxruntime huggingface_hub` then `/tmp/conv/bin/python backend/tools/export_mms_onnx.py facebook/mms-tts-urd-script_arabic assets/models/tts/mms-urd` (torch 2.2 is the last for Intel Macs). The app itself never needs torch. |
| English | `piper-en/` (`<voice>.onnx` + `<voice>.onnx.json`) | Piper | `pip install piper-tts`, download a voice from `rhasspy/piper-voices` on Hugging Face (e.g. `en/en_US/amy/medium`) into that folder |

`TTS=auto` (default) picks per language; `TTS=mms`, `TTS=piper` or `TTS=none` force one.

## Licences (read before selling anything)
- **MMS-TTS: CC-BY-NC 4.0, non-commercial only.** Fine for learning and personal use; a paid product needs a different Urdu voice.
- Piper voices carry the licence of the dataset they were trained on (`en_US-amy-medium`: "see Mimic3 voices" — unclear; `ryan` is CC BY-NC-SA; `lessac` has its own Blizzard licence). Check the `MODEL_CARD` of the voice you ship.

## Quality and speed (Intel i7-4980HQ, CPU only)
Real-time factor 0.42 (English) / 0.46 (Urdu). Whisper-small transcription of the output: English WER 0 %, Urdu 35 % (Whisper also mis-hears natural Urdu). The Urdu voice is understandable but synthetic.

## Limits
One voice per language; no speed control; numbers and abbreviations are not expanded (the Urdu voice drops digits: write numbers as words); sentences longer than
220 characters are cut at commas.

## English voice that is free for commercial use: Kokoro (added 2026-11-19)
`TTS=kokoro` (also what `auto` prefers for English). Kokoro-82M, **Apache 2.0**, 8-bit ONNX through `kokoro-onnx`, CPU only. About 120 MB: `avc fetch-models --kokoro` (checksummed; the Settings page downloads it too). Files: `<tts_dir>/kokoro-en/kokoro-v1.0.int8.onnx` and `voices-v1.0.bin`.
- **Hosted site:** unlike MMS (CC-BY-NC) and the Piper voice (licence unclear), Kokoro is **not** switched off in hosted mode, so a public site can offer "Type a script" in English. Install with `pip install "ai-video-creator[kokoro]"` (the Dockerfile does) and run `avc fetch-models --kokoro` once.
- **Voices:** `KOKORO_VOICE` = `af_heart` (default), `af_bella`, `af_nicole`, `am_michael`, `am_adam`, `bf_emma` (British), `bm_george`.
- **Measured** (GitHub Linux runner, 4 cores): 2 to 3 times faster than real time; Whisper `small` understood the 15 s test script word for word with all three voices tried.
- **Caveats:** the phoneme step uses espeak-ng (GPL): fine for a site we run, review before giving an installer that contains it to others. `kokoro-onnx` needs onnxruntime >= 1.20, which Intel Macs do not get (this repo's development Mac): it cannot be run there, and the desktop installer build deliberately does not include it. Urdu is not covered: see the experiment in `backend/tools/voice_experiment.py` (Urdu written in Devanagari and read by a Hindi voice) which needs a native listener's verdict first.


## Urdu typed scripts through Kokoro's Hindi voice (free, commercial use allowed)

Spoken Urdu and Hindi are nearly the same language; only the script differs. So for a typed Urdu script, Gemini first writes each sentence in Devanagari (same words and sounds, no translation, Urdu-origin words and the nukta letters kept), then Kokoro's Hindi voice `hf_alpha` (Apache 2.0) reads it.

- Engine: `KokoroUrduTTS` (`app/providers/tts/kokoro.py`), transliteration in `app/providers/tts/urdu_script.py`. Part of `TTS=auto`, after MMS (so where MMS is allowed it still wins for Urdu; on the hosted site it is the only Urdu voice).
- Needs: the Kokoro files (`avc fetch-models --kokoro`), `GEMINI_API_KEY` (free tier is enough, one request per 12 sentences), and `URDU_VIA_HINDI` not set to false.
- Safety: the answer is rejected unless it has the same number of sentences, contains Devanagari and no Arabic-script leftovers; otherwise the user is told to try again. Nothing unchecked is ever spoken.
- Quality: understandable, with a Hindi accent and Hindi-style stress. The owner listened to samples and chose to go ahead. A native Urdu speaker should judge real scripts before launch; the fall-back is the user's own recording.
- Limits: depends on the Gemini free tier; text that Gemini mis-writes is spoken wrongly (the captions still show the typed Urdu).
