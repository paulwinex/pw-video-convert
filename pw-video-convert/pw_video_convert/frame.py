import re
from typing import List, Optional, Tuple, Union

RESOLUTION_RE = re.compile(r'^(\d+)x(\d+)$')

AV1_MIN_W = 128
AV1_ALIGN_W = 64
AV1_MIN_H = 80
AV1_ALIGN_H = 16


def parse_resolution(text: str) -> Tuple[int, int]:
    match = RESOLUTION_RE.match(text.strip())
    if not match:
        raise ValueError(f"invalid resolution {text!r}: expected WxH, e.g. 1920x1080")
    width, height = int(match.group(1)), int(match.group(2))
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid resolution {text!r}: sizes must be positive")
    return width, height


def round_up(value: int, align: int) -> int:
    return ((value + align - 1) // align) * align


def av1_supported_size(width: int, height: int) -> Tuple[int, int]:
    """Sizes the AV1 encoders accept unchanged (no encoder-side padding)."""
    return (
        max(round_up(width, AV1_ALIGN_W), AV1_MIN_W),
        max(round_up(height, AV1_ALIGN_H), AV1_MIN_H),
    )


def _even_in_range(value: float, limit: int) -> int:
    """Nearest even size that does not exceed the box."""
    return max(min(int(value + 0.5) & ~1, limit - (limit % 2)), 2)


def fit_within(src_w: int, src_h: int, box_w: int, box_h: int) -> Tuple[int, int]:
    """Largest source-sized frame that fits the box, never upscaling.

    Dimensions are rounded to the nearest even value (capped by the box) so chroma
    subsampling stays exact; float error from the scale factor never pushes a
    perfect ratio (e.g. 1920x1080 -> 1280x720) two pixels short of the target.
    """
    if src_w <= box_w and src_h <= box_h:
        return src_w, src_h
    scale = min(box_w / src_w, box_h / src_h)
    return (_even_in_range(src_w * scale, box_w),
            _even_in_range(src_h * scale, box_h))


def coerce_resolution(value: Optional[Union[str, List[int], Tuple[int, int]]]
                      ) -> Optional[Tuple[int, int]]:
    """Normalize any accepted resolution form to a (width, height) tuple."""
    if value is None:
        return None
    if isinstance(value, str):
        return parse_resolution(value)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        width, height = value[0], value[1]
        if isinstance(width, int) and isinstance(height, int) \
                and width > 0 and height > 0:
            return (width, height)
    raise ValueError(
        f"invalid resolution {value!r}: expected WxH or [width, height]"
    )


def plan_video(source_w: int, source_h: int,
               resolution: Optional[Union[str, List[int], Tuple[int, int]]] = None
               ) -> dict:
    box = coerce_resolution(resolution) or (source_w, source_h)
    scaled = fit_within(source_w, source_h, box[0], box[1])
    final = av1_supported_size(box[0], box[1])

    filters: List[str] = []
    if scaled != (source_w, source_h):
        filters.append(f'scale={scaled[0]}:{scaled[1]}')
    if final != scaled:
        filters.append(f'pad={final[0]}:{final[1]}:(ow-iw)/2:(oh-ih)/2:color=black')

    return {
        'source': (source_w, source_h),
        'box': box,
        'scaled': scaled,
        'final': final,
        'filters': filters,
    }
