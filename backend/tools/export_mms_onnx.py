"""One-time conversion of a Meta MMS-TTS voice (VITS) from Hugging Face to ONNX, so the app can run it with onnxruntime alone.

Needs PyTorch and transformers, which the app itself does NOT (use a throwaway venv, or Google Colab):

    python -m venv /tmp/conv && /tmp/conv/bin/pip install torch "transformers==4.46.3" "numpy<2" onnxruntime
    /tmp/conv/bin/python backend/tools/export_mms_onnx.py facebook/mms-tts-urd-script_arabic assets/models/tts/mms-urd

(torch 2.2 is the last release for Intel Macs, hence the older transformers.) Licence of the MMS-TTS models: CC-BY-NC 4.0,
i.e. NOT for commercial use. The output folder gets model.onnx, vocab.json and voice.json (sample rate, tokenizer settings).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def main(repo: str, out: Path) -> None:
    import numpy as np
    import onnxruntime as ort
    import torch
    from huggingface_hub import hf_hub_download
    from transformers import VitsModel

    out.mkdir(parents=True, exist_ok=True)
    model = VitsModel.from_pretrained(repo).eval()

    class Wrapper(torch.nn.Module):
        def __init__(self, m: torch.nn.Module) -> None:
            super().__init__()
            self.m = m

        def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
            return self.m(input_ids=input_ids, attention_mask=attention_mask).waveform

    ids = torch.randint(1, 20, (1, 41))
    mask = torch.ones_like(ids)
    path = out / "model.onnx"
    with torch.no_grad():
        torch.onnx.export(Wrapper(model), (ids, mask), str(path), input_names=["input_ids", "attention_mask"], output_names=["waveform"],
                          dynamic_axes={"input_ids": {1: "n"}, "attention_mask": {1: "n"}, "waveform": {1: "samples"}}, opset_version=17, do_constant_folding=True)
    for name in ("vocab.json", "tokenizer_config.json", "config.json"):
        shutil.copy(hf_hub_download(repo, name), out / name)
    cfg = json.loads((out / "config.json").read_text("utf-8"))
    tok = json.loads((out / "tokenizer_config.json").read_text("utf-8"))
    (out / "voice.json").write_text(json.dumps({
        "source": repo, "license": "CC-BY-NC-4.0", "sample_rate": cfg["sampling_rate"], "add_blank": tok.get("add_blank", True),
        "normalize": tok.get("normalize", True), "language": tok.get("language"), "unk_token": tok.get("unk_token"), "pad_token": tok.get("pad_token"),
    }, indent=2), "utf-8")

    # check: the ONNX file runs and gives audio of a sensible length
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    ids2 = np.random.randint(1, 20, (1, 61)).astype(np.int64)
    wav = sess.run(None, {"input_ids": ids2, "attention_mask": np.ones_like(ids2)})[0]
    print(f"ok: {path} ({path.stat().st_size / 1e6:.0f} MB), {wav.shape[-1] / cfg['sampling_rate']:.2f} s of audio for 61 tokens")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], Path(sys.argv[2]))
