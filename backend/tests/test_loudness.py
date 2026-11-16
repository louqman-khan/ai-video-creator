import shutil
import subprocess

import pytest

from app.media import ffmpeg, loudness

SAMPLE_STDERR = """
[Parsed_loudnorm_0 @ 0x1] 
{
	"input_i" : "-23.15",
	"input_tp" : "-6.20",
	"input_lra" : "3.50",
	"input_thresh" : "-33.40",
	"output_i" : "-14.05",
	"target_offset" : "0.05"
}
"""


def test_parse_loudnorm_json():
    m = loudness.parse_loudnorm_json("noise before\n" + SAMPLE_STDERR)
    assert float(m["input_i"]) == -23.15 and m["target_offset"] == "0.05"
    with pytest.raises(ffmpeg.FfmpegError):
        loudness.parse_loudnorm_json("no json here")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
def test_normalize_hits_target_and_leaves_silence_alone(tmp_path):
    quiet = tmp_path / "quiet.wav"  # a quiet tone with some level changes, like speech
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=300:duration=6", "-af", "volume=0.05,tremolo=f=3:d=0.6", str(quiet)], check=True)
    before = float(loudness.measure(quiet)["input_i"])
    out = loudness.normalize(quiet, tmp_path / "n.flac", target=-14.0)
    assert out != quiet and before < -25
    assert float(loudness.measure(out)["input_i"]) == pytest.approx(-14.0, abs=0.6)

    silent = tmp_path / "silent.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", "3", str(silent)], check=True)
    assert loudness.normalize(silent, tmp_path / "s.flac") == silent  # not amplified
