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
