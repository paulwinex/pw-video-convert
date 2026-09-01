#!/usr/bin/python3

import os
import re
import subprocess
from tempfile import TemporaryFile
from typing import Callable, List, Optional, Tuple

OPTIMAL_AUDIO_CODECS = {'aac', 'opus'}
COPYABLE_SUB_CODECS = {'subrip', 'ass', 'webvtt'}
FORMAT_NAMES = {'mkv': 'matroska', 'mp4': 'mp4'}


OPUS_MAX_BITRATE = 512000


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


def build_audio_plan(info: dict) -> List[dict]:
    plan = []
    for ordinal, track in enumerate(info['audio']):
        if track['codec'] in OPTIMAL_AUDIO_CODECS:
            action = 'copy'
            bitrate = None
        else:
            action = 'opus'
            bitrate = audio_target_bitrate(track['channels'], track['stream_bitrate'])
        plan.append({
            'ordinal': ordinal,
            'codec': track['codec'],
            'action': action,
            'bitrate': bitrate,
            'channels': track['channels'],
        })
    return plan


def build_subtitle_plan(info: dict) -> Tuple[List[dict], List[dict]]:
    kept = []
    dropped = []
    for ordinal, sub in enumerate(info['subs']):
        if sub['codec'] in COPYABLE_SUB_CODECS:
            kept.append({**sub, 'ordinal': ordinal})
        else:
            dropped.append(sub)
    return kept, dropped


def _common_head(file_input: str, hw: bool) -> List[str]:
    cmd = ['ffmpeg', '-y', '-progress', 'pipe:1']
    if hw:
        cmd.extend(['-vaapi_device', '/dev/dri/renderD128'])
    cmd.extend(['-i', file_input])
    return cmd


def _hw_vf(bit_depth: int) -> str:
    fmt = 'p010' if bit_depth == 10 else 'nv12'
    return f'format={fmt},hwupload'


def build_encode_passes(
    file_input: str,
    file_output: str,
    info: dict,
    video_bitrate: int,
    hw: bool,
    preset: str,
    container: str,
    log_path: Optional[str],
) -> List[dict]:
    video = info['video']
    audio_plan = build_audio_plan(info)
    subs_kept, _ = build_subtitle_plan(info)

    passes: List[dict] = []

    if hw:
        cmd = _common_head(file_input, True)
        cmd.extend(['-vf', _hw_vf(video['bit_depth'])])
        cmd.extend([
            '-c:v', 'av1_vaapi',
            '-b:v', str(video_bitrate),
        ])

        cmd.extend(['-map', '0:v:0'])

        for track in audio_plan:
            cmd.extend(['-map', f'0:a:{track["ordinal"]}'])
            if track['action'] == 'copy':
                cmd.extend([f'-c:a:{track["ordinal"]}', 'copy'])
            else:
                cmd.extend([
                    f'-c:a:{track["ordinal"]}', 'libopus',
                    f'-b:a:{track["ordinal"]}', str(track['bitrate']),
                    f'-ac:a:{track["ordinal"]}', str(track['channels']),
                ])

        for sub in subs_kept:
            cmd.extend(['-map', f'0:s:{sub["ordinal"]}'])
            if container == 'mkv':
                cmd.extend([f'-c:s:{sub["ordinal"]}', 'copy'])
            else:
                cmd.extend([f'-c:s:{sub["ordinal"]}', 'mov_text'])

        cmd.extend(['-f', FORMAT_NAMES[container], file_output])
        passes.append({'cmd': cmd, 'pass_num': None})
        return passes

    pass1 = _common_head(file_input, False)
    if log_path is not None:
        pass1.extend(['-passlogfile', log_path])
    pass1.extend([
        '-c:v', 'libsvtav1',
        '-preset', preset,
        '-b:v', str(video_bitrate),
        '-pix_fmt', 'yuv420p10le' if video['bit_depth'] == 10 else 'yuv420p',
        '-pass', '1',
        '-an', '-sn',
        '-f', 'null', '/dev/null',
    ])
    passes.append({'cmd': pass1, 'pass_num': 0})

    pass2 = _common_head(file_input, False)
    if log_path is not None:
        pass2.extend(['-passlogfile', log_path])
    pass2.extend([
        '-c:v', 'libsvtav1',
        '-preset', preset,
        '-b:v', str(video_bitrate),
        '-pix_fmt', 'yuv420p10le' if video['bit_depth'] == 10 else 'yuv420p',
        '-pass', '2',
    ])

    pass2.extend(['-map', '0:v:0'])

    for track in audio_plan:
        pass2.extend(['-map', f'0:a:{track["ordinal"]}'])
        if track['action'] == 'copy':
            pass2.extend([f'-c:a:{track["ordinal"]}', 'copy'])
        else:
            pass2.extend([
                f'-c:a:{track["ordinal"]}', 'libopus',
                f'-b:a:{track["ordinal"]}', str(track['bitrate']),
                f'-ac:a:{track["ordinal"]}', str(track['channels']),
            ])

    for sub in subs_kept:
        pass2.extend(['-map', f'0:s:{sub["ordinal"]}'])
        if container == 'mkv':
            pass2.extend([f'-c:s:{sub["ordinal"]}', 'copy'])
        else:
            pass2.extend([f'-c:s:{sub["ordinal"]}', 'mov_text'])

    pass2.extend(['-f', FORMAT_NAMES[container], file_output])
    passes.append({'cmd': pass2, 'pass_num': 1})

    return passes


def get_progress(
    ffmpeg_cmd: List[str],
    output_fn: Callable[[float, Optional[int]], None],
    frame_count: int,
    pass_num: Optional[int],
    last_pass_avg_fps: Optional[float],
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
        fps: Optional[float] = last_pass_avg_fps

        if proc.stdout is not None:
            for line in proc.stdout:
                line_string = line.decode('utf-8')

                if line_string.startswith('frame='):
                    match = re.search(r'[0-9]+', line_string)
                    if match:
                        frame = int(match.group())
                elif line_string.startswith('fps='):
                    total_frames = frame_count * (1 if pass_num is None else 2)
                    current_frame = frame_count * (pass_num or 0) + frame
                    progress_fraction = current_frame / total_frames

                    pulse_counter += 1
                    if pulse_counter >= 10:
                        match = re.search(r'[0-9]+[.]?[0-9]*', line_string)
                        if match:
                            fps = float(match.group())
                            avg_counter += 1
                            fps_sum += fps

                    frames_left = total_frames - current_frame
                    seconds_left = None
                    if fps and fps > 0:
                        seconds_left = max(int(frames_left // fps), 0)

                    output_fn(min(progress_fraction, 1.0), seconds_left)

                if cancel_event():
                    proc.kill()
                    return (None, None)

        avg = fps_sum / avg_counter if avg_counter else last_pass_avg_fps

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
    video_bitrate: int,
    hw: bool,
    preset: str,
    container: str,
    log_path: Optional[str],
    output_fn: Callable[[float, Optional[int]], None],
    cancel_event: Callable[[], bool],
) -> Optional[str]:
    passes = build_encode_passes(
        file_input, file_output, info, video_bitrate, hw, preset, container, log_path
    )

    last_avg: Optional[float] = None
    for p in passes:
        if cancel_event():
            return None
        avg, error = get_progress(
            p['cmd'], output_fn, info['frame_count'], p['pass_num'], last_avg, cancel_event
        )
        if error is not None:
            return error
        last_avg = avg

    return None
