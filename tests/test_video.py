from datetime import datetime, timezone

from renameimg.video import MARKER, VideoInfo, build_command, decide, parse_probe


def info(**kw) -> VideoInfo:
    base = dict(codec="h264", width=1920, height=1080, fps=30.0, bitrate=8_000_000, duration=10.0, has_audio=True)
    base.update(kw)
    return VideoInfo(**base)


def test_decide():
    assert decide(info())[0] is True
    assert decide(info(tags={"comment": MARKER}))[0] is False
    assert decide(info(codec=None))[0] is False
    assert decide(info(codec="hevc", bitrate=3_000_000))[0] is False
    assert decide(info(codec="hevc", bitrate=6_000_000))[0] is True
    # 4K 的門檻比較高
    assert decide(info(codec="hevc", width=3840, height=2160, bitrate=9_000_000))[0] is False
    assert decide(info(codec="hevc", width=3840, height=2160, bitrate=25_000_000))[0] is True


def test_build_command_scales_4k_and_caps_fps():
    cmd = build_command("in.mov", "out.mp4", info(width=3840, height=2160, fps=59.94), None)
    assert cmd[cmd.index("-vf") + 1] == "scale=-2:1080,fps=30"
    assert "yuv420p" in cmd
    assert f"comment={MARKER}" in cmd


def test_build_command_portrait_rotation():
    # 直拍：原始 3840x2160 但旋轉 90 度
    cmd = build_command("in.mov", "out.mp4", info(width=3840, height=2160, rotation=-90), None)
    assert cmd[cmd.index("-vf") + 1] == "scale=1080:-2"


def test_build_command_1080p_has_no_filters():
    assert "-vf" not in build_command("in.mov", "out.mp4", info(), None)


def test_build_command_keeps_hdr():
    cmd = build_command(
        "in.mov",
        "out.mp4",
        info(color_primaries="bt2020", color_transfer="arib-std-b67", color_space="bt2020nc"),
        None,
    )
    assert "yuv420p10le" in cmd
    assert cmd[cmd.index("-color_trc") + 1] == "arib-std-b67"


def test_build_command_creation_time_only_when_missing():
    when = datetime(2023, 10, 5, 6, 22, 33, tzinfo=timezone.utc)
    cmd = build_command("in.mov", "out.mp4", info(), when)
    assert "creation_time=2023-10-05T06:22:33.000000Z" in cmd
    cmd = build_command("in.mov", "out.mp4", info(tags={"creation_time": "x"}), when)
    assert not any(a.startswith("creation_time=") for a in cmd)


def test_parse_probe_rotation_and_bitrate_fallback():
    data = {
        "format": {"duration": "12.5", "bit_rate": "5000000", "tags": {"COMMENT": "hi"}},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "side_data_list": [{"rotation": 90}],
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }
    v = parse_probe(data)
    assert v.bitrate == 5_000_000
    assert v.rotation == 90
    assert v.display_size == (1080, 1920)
    assert round(v.fps, 2) == 29.97
    assert v.has_audio
    assert v.tags["comment"] == "hi"
