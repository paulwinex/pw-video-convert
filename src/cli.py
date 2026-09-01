#!/usr/bin/python3

import argparse
import os
import signal
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

import probe
import quality
import encode


CANCELLED = False


def _sigint_handler(signum, frame):
    global CANCELLED
    CANCELLED = True


signal.signal(signal.SIGINT, _sigint_handler)


def bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def make_progress_printer():
    columns, _ = shutil.get_terminal_size(fallback=(80, 24))

    def print_progress(fraction: float, seconds_left: Optional[int]) -> None:
        percent = int(round(fraction * 100, 0))
        bar_len = max(columns - 30, 10)
        filled = int(bar_len * fraction)
        bar = '#' * filled + '-' * (bar_len - filled)

        if seconds_left is None:
            line = f'\r {percent}% [{bar}]'
        else:
            hours, rem = divmod(seconds_left, 3600)
            mins, secs = divmod(rem, 60)
            eta = f'{hours}:{mins:02d}:{secs:02d}' if hours else f'{mins}:{secs:02d}'
            line = f'\r {percent}% [{bar}] ETA {eta}'

        print(bold(line.ljust(columns)), end='', flush=True)

    return print_progress


def resolve_output(file_input: Path, output_arg: Optional[str], q: int, container: str) -> Path:
    ext = 'mkv' if container == 'mkv' else 'mp4'

    if output_arg is None:
        target_dir = file_input.parent
    else:
        candidate = Path(output_arg)
        if candidate.is_dir() or output_arg.endswith(os.sep):
            target_dir = candidate
        else:
            return candidate

    stem = file_input.stem
    same_dir = target_dir.resolve() == file_input.parent.resolve()

    name = f'{stem}.q{q}.av1.{ext}' if same_dir else f'{stem}.{ext}'
    return target_dir / name


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
            'q=10 keeps the source video bitrate; lower levels reduce it. '
            'Resolution, framerate, all audio tracks and subtitles are preserved. '
            'Audio in non-optimal codecs is re-encoded to Opus at high quality.'
        ),
    )
    parser.add_argument('-q', dest='quality', type=int, choices=range(1, 11),
                        metavar='1..10', default=5,
                        help='Quality level: multiplier on source video bitrate '
                             '(q10 = same bitrate as source)')
    parser.add_argument('-c', dest='container', choices=['mkv', 'mp4'], default='mkv',
                        help='Output container (default mkv)')
    parser.add_argument('--software', action='store_true',
                        help='Force software SVT-AV1 encoding instead of hardware VAAPI')
    parser.add_argument('input', type=str, help='Source video file')
    parser.add_argument('output', nargs='?', default=None,
                        help='Target directory or output file path. '
                             'If it matches the source directory, a .qN.av1 suffix is added.')

    args = parser.parse_args()

    file_input = Path(args.input)
    if not file_input.is_file():
        print(f'Error: input file not found: {file_input}', file=sys.stderr)
        return 1

    try:
        info = probe.get_media_info(str(file_input))
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f'Error: could not read video properties ({e})', file=sys.stderr)
        return 1

    source_size = info['size']
    source_video_bitrate = probe.estimate_video_bitrate(info)
    fps = info['video']['fps'] if info['video']['fps'] != -1 else 60.0

    hw = not args.software and probe.will_ha_work()
    encoder_name = 'av1_vaapi (hardware)' if hw else f'libsvtav1 preset {quality.SVT_PRESET_BY_Q[args.quality]} (software, 2-pass)'

    output_path = resolve_output(file_input, args.output, args.quality, args.container)
    if output_path.resolve() == file_input.resolve():
        print('Error: output path resolves to the input file', file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)

    audio_plan = encode.build_audio_plan(info)
    subs_kept, subs_dropped = encode.build_subtitle_plan(info)

    print(f'Input: {file_input} ({fmt_size(source_size)})')
    print(f'Source video bitrate: ~{source_video_bitrate // 1000} kbps, '
          f'{info["video"]["width"]}x{info["video"]["height"]}, '
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

    factor = quality.multiplier_for_quality(args.quality)
    attempts = 0
    final_size = 0

    with TemporaryDirectory(prefix='constrict-mod-pass-') as tmpdir:
        log_path = None if hw else f'{tmpdir}/ffmpeg2pass'

        while True:
            attempts += 1
            video_bitrate = round(source_video_bitrate * factor)
            expected_bits = (
                video_bitrate * info['duration']
                + sum(t['bitrate'] * info['duration'] for t in audio_plan if t['bitrate'])
            )
            expected_bytes = int(expected_bits / 8 * 1.02)

            print(f'\n:: Attempt {attempts} -- video {video_bitrate // 1000} kbps '
                  f'(q{args.quality}, factor {factor:.3f}), target ~{fmt_size(expected_bytes)}')

            if output_path.exists():
                output_path.unlink()

            error = encode.run_encode(
                str(file_input), str(output_path), info, video_bitrate,
                hw, quality.SVT_PRESET_BY_Q[args.quality], args.container,
                log_path, progress_fn, lambda: CANCELLED,
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
            percent_of_target = (final_size / expected_bytes) * 100.0

            print(f'   Result: {fmt_size(final_size)} ({percent_of_target:.1f}% of target)')

            if percent_of_target <= 100 + quality.TOLERANCE_PERCENT:
                break

            if attempts >= 4 or video_bitrate <= 5000:
                print('   Stopping: overshoot could not be corrected within tolerance.')
                break

            factor *= 0.98 * (100 / percent_of_target)

    savings = (1 - final_size / source_size) * 100.0
    print(f'\nDone: {output_path} ({fmt_size(final_size)})')
    print(f'Savings vs source: {savings:.1f}% '
          f'({fmt_size(source_size)} -> {fmt_size(final_size)})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
