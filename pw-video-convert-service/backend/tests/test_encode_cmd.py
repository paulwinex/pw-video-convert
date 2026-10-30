import pytest

import app.core.config  # noqa: F401  # installs pw-video-convert on sys.path
from pw_video_convert import encode


def _info(width=1918, height=1080, bit_depth=8):
    return {
        'video': {'width': width, 'height': height, 'bit_depth': bit_depth},
        'audio': [],
        'subs': [],
    }


def _vf(cmd):
    return cmd[cmd.index('-vf') + 1]


def test_software_encode_without_filters_keeps_command_shape():
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', _info(320, 240), 30, False, '8', 'mkv')
    assert '-vf' not in cmd
    assert cmd[cmd.index('-c:v') + 1] == 'libsvtav1'
    assert cmd[cmd.index('-pix_fmt') + 1] == 'yuv420p'


def test_software_encode_pads_unsupported_size():
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', _info(1918, 1080), 30, False, '8', 'mkv')
    assert _vf(cmd) == 'pad=1920:1088:(ow-iw)/2:(oh-ih)/2:color=black'


def test_hardware_chain_pads_before_hwupload():
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', _info(1918, 1080, 10), 40, True, None, 'mkv')
    assert _vf(cmd) == ('pad=1920:1088:(ow-iw)/2:(oh-ih)/2:color=black,'
                        'format=p010,hwupload')


def test_hardware_chain_keeps_format_first_when_no_padding_needed():
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', _info(320, 240, 8), 40, True, None, 'mkv')
    assert _vf(cmd) == 'format=nv12,hwupload'


def test_resolution_option_adds_scale_and_pad():
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', _info(320, 240), 30, False, '8',
                                  'mkv', resolution='128x128')
    assert _vf(cmd) == ('scale=128:96,'
                        'pad=128:128:(ow-iw)/2:(oh-ih)/2:color=black')


def test_resolution_option_accepts_list():
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', _info(320, 240), 30, False, '8',
                                  'mkv', resolution=[128, 128])
    assert _vf(cmd) == ('scale=128:96,'
                        'pad=128:128:(ow-iw)/2:(oh-ih)/2:color=black')


def test_resolution_smaller_than_source_only_pads():
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', _info(640, 360), 30, False, '8',
                                  'mkv', resolution='1920x1080')
    assert _vf(cmd) == 'pad=1920:1088:(ow-iw)/2:(oh-ih)/2:color=black'


def test_invalid_resolution_raises():
    with pytest.raises(ValueError):
        encode.build_encode_cmd('in.mkv', 'out.mkv', _info(), 30, False, '8', 'mkv',
                                resolution='1920')


def _with_audio(*tracks):
    info = _info()
    info['audio'] = [
        {'codec': codec, 'channels': channels, 'stream_bitrate': bitrate}
        for codec, channels, bitrate in tracks
    ]
    return info


@pytest.mark.parametrize('channels,layout', [
    (1, 'mono'),
    (2, 'stereo'),
    (3, '3.0'),
    (4, 'quad'),
    (5, '5.0'),
    (6, '5.1'),
    (7, '6.1'),
    (8, '7.1'),
])
def test_opus_requests_libopus_compatible_channel_layout(channels, layout):
    info = _with_audio(('ac3', channels, None))
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', info, 30, False, '8', 'mkv')
    assert cmd[cmd.index('-ac:a:0') + 1] == str(channels)
    assert cmd[cmd.index('-ch_layout:a:0') + 1] == layout


def test_opus_four_channel_track_forces_quad_not_ffmpeg_default_4_0():
    info = _with_audio(('ac3', 4, 448000))
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', info, 30, False, '8', 'mkv')
    assert cmd[cmd.index('-ch_layout:a:0') + 1] == 'quad'


def test_opus_downmixes_channel_counts_above_vorbis_layouts():
    plan = encode.build_audio_plan(_with_audio(('dts', 12, 1536000)))
    assert plan[0]['action'] == 'opus'
    assert plan[0]['channels'] == 2
    assert plan[0]['layout'] == 'stereo'


def test_audio_copy_track_has_no_channel_layout():
    plan = encode.build_audio_plan(_with_audio(('opus', 6, 320000)))
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', _with_audio(('opus', 6, 320000)),
                                  30, False, '8', 'mkv')
    assert plan[0]['action'] == 'copy'
    assert '-ch_layout:a:0' not in cmd


def _maps(cmd):
    return [cmd[i + 1] for i, tok in enumerate(cmd) if tok == '-map']


def test_audio_selection_keeps_only_selected_tracks():
    info = _with_audio(('ac3', 6, 448000), ('aac', 2, 128000), ('dts', 6, 1536000))
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', info, 30, False, '8', 'mkv',
                                  audio=[0, 2])
    assert _maps(cmd) == ['0:v:0', '0:a:0', '0:a:2']
    assert '0:a:1' not in cmd
    assert cmd[cmd.index('-c:a:0') + 1] == 'libopus'
    assert cmd[cmd.index('-c:a:1') + 1] == 'libopus'


def test_audio_selection_renumbers_output_stream_indexes():
    info = _with_audio(('aac', 2, 128000), ('dts', 6, 1536000))
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', info, 30, False, '8', 'mkv',
                                  audio=[1])
    assert _maps(cmd) == ['0:v:0', '0:a:1']
    assert cmd[cmd.index('-c:a:0') + 1] == 'libopus'
    assert cmd[cmd.index('-b:a:0') + 1] == str(
        encode.audio_target_bitrate(6, 1536000))
    assert cmd[cmd.index('-ac:a:0') + 1] == '6'
    assert '-c:a:1' not in cmd


def test_audio_selection_first_track_copy_renumbered_to_zero():
    info = _with_audio(('ac3', 6, 448000), ('opus', 2, 96000))
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', info, 30, False, '8', 'mkv',
                                  audio=[1])
    assert _maps(cmd) == ['0:v:0', '0:a:1']
    assert cmd[cmd.index('-c:a:0') + 1] == 'copy'
    assert '-c:a:1' not in cmd


def test_audio_selection_out_of_range_raises():
    info = _with_audio(('aac', 2, 128000))
    with pytest.raises(ValueError, match='out of range'):
        encode.build_audio_plan(info, audio=[2])
    with pytest.raises(ValueError, match='out of range'):
        encode.build_encode_cmd('in.mkv', 'out.mkv', info, 30, False, '8', 'mkv',
                                audio=[5])


def test_build_audio_plan_filters_selected_ordinals():
    info = _with_audio(('aac', 2, 128000), ('ac3', 6, 448000), ('dts', 2, 768000))
    plan = encode.build_audio_plan(info, audio=[2])
    assert [t['ordinal'] for t in plan] == [2]
    assert plan[0]['action'] == 'opus'


def test_build_audio_plan_without_selection_keeps_all():
    info = _with_audio(('aac', 2, 128000), ('ac3', 6, 448000))
    assert [t['ordinal'] for t in encode.build_audio_plan(info)] == [0, 1]


def _add(path, label, channels=2, bitrate=None):
    return {'path': path, 'label': label, 'channels': channels,
            'stream_bitrate': bitrate}


def test_audio_add_appends_external_tracks():
    info = _with_audio(('aac', 2, 128000), ('dts', 6, 1536000))
    adds = [_add('/tmp/vo.mp3', 'VO', 2, 192000), _add('/tmp/m.flac', 'Music', 6, None)]
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', info, 30, False, '8', 'mkv',
                                  audio=[1], audio_add=adds)
    # kept source track is ordinal 1; external maps reference 1:a:0 and 2:a:0
    assert _maps(cmd) == ['0:v:0', '0:a:1', '1:a:0', '2:a:0']
    # output index 0 = kept source track (opus), 1 and 2 = external tracks
    assert cmd[cmd.index('-c:a:0') + 1] == 'libopus'
    assert cmd[cmd.index('-c:a:1') + 1] == 'libopus'
    assert cmd[cmd.index('-c:a:2') + 1] == 'libopus'
    assert cmd[cmd.index('-metadata:s:a:1') + 1] == 'title=VO'
    assert cmd[cmd.index('-metadata:s:a:2') + 1] == 'title=Music'
    assert cmd[cmd.index('-b:a:1') + 1] == str(
        encode.audio_target_bitrate(2, 192000))


def test_audio_add_output_index_follows_kept_tracks():
    info = _with_audio(('aac', 2, 128000), ('ac3', 6, 448000))
    adds = [_add('/tmp/vo.mp3', 'VO')]
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', info, 30, False, '8', 'mkv',
                                  audio=[1], audio_add=adds)
    assert _maps(cmd) == ['0:v:0', '0:a:1', '1:a:0']
    assert cmd[cmd.index('-metadata:s:a:1') + 1] == 'title=VO'
    assert '-metadata:s:a:2' not in cmd


def test_audio_add_allows_no_source_tracks():
    info = _with_audio()
    adds = [_add('/tmp/vo.mp3', 'VO', 2, 128000)]
    cmd = encode.build_encode_cmd('in.mkv', 'out.mkv', info, 30, False, '8', 'mkv',
                                  audio_add=adds)
    assert _maps(cmd) == ['0:v:0', '1:a:0']
    assert cmd[cmd.index('-metadata:s:a:0') + 1] == 'title=VO'
