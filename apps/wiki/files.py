"""What an uploaded file really is, decided from its bytes.

The browser's Content-Type and the file's name are the uploader's words.
Serving a file inline on either would let "picture.png" that is really HTML,
or an SVG with a script in it, run in Jackil's origin. Only these raster
formats, recognised by Pillow, are ever shown inline.
"""

from PIL import Image, UnidentifiedImageError

#: Pillow format name -> the Content-Type served for it.
INLINE_IMAGE_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}

#: Every attachment response carries these, inline or not.
SAFE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; img-src 'self'; sandbox",
}


def sniff_image(fileobj) -> str | None:
    """The Content-Type to serve inline, or None when it is not a safe raster image."""
    try:
        position = fileobj.tell()
    except (AttributeError, OSError):
        position = None
    try:
        with Image.open(fileobj) as image:
            kind = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        return None
    finally:
        if position is not None:
            fileobj.seek(position)
    return INLINE_IMAGE_TYPES.get(kind)
