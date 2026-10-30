"""The QR as inline SVG, built server-side so an install with no CDN access
still shows a scannable code (Vigil's air-gapped deployments learned this the
hard way). Inline SVG rather than a data: URI so no img-src or base64 is
involved; the SVG factory rather than PNG so Pillow is not pulled in.

The SVG comes from ``qrcode`` fed an ``otpauth://`` URI the server built from
a generated secret — never from anything a user typed."""

import io

import qrcode
import qrcode.image.svg


def totp_qr_svg(uri: str) -> str:
    code = qrcode.QRCode(
        version=None,
        box_size=10,
        border=2,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    code.add_data(uri)
    # ``image_factory``, not ``factory``: an unknown keyword is swallowed by
    # **kwargs and qrcode then falls back to its PIL factory, which this
    # project does not install (no Pillow) — the SVG factory also means no
    # Pillow is needed.
    image = code.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    image.save(buf)
    return buf.getvalue().decode("utf-8")
