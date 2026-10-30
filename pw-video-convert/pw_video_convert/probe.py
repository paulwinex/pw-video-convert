import json
import subprocess
from typing import Optional


HDR_SIDE_DATA = [
    'Content light level metadata',
    'Mastering display metadata',
]


def _ffprobe(args: list[str], file_input: str) -> bytes:
    return subprocess.check_output(['ffprobe', '-v', 'error', *args, file_input])


def get_media_info(file_input: str) -> dict:
    out = _ffprobe([
        '-show_entries',
        'stream=index,codec_type,codec_name,pix_fmt,width,height,channels,'
        'bit_rate,avg_frame_rate:format=duration,size'
        ':stream_side_data=side_data_type:stream_tags=language,title',
        '-of', 'json',
    ], file_input)
    data = json.loads(out)

    fmt = data['format']
    duration = float(fmt['duration'])
    size = int(fmt['size'])

    video: Optional[dict] = None
    audio: list[dict] = []
    subs: list[dict] = []

    for stream in data.get('streams', []):
        stype = stream.get('codec_type')
        if stype == 'video' and video is None:
            pix_fmt = stream.get('pix_fmt', '')
            side_data = stream.get('side_data_list', []) or []
            hdr = any(sd.get('side_data_type') in HDR_SIDE_DATA for sd in side_data)
            bit_depth = 10 if '10le' in pix_fmt else 8
            fps_fraction = stream.get('avg_frame_rate', '0/0')
            num, _, den = fps_fraction.partition('/')
            try:
                fps = float(num) / float(den) if den and int(den) != 0 else -1.0
            except ValueError:
                fps = -1.0
            video = {
                'index': stream['index'],
                'codec_name': stream.get('codec_name', ''),
                'width': stream.get('width', 0),
                'height': stream.get('height', 0),
                'pix_fmt': pix_fmt,
                'bit_depth': bit_depth,
                'hdr': hdr,
                'fps': fps,
                'stream_bitrate': _int_or_none(stream.get('bit_rate')),
            }
        elif stype == 'audio':
            tags = stream.get('tags') or {}
            audio.append({
                'index': stream['index'],
                'codec': stream.get('codec_name', ''),
                'channels': int(stream.get('channels', 1) or 1),
                'stream_bitrate': _int_or_none(stream.get('bit_rate')),
                'language': tags.get('language'),
                'title': tags.get('title'),
            })
        elif stype == 'subtitle':
            subs.append({
                'index': stream['index'],
                'codec': stream.get('codec_name', ''),
            })

    if video is None:
        raise ValueError('no video stream found')

    frame_count = get_frame_count(file_input)

    return {
        'duration': duration,
        'size': size,
        'video': video,
        'audio': audio,
        'subs': subs,
        'frame_count': frame_count,
    }


def get_audio_tracks(file_input: str) -> list[dict]:
    """Fast header-only audio listing for UIs (no packet counting).

    Returns tracks with user-facing 1-based `track` numbers.
    """
    out = _ffprobe([
        '-select_streams', 'a',
        '-show_entries',
        'stream=index,codec_name,channels,bit_rate:stream_tags=language,title',
        '-of', 'json',
    ], file_input)
    tracks = []
    for position, stream in enumerate(json.loads(out).get('streams', [])):
        tags = stream.get('tags') or {}
        tracks.append({
            'track': position + 1,
            'index': stream.get('index'),
            'codec': stream.get('codec_name', ''),
            'channels': int(stream.get('channels', 1) or 1),
            'language': tags.get('language'),
            'title': tags.get('title'),
            'stream_bitrate': _int_or_none(stream.get('bit_rate')),
        })
    return tracks


def _int_or_none(value: Optional[str]) -> Optional[int]:
    if value is None or value == 'N/A':
        return None
    try:
        return int(value)
    except ValueError:
        return None


def get_frame_count(file_input: str) -> int:
    out = _ffprobe([
        '-select_streams', 'v:0',
        '-count_packets',
        '-show_entries', 'stream=nb_read_packets',
        '-of', 'json',
    ], file_input)
    streams = json.loads(out).get('streams', [])
    if not streams:
        return 1
    try:
        return int(streams[0]['nb_read_packets'])
    except (ValueError, KeyError):
        return 1


def estimate_video_bitrate(info: dict) -> int:
    video = info['video']
    duration = info['duration']

    if video['stream_bitrate']:
        return video['stream_bitrate']

    total_bits = info['size'] * 8
    audio_bits = sum(
        a['stream_bitrate'] * duration for a in info['audio'] if a['stream_bitrate']
    )
    video_bits = max(total_bits - audio_bits, 0)
    return round(video_bits / duration)


def will_ha_work() -> bool:
    try:
        out = subprocess.check_output(['vainfo', '--display', 'drm'])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

    text = out.decode('utf-8').replace(' ', '').replace('\t', '')
    lines = text.split('\n')
    valid = [
        'VAProfileAV1Profile0:VAEntrypointEncSlice',
        'VAProfileAV1Profile0:VAEntrypointEncSliceLP',
    ]
    return any(entry in lines for entry in valid)
