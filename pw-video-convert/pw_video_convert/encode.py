import re
import shlex
import subprocess
from tempfile import TemporaryFile
from typing import Callable, List, Optional, Tuple, Union

from . import frame

OPTIMAL_AUDIO_CODECS = {'aac', 'opus'}
COPYABLE_SUB_CODECS = {'subrip', 'ass', 'webvtt'}
MKV_NATIVE_SUB_CODECS = {'dvd_subtitle', 'hdmf_pgs'}
FORMAT_NAMES = {'mkv': 'matroska', 'mp4': 'mp4'}

OPUS_MAX_BITRATE = 512000

# libopus only accepts the Vorbis channel layouts (one per channel count).
# FFmpeg's default layout for 4 channels is 4.0, which libopus rejects, so
# every re-encoded track has to request the matching Vorbis layout explicitly.
OPUS_LAYOUTS = {
    1: 'mono',
    2: 'stereo',
    3: '3.0',
    4: 'quad',
    5: '5.0',
    6: '5.1',
    7: '6.1',
    8: '7.1',
}


def audio_target_bitrate(channels: int, source_bitrate: Optional[int]) -> int:
    if channels >= 7:
        floor, default = 640000, 512000
    elif channels > 2:
        floor, default = 448000, 512000
    elif channels == 2:
        floor, default = 128000, 160000
    else:
        floor, default = 96000, 128000

    if source_bitrate is None:
        return min(default, OPUS_MAX_BITRATE)
    return min(source_bitrate, max(floor, round(source_bitrate * 0.35)), OPUS_MAX_BITRATE)


def _opus_params(channels: int, source_bitrate: Optional[int]) -> Tuple[int, str, int]:
    """Resolve channels, Vorbis layout and bitrate for a libopus re-encode."""
    layout = OPUS_LAYOUTS.get(channels)
    if layout is None:
        # libopus has no Vorbis layout above 8 channels; downmix.
        channels = 2
        layout = OPUS_LAYOUTS[channels]
    return channels, layout, audio_target_bitrate(channels, source_bitrate)


def build_audio_plan(info: dict, audio: Optional[List[int]] = None) -> List[dict]:
    """Plan audio tracks; `audio` is a list of 0-based ordinals to keep (None = all)."""
    if audio is not None:
        count = len(info['audio'])
        for ordinal in audio:
            if not 0 <= ordinal < count:
                raise ValueError(
                    f'audio track {ordinal + 1} out of range '
                    f'(file has {count} audio tracks)'
                )
    plan = []
    for ordinal, track in enumerate(info['audio']):
        if audio is not None and ordinal not in audio:
            continue
        if track['codec'] in OPTIMAL_AUDIO_CODECS:
            action = 'copy'
            bitrate = None
            channels = track['channels']
            layout = None
        else:
            action = 'opus'
            channels, layout, bitrate = _opus_params(
                track['channels'], track['stream_bitrate']
            )
        plan.append({
            'ordinal': ordinal,
            'codec': track['codec'],
            'action': action,
            'bitrate': bitrate,
            'channels': channels,
            'layout': layout,
        })
    return plan


def build_subtitle_plan(info: dict, container: str = 'mkv') -> Tuple[List[dict], List[dict]]:
    kept = []
    dropped = []
    copyable = set(COPYABLE_SUB_CODECS)
    if container == 'mkv':
        copyable |= MKV_NATIVE_SUB_CODECS
    for ordinal, sub in enumerate(info['subs']):
        if sub['codec'] in copyable:
            kept.append({**sub, 'ordinal': ordinal})
        else:
            dropped.append(sub)
    return kept, dropped


def _hw_vf(bit_depth: int) -> str:
    fmt = 'p010' if bit_depth == 10 else 'nv12'
    return f'format={fmt},hwupload'


def build_encode_cmd(
    file_input: str,
    file_output: str,
    info: dict,
    quality_value: int,
    hw: bool,
    preset: Optional[str],
    container: str,
    resolution: Optional[Union[str, List[int]]] = None,
    audio: Optional[List[int]] = None,
    audio_add: Optional[List[dict]] = None,
) -> List[str]:
    video = info['video']
    plan = frame.plan_video(video['width'], video['height'], resolution)
    filters = list(plan['filters'])

    cmd = ['ffmpeg', '-y', '-progress', 'pipe:1']
    if hw:
        cmd.extend(['-vaapi_device', '/dev/dri/renderD128'])
    cmd.extend(['-i', file_input])
    for item in (audio_add or []):
        cmd.extend(['-i', item['path']])

    if hw:
        cmd.extend(['-vf', ','.join(filters + [_hw_vf(video['bit_depth'])])])
        cmd.extend([
            '-c:v', 'av1_vaapi',
            '-rc_mode:v', 'CQP',
            '-global_quality:v', str(quality_value),
        ])
    else:
        if filters:
            cmd.extend(['-vf', ','.join(filters)])
        cmd.extend([
            '-c:v', 'libsvtav1',
            '-preset', preset,
            '-crf', str(quality_value),
            '-pix_fmt', 'yuv420p10le' if video['bit_depth'] == 10 else 'yuv420p',
        ])

    cmd.extend(['-map', '0:v:0'])

    audio_plan = build_audio_plan(info, audio)
    # -map refers to input ordinals, per-stream options to output indexes;
    # they diverge once tracks are filtered out.
    for out_index, track in enumerate(audio_plan):
        cmd.extend(['-map', f'0:a:{track["ordinal"]}'])
        if track['action'] == 'copy':
            cmd.extend([f'-c:a:{out_index}', 'copy'])
        else:
            cmd.extend([
                f'-c:a:{out_index}', 'libopus',
                f'-b:a:{out_index}', str(track['bitrate']),
                f'-ac:a:{out_index}', str(track['channels']),
                f'-ch_layout:a:{out_index}', track['layout'],
            ])

    # External audio files: each is an extra -i (input index i+1); its first
    # audio stream is re-encoded to opus and titled with its label.
    for i, item in enumerate(audio_add or []):
        input_index = i + 1
        out_index = len(audio_plan) + i
        channels, layout, bitrate = _opus_params(
            item['channels'], item.get('stream_bitrate')
        )
        cmd.extend(['-map', f'{input_index}:a:0'])
        cmd.extend([
            f'-c:a:{out_index}', 'libopus',
            f'-b:a:{out_index}', str(bitrate),
            f'-ac:a:{out_index}', str(channels),
            f'-ch_layout:a:{out_index}', layout,
            f'-metadata:s:a:{out_index}', f'title={item["label"]}',
        ])

    subs_kept, _ = build_subtitle_plan(info, container)
    for sub in subs_kept:
        cmd.extend(['-map', f'0:s:{sub["ordinal"]}'])
        if container == 'mkv':
            cmd.extend([f'-c:s:{sub["ordinal"]}', 'copy'])
        else:
            cmd.extend([f'-c:s:{sub["ordinal"]}', 'mov_text'])

    cmd.extend(['-f', FORMAT_NAMES[container], file_output])
    return cmd


def get_progress(
    ffmpeg_cmd: List[str],
    output_fn: Callable[[float, Optional[int]], None],
    frame_count: int,
    cancel_event: Callable[[], bool],
) -> Tuple[Optional[float], Optional[str]]:
    with TemporaryFile() as err_file:
        proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=err_file,
        )

        frame = 0
        fps_sum = 0.0
        pulse_counter = 0
        avg_counter = 0
        fps: Optional[float] = None

        if proc.stdout is not None:
            for line in proc.stdout:
                line_string = line.decode('utf-8')

                if line_string.startswith('frame='):
                    match = re.search(r'[0-9]+', line_string)
                    if match:
                        frame = int(match.group())
                elif line_string.startswith('fps='):
                    progress_fraction = min(frame / max(frame_count, 1), 1.0)

                    pulse_counter += 1
                    if pulse_counter >= 10:
                        match = re.search(r'[0-9]+[.]?[0-9]*', line_string)
                        if match:
                            fps = float(match.group())
                            avg_counter += 1
                            fps_sum += fps

                    frames_left = frame_count - frame
                    seconds_left = None
                    if fps and fps > 0:
                        seconds_left = max(int(frames_left // fps), 0)

                    output_fn(progress_fraction, seconds_left)

                if cancel_event():
                    proc.kill()
                    return (None, None)

        avg = fps_sum / avg_counter if avg_counter else None

        proc.wait()
        returncode = proc.poll()

        if returncode != 0:
            err_file.flush()
            err_file.seek(0, 0)
            errors = err_file.read().decode('utf-8')
            tail = '\n'.join(errors.strip().split('\n')[-6:])
            return (avg, f'ffmpeg exited with code {returncode}:\n{tail}')

        return (avg, None)


def run_encode(
    file_input: str,
    file_output: str,
    info: dict,
    quality_value: int,
    hw: bool,
    preset: Optional[str],
    container: str,
    output_fn: Callable[[float, Optional[int]], None],
    cancel_event: Callable[[], bool],
    resolution: Optional[Union[str, List[int]]] = None,
    audio: Optional[List[int]] = None,
    audio_add: Optional[List[dict]] = None,
) -> Optional[str]:
    cmd = build_encode_cmd(
        file_input, file_output, info, quality_value, hw, preset, container,
        resolution, audio, audio_add,
    )
    print(f'Command: {shlex.join(cmd)}')
    _, error = get_progress(cmd, output_fn, info['frame_count'], cancel_event)
    return error
