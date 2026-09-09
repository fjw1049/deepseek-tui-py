"""Content-addressed original images and bounded, reproducible wire variants."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import tempfile
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from deepseek_tui.config.paths import user_media_dir
from deepseek_tui.protocol.messages import ImageBlock, Message, ToolResultBlock

MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})


def _decode(data: bytes) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image exceeds the 40 megapixel decoding limit")
                if getattr(image, "n_frames", 1) > 1:
                    raise ValueError("Animated images are not supported; attach a still frame")
                image.load()
                return ImageOps.exif_transpose(image).copy()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("Image is damaged, unsupported, or too large to decode") from exc


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def import_image(data: bytes) -> ImageBlock:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image must be nonempty and no larger than 32 MiB")
    image = _decode(data)
    # Preserve the original file; use a canonical PNG/JPEG wire variant later.
    with Image.open(io.BytesIO(data)) as original:
        mime = Image.MIME.get(original.format or "", "image/png")
    if mime not in {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "image/bmp",
        "image/tiff",
    }:
        raise ValueError("Unsupported image format")
    digest = hashlib.sha256(data).hexdigest()
    path = user_media_dir() / digest
    if not path.exists():
        _write_atomic(path, data)
    return ImageBlock(
        asset_id=digest, mime_type=mime, width=image.width, height=image.height, byte_size=len(data)
    )


def import_image_path(path: Path) -> ImageBlock:
    with path.open("rb") as stream:
        return import_image(stream.read(MAX_IMAGE_BYTES + 1))


def image_data_url(block: ImageBlock, *, max_side: int = 2048) -> str:
    """PNG preserves screenshot text; large photos fall back to bounded JPEG."""
    data = (user_media_dir() / block.asset_id).read_bytes()
    if hashlib.sha256(data).hexdigest() != block.asset_id:
        raise ValueError(f"Stored image failed integrity check: {block.asset_id}")
    image = _decode(data)
    if block.crop is not None:
        x, y, width, height = block.crop
        if (
            min(x, y) < 0
            or min(width, height) <= 0
            or x + width > image.width
            or y + height > image.height
        ):
            raise ValueError("Image crop is outside the oriented original image")
        image = image.crop((x, y, x + width, y + height))
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    if image.mode not in {"1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16"}:
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    mime = "image/png"
    if buffer.tell() > 2 * 1024 * 1024:
        if image.mode in {"RGBA", "LA"}:
            background = Image.new("RGB", image.size, "white")
            rgba = image.convert("RGBA")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def message_images(message: Message) -> list[ImageBlock]:
    return [
        image
        for block in message.content
        for image in (
            [block]
            if isinstance(block, ImageBlock)
            else block.images
            if isinstance(block, ToolResultBlock)
            else []
        )
    ]


def image_token_estimate(block: ImageBlock) -> int:
    # Conservative tile estimate; actual provider usage remains authoritative.
    width, height = block.crop[2:] if block.crop else (block.width, block.height)
    scale = min(1.0, 2048 / max(width, height))
    return 85 + 170 * (((int(width * scale) + 511) // 512) * ((int(height * scale) + 511) // 512))
