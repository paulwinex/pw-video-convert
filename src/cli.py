#!/usr/bin/python3

import argparse
import os
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import probe
import quality
import encode


CANCELLED = False


def _sigint_handler(signum, frame):
    global CANCELLED
    CANCELLED = True


signal.signal(signal.SIGINT, _sigint_handler)

FILLED = '█'
EMPTY = '░'


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


def resolve_output(file_input: Path, output_arg: Optional[str], q: int, container: str) -> Path:
    ext = 'mkv' if container == 'mkv' else 'mp4'

    if output_arg is None:
        target_dir = file_input.parent
    else:
        candidate = Path(output_arg).expanduser()
        if candidate.is_dir() or output_arg.endswith(os.sep):
            target_dir = candidate
        else:
            return candidate.resolve()

    stem = file_input.stem
    same_dir = target_dir.resolve() == file_input.parent.resolve()

    name = f'{stem}.q{q}.av1.{ext}' if same_dir else f'{stem}.{ext}'
    return (target_dir / name).resolve()


def fmt_size(size_bytes: int) -> str:
    mib = size_bytes / 1024 / 1024
    if mib >= 1024:
        return f'{mib / 1024:.2f} GiB'
    return f'{mib:.1f} MiB'


TEST_QUALITIES: List[int] = [1, 3, 5, 7, 9]


def encoder_for(q: int, use_hw: bool) -> Tuple[int, Optional[str], str]:
    if use_hw:
        qv = quality.vaapi_quality_for_quality(q)
        return qv, None, f'av1_vaapi CQP qp={qv} (hardware)'
    preset = quality.preset_for_quality(q)
    return quality.crf_for_quality(q), preset, \
        f'libsvtav1 preset {preset} crf {quality.crf_for_quality(q)} (software)'


def print_plan(info: dict, encoder_name: str, container: str) -> None:
    print(f'Input: {info["source"]} ({fmt_size(info["size"])})')
    video = info['video']
    print(f'Source: {video["width"]}x{video["height"]}, {video["bit_depth"]}-bit'
          + (', HDR metadata present' if video['hdr'] else ''))
    print(f'Encoder: {encoder_name}')

    audio_plan = encode.build_audio_plan(info)
    subs_kept, subs_dropped = encode.build_subtitle_plan(info, container)

    audio_summary = ', '.join(
        f'a{t["ordinal"]} {t["codec"]}->copy' if t['action'] == 'copy'
        else f'a{t["ordinal"]} {t["codec"]}->opus {t["bitrate"] // 1000}k ({t["channels"]}ch)'
        for t in audio_plan
    )
    print(f'Audio: {audio_summary or "none"}')
    subs_summary = ', '.join(
        f's{s["ordinal"]} {s["codec"]}->{"copy" if container == "mkv" else "mov_text"}'
        for s in subs_kept
    )
    dropped_summary = ', '.join(f'{d["codec"]} dropped' for d in subs_dropped)
    print(f'Subtitles: {subs_summary or "none"}'
          + (f'; dropped: {dropped_summary}' if subs_dropped else ''))


def encode_once(file_input: Path, output_path: Path, q: int,
                use_hw: bool, container: str) -> int:
    info = probe.get_media_info(str(file_input))
    info['source'] = str(file_input)
    source_size = info['size']

    quality_value, preset, encoder_name = encoder_for(q, use_hw)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print_plan(info, encoder_name, container)

    progress_fn = make_progress_printer()

    if output_path.exists():
        output_path.unlink()

    error = encode.run_encode(
        str(file_input), str(output_path), info, quality_value,
        use_hw, preset, container, progress_fn, lambda: CANCELLED,
    )

    print()

    if CANCELLED:
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


def run_test(file_input: Path, args, use_hw: bool) -> int:
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
            code = encode_once(Path(seg_path), out, q, use_hw, args.container)
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
            'quality for size. Resolution, framerate, all audio tracks and subtitles '
            'are preserved. Audio in non-optimal codecs is re-encoded to Opus at '
            'high quality without loudness change.'
        ),
    )
    parser.add_argument('-q', dest='quality', type=int, choices=range(1, 11),
                        metavar='1..10', default=5,
                        help='Quality level (default 5): perceptual tier from '
                             'source-preserving (10) to small-and-acceptable (1)')
    parser.add_argument('-c', dest='container', choices=['mkv', 'mp4'], default='mkv',
                        help='Output container (default mkv)')
    parser.add_argument('--software', action='store_true',
                        help='Use software SVT-AV1 (slower but better quality; '
                             'default is hardware VAAPI AV1)')
    parser.add_argument('-t', dest='test', action='store_true',
                        help='Test mode: cut 1 minute from the middle and encode '
                             'samples at q=1,3,5,7,9 into the output directory.')
    parser.add_argument('input', type=str, help='Source video file')
    parser.add_argument('output', nargs='?', default=None,
                        help='Target directory or output file path. '
                             'If it matches the source directory, a .qN.av1 suffix is added.')

    args = parser.parse_args()

    file_input = Path(args.input).expanduser().resolve()
    if not file_input.is_file():
        print(f'Error: input file not found: {file_input}', file=sys.stderr)
        return 1

    try:
        probe.get_media_info(str(file_input))
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f'Error: could not read video properties ({e})', file=sys.stderr)
        return 1

    use_hw = (not args.software) and probe.will_ha_work()
    if not args.software and not probe.will_ha_work():
        print('Warning: hardware VAAPI AV1 unavailable, falling back to software SVT-AV1')

    if args.test:
        return run_test(file_input, args, use_hw)

    output_path = resolve_output(file_input, args.output, args.quality, args.container)
    if output_path == file_input:
        print('Error: output path resolves to the input file', file=sys.stderr)
        return 1

    return encode_once(file_input, output_path, args.quality, use_hw, args.container)


if __name__ == '__main__':
    sys.exit(main())
