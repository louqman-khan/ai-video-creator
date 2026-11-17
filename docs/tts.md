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
