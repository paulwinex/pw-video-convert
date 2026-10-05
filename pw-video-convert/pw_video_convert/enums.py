class FpsMode:
    AUTO = 0
    PREFER_CLEAR = 1
    PREFER_SMOOTH = 2


class VideoCodec:
    H264 = 0
    HEVC = 1
    AV1 = 2
    VP9 = 3


class SourceState:
    PENDING = 0
    COMPRESSING = 1
    COMPLETE = 2
    ERROR = 3
    BROKEN = 4
    INCOMPATIBLE = 5
    WARN = 6

