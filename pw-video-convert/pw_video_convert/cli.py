#!/usr/bin/python3

import argparse
import os
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union

from . import probe
from . import quality
from . import encode
from . import frame


CANCELLED = False


def _sigint_handler(signum, frame):
    global CANCELLED
    CANCELLED = True


signal.signal(signal.SIGINT, _sigint_handler)

FILLED = '█'
EMPTY = '░'

OUTPUT_CODEC = 'av1'


def bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def make_progress_printer():
    columns, _ = shutil.get_terminal_size(fallback=(80, 24))

    def print_progress(fraction: float, seconds_left: Optional[int]) -> None:
        percent = int(round(fraction * 100, 0))
        bar_len = max(columns - 32, 10)
        filled = int(bar_len * fraction)
        bar = FILLED * filled + EMPTY * (bar_len - filled)

        if seconds_left is None:
            line = f' {percent:>3}% [{bar}] ETA --:--'
        else:
            hours, rem = divmod(seconds_left, 3600)
            mins, secs = divmod(rem, 60)
            eta = f'{hours}:{mins:02d}:{secs:02d}' if hours else f'{mins}:{secs:02d}'
            line = f' {percent:>3}% [{bar}] ETA {eta}'

        print('\r'+bold(line.ljust(columns)), end='', flush=True)

    return print_progress


def resolve_output(file_input: Path, output_arg: Optional[str], container: str,
                   add_codec_name_suffix: bool = True) -> Path:
    ext = 'mkv' if container == 'mkv' else 'mp4'
    codec = f'.{OUTPUT_CODEC}' if add_codec_name_suffix else ''

    if output_arg is None:
        target_dir = file_input.parent
    else:
        candidate = Path(output_arg).expanduser()
        if candidate.is_dir() or output_arg.endswith(os.sep):
            target_dir = candidate
        else:
            return candidate.resolve()

    stem = file_input.stem
    source = file_input.resolve()
    path = (target_dir / f'{stem}{codec}.{ext}').resolve()
    if path != source:
        return path

    suffix = 1
    while True:
        name = f'{stem}{codec}.out{"" if suffix == 1 else suffix}.{ext}'
        path = (target_dir / name).resolve()
        if path != source:
            return path
        suffix += 1


def fmt_size(size_bytes: int) -> str:
    mib = size_bytes / 1024 / 1024
    if mib >= 1024:
        return f'{mib / 1024:.2f} GiB'
    return f'{mib:.1f} MiB'


TEST_QUALITIES: List[int] = [1, 3, 5, 7, 9]


def encoder_for(q: int, use_hw: bool, source_codec: Optional[str] = None) -> Tuple[int, Optional[str], str]:
    if use_hw:
        qv = quality.vaapi_quality_for_quality(q, source_codec)
        return qv, None, f'av1_vaapi CQP qp={qv} (hardware)'
    preset = quality.preset_for_quality(q, source_codec)
    crf = quality.crf_for_quality(q, source_codec)
    return crf, preset, f'libsvtav1 preset {preset} crf {crf} (software)'


def parse_audio_tracks(value: str) -> List[int]:
    """Parse '1,3,4' into sorted unique 1-based audio track numbers."""
    try:
        numbers = [int(part.strip()) for part in value.split(',')]
    except ValueError:
        raise ValueError(f'invalid --audio value {value!r} (expected e.g. 1,3,4)')
    if not numbers or any(n < 1 for n in numbers):
        raise ValueError(f'invalid --audio value {value!r} (track numbers start at 1)')
    return sorted(set(numbers))


class _AudioAddAction(argparse.Action):
    """Collect --add-audio-path / --add-audio-label values in input order."""

    def __call__(self, parser, namespace, values, option_string=None):
        seq = getattr(namespace, 'audio_add_seq', None)
        if seq is None:
            seq = []
            setattr(namespace, 'audio_add_seq', seq)
        seq.append((self.dest, values))


def pair_audio_add(seq: List[tuple]) -> List[dict]:
    """Pair path/label occurrences in order; a label binds to the nearest file.

    Both '-d f --label l' and '--label l -d f' pair into (f, l). Files without
    a label get a default one.
    """
    pairs: List[dict] = []
    pending_paths: List[str] = []
    pending_labels: List[str] = []

    def flush(path: Optional[str], label: Optional[str]) -> None:
        if path is None:
            path = pending_paths.pop(0) if pending_paths else None
        if label is None:
            label = pending_labels.pop(0) if pending_labels else None
        pairs.append({'path': path, 'label': label})

    for kind, value in seq:
        if kind == 'add_audio_path':
            if pending_labels:
                flush(value, pending_labels.pop(0))
            else:
                pending_paths.append(value)
        else:
            if pending_paths:
                flush(pending_paths.pop(0), value)
            else:
                pending_labels.append(value)

    while pending_paths or pending_labels:
        path = pending_paths.pop(0) if pending_paths else None
        label = pending_labels.pop(0) if pending_labels else None
        if path is None and label is not None:
            raise ValueError('--add-audio-label without a matching --add-audio-path')
        pairs.append({'path': path, 'label': label})

    return [
        {'path': p['path'], 'label': p['label'] or f'External audio {i + 1}'}
        for i, p in enumerate(pairs)
    ]


def _audio_track_label(ordinal: int, track: dict) -> str:
    tags = [t for t in (track.get('language'), track.get('title')) if t]
    suffix = f' [{", ".join(tags)}]' if tags else ''
    return f'a{ordinal + 1}{suffix}'


def print_plan(info: dict, encoder_name: str, container: str,
               resolution: Optional[Union[str, List[int]]] = None,
               audio: Optional[List[int]] = None,
               audio_add: Optional[List[dict]] = None) -> None:
    print(f'Input: {info["source"]} ({fmt_size(info["size"])})')
    video = info['video']
    print(f'Source: {video["width"]}x{video["height"]}, {video["bit_depth"]}-bit'
          + (', HDR metadata present' if video['hdr'] else ''))
    plan = frame.plan_video(video['width'], video['height'], resolution)
    if plan['final'] != plan['source']:
        box_note = (f' (target {plan["box"][0]}x{plan["box"][1]})'
                    if plan['box'] != plan['source'] else '')
        print(f'Frame: {plan["source"][0]}x{plan["source"][1]} -> '
              f'{plan["final"][0]}x{plan["final"][1]} aligned for AV1{box_note}')
    print(f'Encoder: {encoder_name}')

    audio_plan = encode.build_audio_plan(info, audio)
    subs_kept, subs_dropped = encode.build_subtitle_plan(info, container)

    audio_summary = ', '.join(
        f'{_audio_track_label(t["ordinal"], info["audio"][t["ordinal"]])} '
        f'{t["codec"]}->copy'
        if t['action'] == 'copy'
        else f'{_audio_track_label(t["ordinal"], info["audio"][t["ordinal"]])} '
             f'{t["codec"]}->opus {t["bitrate"] // 1000}k ({t["channels"]}ch)'
        for t in audio_plan
    )
    kept_ordinals = {t['ordinal'] for t in audio_plan}
    audio_dropped = [
        _audio_track_label(ordinal, track) + f' {track["codec"]}'
        for ordinal, track in enumerate(info['audio'])
        if ordinal not in kept_ordinals
    ]
    print(f'Audio: {audio_summary or "none"}'
          + (f'; dropped: {", ".join(audio_dropped)}' if audio_dropped else ''))
    for i, item in enumerate(audio_add or []):
        layout_channels, layout, bitrate = encode._opus_params(
            item['channels'], item.get('stream_bitrate')
        )
        name = Path(item['path']).name
        print(f'Audio add {i + 1}: [{item["label"]}] {name} '
              f'{item["codec"]} {item["channels"]}ch -> opus '
              f'{bitrate // 1000}k ({layout_channels}ch)')
    subs_summary = ', '.join(
        f's{s["ordinal"]} {s["codec"]}->{"copy" if container == "mkv" else "mov_text"}'
        for s in subs_kept
    )
    dropped_summary = ', '.join(f'{d["codec"]} dropped' for d in subs_dropped)
    print(f'Subtitles: {subs_summary or "none"}'
          + (f'; dropped: {dropped_summary}' if subs_dropped else ''))


def encode_once(file_input: Path, output_path: Path, q: int,
                use_hw: bool, container: str,
                progress_fn: Optional[Callable[[float, Optional[int]], None]] = None,
                cancel_fn: Optional[Callable[[], bool]] = None,
                resolution: Optional[Union[str, List[int]]] = None,
                audio: Optional[List[int]] = None,
                audio_add: Optional[List[dict]] = None) -> int:
    # `audio` holds user-facing 1-based track numbers; encode layer uses 0-based
    # ordinals matching `-map 0:a:N`.
    audio_ordinals = [n - 1 for n in audio] if audio is not None else None
    info = probe.get_media_info(str(file_input))
    info['source'] = str(file_input)
    source_size = info['size']

    # External audio files: probe the first audio stream of each for opus
    # parameters; fail early with a clear message.
    audio_add_info: List[dict] = []
    for item in audio_add or []:
        try:
            tracks = probe.get_audio_tracks(str(item['path']))
        except Exception as e:
            print(f'Error: could not read audio file {item["path"]} ({e})',
                  file=sys.stderr)
            return 1
        if not tracks:
            print(f'Error: no audio stream in {item["path"]}', file=sys.stderr)
            return 1
        first = tracks[0]
        audio_add_info.append({
            'path': str(item['path']),
            'label': item['label'],
            'codec': first['codec'],
            'channels': first['channels'],
            'stream_bitrate': first['stream_bitrate'],
        })

    source_codec = (info.get('video') or {}).get('codec_name')
    quality_value, preset, encoder_name = encoder_for(q, use_hw, source_codec)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print_plan(info, encoder_name, container, resolution,
               audio=audio_ordinals, audio_add=audio_add_info)

    on_progress = progress_fn if progress_fn is not None else make_progress_printer()
    is_cancelled = cancel_fn if cancel_fn is not None else (lambda: CANCELLED)

    if output_path.exists():
        output_path.unlink()

    error = encode.run_encode(
        str(file_input), str(output_path), info, quality_value,
        use_hw, preset, container, on_progress, is_cancelled,
        resolution=resolution,
        audio=audio_ordinals,
        audio_add=audio_add_info,
    )

    print()

    if is_cancelled():
        print('*** Cancelled ***')
        if output_path.exists():
            output_path.unlink()
        return 130

    if error is not None:
        print(f'*** ENCODE ERROR ***\n{error}', file=sys.stderr)
        if output_path.exists():
            output_path.unlink()
        return 1

    final_size = os.stat(output_path).st_size
    savings = (1 - final_size / source_size) * 100.0
    print(f'Done: {output_path} ({fmt_size(final_size)})')
    print(f'Savings vs source: {savings:.1f}% '
          f'({fmt_size(source_size)} -> {fmt_size(final_size)})')
    return 0


def run_test(file_input: Path, args, use_hw: bool,
             audio_tracks: Optional[List[int]] = None,
             audio_add: Optional[List[dict]] = None) -> int:
    info = probe.get_media_info(str(file_input))
    target_dir = (Path(args.output).expanduser().resolve()
                  if args.output else file_input.parent)
    target_dir.mkdir(parents=True, exist_ok=True)
    ext = 'mkv' if args.container == 'mkv' else 'mp4'

    duration = info['duration']
    depth = min(60, max(int(duration), 1))
    start = max(int(duration) // 2 - depth // 2, 0)
    print(f'Test mode: cutting {depth}s from {file_input.name} and encoding '
          f'q={TEST_QUALITIES} into {target_dir}')

    seg_fd, seg_path = tempfile.mkstemp(prefix='.constrict_test_', suffix='.mkv')
    os.close(seg_fd)
    try:
        cut = subprocess.run(
            ['ffmpeg', '-y', '-hide_banner', '-ss', str(start), '-i', str(file_input),
             '-t', str(depth), '-map', '0', '-c', 'copy', seg_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if cut.returncode != 0:
            print('Error: failed to cut test segment', file=sys.stderr)
            return 1

        overall = 0
        for q in TEST_QUALITIES:
            if CANCELLED:
                print('*** Cancelled ***')
                return 130
            out = target_dir / f'{file_input.stem}.q{q}.{ext}'
            print(f'\n=== q{q} ===')
            code = encode_once(Path(seg_path), out, q, use_hw, args.container,
                               resolution=args.resolution, audio=audio_tracks,
                               audio_add=audio_add)
            if code != 0:
                overall = code
                break
        return overall
    finally:
        try:
            os.unlink(seg_path)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        prog='constrict-mod',
        description=(
            'Re-encode video to AV1 with a quality scale q=1..10. '
            'q=10 is near-transparent (film grain preserved); lower levels trade '
            'quality for size. Framerate, selected audio tracks and subtitles are '
            'preserved. Resolution is kept unless --resolution is given, and the '
            'frame is always aligned to an AV1-supported size with centered black '
            'bars. Audio in non-optimal codecs is re-encoded to Opus at '
            'high quality without loudness change.'
        ),
    )
    parser.add_argument('-q', dest='quality', type=int, choices=range(1, 11),
                        metavar='1..10', default=5,
                        help='Quality level (default 5): perceptual tier from '
                             'source-preserving (10) to small-and-acceptable (1)')
    parser.add_argument('-c', dest='container', choices=['mkv', 'mp4'], default='mkv',
                        help='Output container (default mkv)')
    parser.add_argument('-s', '--software', action='store_true',
                        help='Use software SVT-AV1 (slower but better quality; '
                             'default is hardware VAAPI AV1)')
    parser.add_argument('-t', dest='test', action='store_true',
                        help='Test mode: cut 1 minute from the middle and encode '
                             'samples at q=1,3,5,7,9 into the output directory.')
    parser.add_argument('-r', '--resolution', type=str, default=None, metavar='WxH',
                        help='Target frame size, e.g. 1920x1080. The source is fitted '
                             'into it without upscaling and centered with black bars; '
                             'the result is always aligned to an AV1-supported size')
    parser.add_argument('-a', '--audio', type=str, default=None, metavar='1,3,4',
                        help='Audio tracks to keep: 1-based comma-separated numbers '
                             'as shown in the plan output (e.g. 1,3). '
                             'Default: keep all audio tracks')
    parser.add_argument('-d', '--add-audio-path', dest='add_audio_path',
                        action=_AudioAddAction, metavar='FILE', default=[],
                        help='External audio file to mux in as an extra track '
                             '(re-encoded to Opus). Repeatable; each label binds '
                             'to the nearest file in argument order')
    parser.add_argument('--add-audio-label', dest='add_audio_label',
                        action=_AudioAddAction, metavar='LABEL', default=[],
                        help='Track title for the preceding/following '
                             '--add-audio-path file')
    parser.add_argument('input', type=str, help='Source video file')
    parser.add_argument('output', nargs='?', default=None,
                        help='Target directory or output file path. The output keeps '
                             'the input name with the container extension; an .out '
                             'suffix is added if it would overwrite the input.')

    args = parser.parse_args()

    audio_tracks = None
    if args.audio:
        try:
            audio_tracks = parse_audio_tracks(args.audio)
        except ValueError as exc:
            parser.error(str(exc))

    try:
        audio_add = pair_audio_add(getattr(args, 'audio_add_seq', []))
    except ValueError as exc:
        parser.error(str(exc))
    for item in audio_add:
        path = Path(item['path']).expanduser().resolve()
        if not path.is_file():
            parser.error(f"audio file not found: {path}")
        item['path'] = str(path)

    if args.resolution:
        try:
            frame.parse_resolution(args.resolution)
        except ValueError as exc:
            parser.error(str(exc))

    file_input = Path(args.input).expanduser().resolve()
    if not file_input.is_file():
        print(f'Error: input file not found: {file_input}', file=sys.stderr)
        return 1

    try:
        info = probe.get_media_info(str(file_input))
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f'Error: could not read video properties ({e})', file=sys.stderr)
        return 1

    if audio_tracks is not None:
        audio_count = len(info['audio'])
        invalid = [n for n in audio_tracks if n > audio_count]
        if invalid:
            parser.error(
                f'audio track {invalid[0]} out of range '
                f'(file has {audio_count} audio tracks)'
            )

    use_hw = (not args.software) and probe.will_ha_work()
    if not args.software and not probe.will_ha_work():
        print('Warning: hardware VAAPI AV1 unavailable, falling back to software SVT-AV1')

    if args.test:
        return run_test(file_input, args, use_hw, audio_tracks=audio_tracks,
                        audio_add=audio_add)

    output_path = resolve_output(file_input, args.output, args.container)
    if output_path == file_input:
        print('Error: output path resolves to the input file', file=sys.stderr)
        return 1

    return encode_once(file_input, output_path, args.quality, use_hw, args.container,
                       resolution=args.resolution, audio=audio_tracks,
                       audio_add=audio_add)


if __name__ == '__main__':
    sys.exit(main())
