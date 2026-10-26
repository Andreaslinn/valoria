from __future__ import annotations
from dataclasses import dataclass
import hashlib
import io
import time
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from .security import MIMES, MAX_BYTES, MAX_PIXELS, MAX_DIMENSION, Rejected


@dataclass(frozen=True)
class Thumbnail:
    data: bytes
    digest: str
    width: int
    height: int
    format: str
    metrics: dict


def normalize(data: bytes, mime: str, *, width=320, quality=60, format='WEBP') -> Thumbnail:
    if mime not in MIMES or len(data) > MAX_BYTES:
        raise Rejected('input_limit_or_mime')
    start = time.perf_counter()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                w, h = image.size
                if image.format != MIMES[mime]:
                    raise Rejected('mime_signature_mismatch')
                if w*h > MAX_PIXELS or max(w, h) > MAX_DIMENSION:
                    raise Rejected('decoded_limit')
                if getattr(image, 'n_frames', 1) != 1:
                    raise Rejected('animated_unsupported')
                image.load()
                oriented = ImageOps.exif_transpose(image)
                # Flatten alpha consistently; copy pixels into a fresh image to
                # remove EXIF, ICC, XMP, comments and other input metadata.
                rgba = oriented.convert('RGBA')
                clean = Image.new('RGB', rgba.size, 'white')
                clean.paste(rgba, mask=rgba.getchannel('A'))
        decoded = time.perf_counter()
        target = (min(width, clean.width), max(1, round(clean.height*min(width, clean.width)/clean.width)))
        if target != clean.size:
            clean = clean.resize(target, Image.Resampling.LANCZOS)
        resized = time.perf_counter()
        output = io.BytesIO()
        if format == 'WEBP':
            clean.save(output, format='WEBP', quality=quality, method=4)
        elif format == 'JPEG':
            clean.save(output, format='JPEG', quality=quality, optimize=True, progressive=True)
        elif format == 'AVIF':
            clean.save(output, format='AVIF', quality=quality, speed=6, max_threads=1)
        else:
            raise Rejected('output_format_unsupported')
        end = time.perf_counter()
        blob = output.getvalue()
        return Thumbnail(blob, hashlib.sha256(blob).hexdigest(), *clean.size, format.lower(),
                         {'decode_ms': (decoded-start)*1000,
                          'resize_ms': (resized-decoded)*1000,
                          'encode_ms': (end-resized)*1000,
                          'processing_ms': (end-start)*1000,
                          'original_bytes': len(data), 'thumbnail_bytes': len(blob),
                          'compression_ratio': len(data)/max(1,len(blob))})
    except Rejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise Rejected('corrupt_or_unsupported') from exc
