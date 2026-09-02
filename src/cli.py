#!/usr/bin/python3

import argparse
import os
import signal
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

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
    parser.add_argument('--hw', action='store_true',
                        help='Use hardware VAAPI AV1 encoder (fast; RDNA3 HW AV1 is '
                             'less efficient than SVT-AV1 software, so files are '
                             'larger at equal q). Default: software SVT-AV1.')
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
        info = probe.get_media_info(str(file_input))
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f'Error: could not read video properties ({e})', file=sys.stderr)
        return 1

    source_size = info['size']

    use_hw = args.hw and probe.will_ha_work()
    if args.hw and not probe.will_ha_work():
        print('Warning: hardware VAAPI AV1 unavailable, falling back to software SVT-AV1')

    if use_hw:
        quality_value = quality.vaapi_quality_for_quality(args.quality)
        preset = None
        encoder_name = f'av1_vaapi CQP qp={quality_value} (hardware)'
    else:
        quality_value = quality.crf_for_quality(args.quality)
        preset = quality.preset_for_quality(args.quality)
        encoder_name = f'libsvtav1 preset {preset} crf {quality_value} (software)'

    output_path = resolve_output(file_input, args.output, args.quality, args.container)
    if output_path == file_input:
        print('Error: output path resolves to the input file', file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)

    audio_plan = encode.build_audio_plan(info)
    subs_kept, subs_dropped = encode.build_subtitle_plan(info, args.container)

    print(f'Input: {file_input} ({fmt_size(source_size)})')
    print(f'Source: {info["video"]["width"]}x{info["video"]["height"]}, '
          f'{info["video"]["bit_depth"]}-bit'
          + (', HDR metadata present' if info['video']['hdr'] else ''))
    print(f'Encoder: {encoder_name}')

    audio_summary = ', '.join(
        f'a{t["ordinal"]} {t["codec"]}->copy' if t['action'] == 'copy'
        else f'a{t["ordinal"]} {t["codec"]}->opus {t["bitrate"] // 1000}k ({t["channels"]}ch)'
        for t in audio_plan
    )
    print(f'Audio: {audio_summary or "none"}')
    subs_summary = ', '.join(
        f's{s["ordinal"]} {s["codec"]}->{"copy" if args.container == "mkv" else "mov_text"}'
        for s in subs_kept
    )
    dropped_summary = ', '.join(f'{d["codec"]} dropped' for d in subs_dropped)
    print(f'Subtitles: {subs_summary or "none"}'
          + (f'; dropped: {dropped_summary}' if subs_dropped else ''))

    progress_fn = make_progress_printer()

    if output_path.exists():
        output_path.unlink()

    error = encode.run_encode(
        str(file_input), str(output_path), info, quality_value,
        use_hw, preset, args.container, progress_fn, lambda: CANCELLED,
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


if __name__ == '__main__':
    sys.exit(main())
