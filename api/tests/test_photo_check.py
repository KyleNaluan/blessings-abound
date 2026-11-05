"""The blur and brightness check on generated sample photos, with the thresholds from config."""

import io

import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.photo_check import BLURRY, TOO_DARK, WASHED_OUT, PhotoMeasures, measure, retake_reason
from app.pipeline import photo_retake_reason
from app.settings import PhotoChecks

CHECKS = PhotoChecks()


def scene(size: tuple[int, int] = (800, 600)) -> Image.Image:
    """A made-up product photo: a box with a label and a cord on a shaded backdrop."""
    width, height = size
    image = Image.eval(Image.linear_gradient("L").resize(size), lambda value: 150 + value // 4)
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image)
    unit = width // 40
    draw.rectangle((10 * unit, 6 * unit, 30 * unit, 22 * unit), fill=(60, 70, 90))
    draw.rectangle((13 * unit, 9 * unit, 27 * unit, 13 * unit), fill=(235, 230, 220))
    for row in range(3):
        top = 15 * unit + row * 2 * unit
        draw.rectangle((13 * unit, top, 24 * unit, top + unit // 2), fill=(200, 40, 40))
    draw.line((30 * unit, 18 * unit, 38 * unit, height - unit), fill=(20, 20, 20), width=unit // 3)
    draw.ellipse((4 * unit, 20 * unit, 8 * unit, 24 * unit), fill=(240, 200, 60))
    return image


def encode(image: Image.Image, kind: str = "JPEG") -> bytes:
    output = io.BytesIO()
    image.save(output, format=kind, quality=90)
    return output.getvalue()


def sharp() -> bytes:
    return encode(scene())


def blurry() -> bytes:
    return encode(scene().filter(ImageFilter.GaussianBlur(4)))


def dark() -> bytes:
    # About a fifth of the light, as in a back room with the lights off.
    return encode(Image.eval(scene(), lambda value: value // 5))


def overexposed() -> bytes:
    # Everything pushed up toward white, as under a bright window.
    return encode(Image.eval(scene(), lambda value: 220 + value * 35 // 255))


def measures(data: bytes) -> PhotoMeasures:
    result = measure(data, CHECKS)
    assert result is not None
    return result


def test_a_sharp_photo_passes() -> None:
    assert photo_retake_reason(sharp()) is None


def test_a_blurry_photo_is_a_retake() -> None:
    assert photo_retake_reason(blurry()) == BLURRY
    assert measures(blurry()).sharpness < CHECKS.min_sharpness <= measures(sharp()).sharpness


def test_a_dark_photo_is_a_retake() -> None:
    assert photo_retake_reason(dark()) == TOO_DARK
    assert measures(dark()).bright_end < CHECKS.min_bright_end


def test_an_overexposed_photo_is_a_retake() -> None:
    assert photo_retake_reason(overexposed()) == WASHED_OUT
    assert measures(overexposed()).dark_end > CHECKS.max_dark_end


def test_brightness_is_named_before_blur() -> None:
    # A dark photo shows few edges too, and more light is what fixes it.
    murky = encode(Image.eval(scene().filter(ImageFilter.GaussianBlur(4)), lambda v: v // 5))
    assert photo_retake_reason(murky) == TOO_DARK


def test_a_plain_backdrop_does_not_make_a_sharp_item_blurry() -> None:
    # A small item in one corner of a large plain wall.
    image = Image.new("RGB", (800, 600), (200, 200, 200))
    image.paste(scene((160, 120)), (20, 20))
    assert photo_retake_reason(encode(image)) is None


def test_the_size_of_the_photo_does_not_change_the_answer() -> None:
    big, small = scene((3200, 2400)), scene((400, 300))
    assert photo_retake_reason(encode(big)) is None
    assert photo_retake_reason(encode(small)) is None
    assert photo_retake_reason(encode(big.filter(ImageFilter.GaussianBlur(16)))) == BLURRY


@pytest.mark.parametrize("kind", ["PNG", "WEBP"])
def test_other_photo_types_are_checked_the_same(kind: str) -> None:
    assert photo_retake_reason(encode(scene(), kind)) is None
    assert photo_retake_reason(encode(Image.eval(scene(), lambda v: v // 5), kind)) == TOO_DARK


def test_a_photo_too_small_to_judge_is_not_a_retake() -> None:
    assert measure(encode(Image.new("RGB", (2, 2), "black"), "PNG"), CHECKS) is None
    assert photo_retake_reason(encode(Image.new("RGB", (2, 2), "black"), "PNG")) is None


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("min_bright_end", 256, TOO_DARK),
        ("max_dark_end", -1, WASHED_OUT),
        ("min_sharpness", float("inf"), BLURRY),
    ],
)
def test_each_threshold_comes_from_config(field: str, value: float, reason: str) -> None:
    strict = PhotoChecks.model_validate(CHECKS.model_dump() | {field: value})
    assert retake_reason(measures(sharp()), CHECKS) is None
    assert retake_reason(measures(sharp()), strict) == reason


def test_each_threshold_has_a_reason() -> None:
    for name, field in PhotoChecks.model_fields.items():
        assert field.description, f"{name} needs a one-line reason"
