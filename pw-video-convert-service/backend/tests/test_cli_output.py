import sys

import pytest

import app.core.config  # noqa: F401  # installs pw-video-convert on sys.path
from pw_video_convert import cli


def _input(tmp_path, name='video.mkv'):
    path = tmp_path / name
    path.write_bytes(b'x')
    return path.resolve()


def test_output_next_to_source_appends_codec_suffix(tmp_path):
    src = _input(tmp_path, 'video.mp4')
    assert cli.resolve_output(src, None, 'mkv') == (tmp_path / 'video.av1.mkv').resolve()


def test_codec_suffix_can_be_disabled(tmp_path):
    src = _input(tmp_path, 'video.mp4')
    assert cli.resolve_output(
        src, None, 'mkv', add_codec_name_suffix=False
    ) == (tmp_path / 'video.mkv').resolve()


def test_output_collision_with_suffix_disabled_gets_out_suffix(tmp_path):
    src = _input(tmp_path, 'video.mkv')
    assert cli.resolve_output(
        src, None, 'mkv', add_codec_name_suffix=False
    ) == (tmp_path / 'video.out.mkv').resolve()


def test_output_dir_keeps_stem_and_appends_codec(tmp_path):
    src = _input(tmp_path, 'video.mp4')
    out_dir = tmp_path / 'outdir'
    out_dir.mkdir()
    assert cli.resolve_output(src, str(out_dir), 'mkv') == (out_dir / 'video.av1.mkv').resolve()


def test_explicit_output_file_is_used_as_is(tmp_path):
    src = _input(tmp_path)
    explicit = tmp_path / 'sub' / 'name.mkv'
    assert cli.resolve_output(src, str(explicit), 'mkv') == explicit.resolve()


def test_invalid_resolution_is_parser_error(tmp_path, monkeypatch):
    src = _input(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['constrict-mod', '-r', '1920', str(src)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_valid_resolution_passes_validation(tmp_path, monkeypatch, capsys):
    src = _input(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['constrict-mod', '-r', '1920x1080', str(src)])
    assert cli.main() == 1  # dummy file: fails later while probing, not on -r
    assert 'invalid resolution' not in capsys.readouterr().err


def test_parse_audio_tracks_sorts_and_dedups():
    assert cli.parse_audio_tracks('3,1,3') == [1, 3]
    assert cli.parse_audio_tracks('2') == [2]


@pytest.mark.parametrize('value', ['1,x', '1,,2', '0,1', '-1', ' ', '1.5'])
def test_invalid_audio_selection_is_parser_error(tmp_path, monkeypatch, value):
    src = _input(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['constrict-mod', '--audio', value, str(src)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_valid_audio_selection_passes_validation(tmp_path, monkeypatch, capsys):
    src = _input(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['constrict-mod', '--audio', '2,1,2', str(src)])
    assert cli.main() == 1  # dummy file: fails later while probing, not on --audio
    assert 'invalid --audio' not in capsys.readouterr().err


def test_pair_audio_add_binds_label_to_nearest_file():
    seq = [('add_audio_path', 'a.mp3'), ('add_audio_label', 'VO'),
           ('add_audio_path', 'b.mp3'), ('add_audio_label', 'Music')]
    assert cli.pair_audio_add(seq) == [
        {'path': 'a.mp3', 'label': 'VO'},
        {'path': 'b.mp3', 'label': 'Music'},
    ]


def test_pair_audio_add_accepts_label_before_file():
    seq = [('add_audio_label', 'VO'), ('add_audio_path', 'a.mp3')]
    assert cli.pair_audio_add(seq) == [{'path': 'a.mp3', 'label': 'VO'}]


def test_pair_audio_add_defaults_for_unlabeled_files():
    seq = [('add_audio_path', 'a.mp3'), ('add_audio_path', 'b.mp3')]
    assert cli.pair_audio_add(seq) == [
        {'path': 'a.mp3', 'label': 'External audio 1'},
        {'path': 'b.mp3', 'label': 'External audio 2'},
    ]


def test_pair_audio_add_dangling_label_is_error():
    with pytest.raises(ValueError, match='without a matching'):
        cli.pair_audio_add([('add_audio_label', 'VO')])


def test_add_audio_file_not_found_is_parser_error(tmp_path, monkeypatch):
    src = _input(tmp_path)
    monkeypatch.setattr(
        sys, 'argv',
        ['constrict-mod', '-d', str(tmp_path / 'nope.mp3'), str(src)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
