"""The blur and brightness check at intake, in code with no model call.

A photo that fails is a prompt to take it again, and staff can still keep it. The thresholds are
`PhotoChecks` in app/settings.py, and docs/architecture.md says how they were measured.
"""

import io
import math
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageStat

from app.settings import PhotoChecks

# The Laplacian, which is near zero on smooth areas and large across a sharp edge. Pillow clips a
# filtered pixel to 0 to 255, so the kernel and its negative give the two signs separately.
_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=0)
_NEGATIVE_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, -1, 0, -1, 4, -1, 0, -1, 0], scale=1, offset=0)

TOO_DARK = "It's too dark to see the item well. Take it again with more light."
WASHED_OUT = "It's so bright that the item looks washed out. Take it again out of direct light."
BLURRY = "It looks blurry. Hold the phone still and take it again."


@dataclass(frozen=True)
class PhotoMeasures:
    # The Laplacian variance of the sharpest piece of the photo.
    sharpness: float
    # The brightness, out of 255, that the darkest and the brightest share of pixels reach.
    dark_end: int
    bright_end: int


def _variance(positive: Image.Image, negative: Image.Image) -> float:
    """The variance of the signed Laplacian, from its positive and negative halves."""
    up, down = ImageStat.Stat(positive), ImageStat.Stat(negative)
    count = up.count[0]
    mean = (up.sum[0] - down.sum[0]) / count
    return (up.sum2[0] + down.sum2[0]) / count - mean * mean


def _sharpness(gray: Image.Image, grid: int) -> float:
    # Pillow leaves the outermost pixels unfiltered, so they are cut off before measuring.
    box = (1, 1, gray.width - 1, gray.height - 1)
    positive = gray.filter(_LAPLACIAN).crop(box)
    negative = gray.filter(_NEGATIVE_LAPLACIAN).crop(box)
    width, height = positive.size
    columns, rows = min(grid, width), min(grid, height)
    best = 0.0
    for column in range(columns):
        for row in range(rows):
            piece = (
                width * column // columns,
                height * row // rows,
                width * (column + 1) // columns,
                height * (row + 1) // rows,
            )
            best = max(best, _variance(positive.crop(piece), negative.crop(piece)))
    return best


def _ends(gray: Image.Image, share: float) -> tuple[int, int]:
    """The brightness the darkest and the brightest `share` of the pixels reach."""
    histogram = gray.histogram()
    wanted = math.ceil(sum(histogram) * share)
    dark = bright = 0
    seen = 0
    for level, count in enumerate(histogram):
        seen += count
        if seen >= wanted:
            dark = level
            break
    seen = 0
    for level in range(255, -1, -1):
        seen += histogram[level]
        if seen >= wanted:
            bright = level
            break
    return dark, bright


def measure(data: bytes, checks: PhotoChecks) -> PhotoMeasures | None:
    """The photo's sharpness and brightness, or None for one too small to judge."""
    with Image.open(io.BytesIO(data)) as image:
        # Scaling first lets Pillow decode a large JPEG at a fraction of its size.
        image.thumbnail((checks.long_side, checks.long_side))
        gray = image.convert("L")
    if gray.width < 3 or gray.height < 3:
        return None
    dark, bright = _ends(gray, checks.tail_share)
    return PhotoMeasures(_sharpness(gray, checks.grid), dark, bright)


def retake_reason(measures: PhotoMeasures, checks: PhotoChecks) -> str | None:
    """What is wrong with the photo, brightness first, because a dark photo also shows no edges."""
    if measures.bright_end < checks.min_bright_end:
        return TOO_DARK
    if measures.dark_end > checks.max_dark_end:
        return WASHED_OUT
    if measures.sharpness < checks.min_sharpness:
        return BLURRY
    return None
