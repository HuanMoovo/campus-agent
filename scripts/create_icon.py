"""Generate the desktop, PWA and loading-page icons from mens-mark.svg.

Pillow is already a build dependency in requirements-build.txt. The SVG uses only
circle, polyline and line primitives; this intentionally small renderer reads their
geometry directly so every exported size stays in sync with the vector mark.
"""
import base64
import io
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'frontend' / 'src' / 'assets' / 'mens-mark.svg'
SIZES = (16, 24, 32, 48, 64, 128, 180, 192, 256, 512, 1024)
CORNER_RADIUS_RATIO = 0.22
MARK_SCALE = 0.78
ICNS_TYPES = {16: b'icp4', 32: b'icp5', 64: b'icp6', 128: b'ic07', 256: b'ic08', 512: b'ic09', 1024: b'ic10'}


def load_mark(source: Path):
    """Read the deliberately restricted, flat SVG mark and reject unsupported art."""
    root = ET.parse(source).getroot()
    view_box = tuple(float(value) for value in root.attrib['viewBox'].split())
    if view_box[:2] != (0.0, 0.0) or view_box[2] != view_box[3]:
        raise ValueError('The brand mark must have a square, zero-origin viewBox.')
    if root.get('fill') != 'none' or root.get('stroke-linecap') != 'round':
        raise ValueError('The brand mark must use unfilled shapes with round caps.')
    primitives = []
    for element in root:
        kind = element.tag.rsplit('}', 1)[-1]
        if kind not in ('circle', 'polyline', 'line'):
            raise ValueError(f'Unsupported brand SVG element: {kind}')
        if 'transform' in element.attrib or 'style' in element.attrib:
            raise ValueError('Use direct SVG coordinates and presentation attributes.')
        width = float(element.get('stroke-width', root.attrib['stroke-width']))
        if kind == 'circle':
            geometry = tuple(float(element.attrib[key]) for key in ('cx', 'cy', 'r'))
        elif kind == 'line':
            geometry = tuple(float(element.attrib[key]) for key in ('x1', 'y1', 'x2', 'y2'))
        else:
            geometry = tuple(float(value) for value in re.split(r'[\s,]+', element.attrib['points'].strip()))
            if len(geometry) < 4 or len(geometry) % 2:
                raise ValueError('A polyline must contain at least two coordinate pairs.')
        primitives.append((kind, geometry, width))
    return view_box[2], primitives


def render_icons(source: Path, sizes) -> dict:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit('Pillow is required to render mens-mark.svg. Run: pip install -r requirements-build.txt') from None

    side, primitives = load_mark(source)
    images = {}
    for size in sizes:
        # Supersampling preserves the rounded plate, circular ring and caps at 16 px.
        render_size = size * 4
        image = Image.new('RGBA', (render_size, render_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (0, 0, render_size - 1, render_size - 1),
            radius=render_size * CORNER_RADIUS_RATIO, fill=(0, 0, 0, 255))
        scale = render_size * MARK_SCALE / side
        origin = render_size * (1 - MARK_SCALE) / 2

        def point(x, y):
            return origin + x * scale, origin + y * scale

        for kind, geometry, width in primitives:
            stroke = width * scale
            if kind == 'circle':
                cx, cy = point(*geometry[:2])
                radius = geometry[2] * scale
                outer, inner = radius + stroke / 2, radius - stroke / 2
                draw.ellipse((cx - outer, cy - outer, cx + outer, cy + outer), fill='white')
                draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill='black')
            else:
                points = [point(*geometry[index:index + 2]) for index in range(0, len(geometry), 2)]
                draw.line(points, fill='white', width=max(1, round(stroke)), joint='curve')
                # Explicit round caps also round the interior corners of the brackets.
                for x, y in points:
                    radius = stroke / 2
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill='white')
        image = image.resize((size, size), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        images[size] = buffer.getvalue()
    return images


def build_ico(images: dict) -> bytes:
    icon_sizes = tuple(size for size in SIZES if size <= 256 and size in images)
    offset = 6 + 16 * len(icon_sizes)
    entries = bytearray(struct.pack('<HHH', 0, 1, len(icon_sizes)))
    for size in icon_sizes:
        image = images[size]
        entries.extend(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(image), offset))
        offset += len(image)
    return bytes(entries) + b''.join(images[size] for size in icon_sizes)


def build_icns(images: dict) -> bytes:
    """macOS icon container with raw PNG payloads at every supported size."""
    body = bytearray()
    for size, type_code in sorted(ICNS_TYPES.items()):
        if size in images:
            payload = images[size]
            body += type_code + struct.pack('>I', len(payload) + 8) + payload
    return b'icns' + struct.pack('>I', len(body) + 8) + bytes(body)


def main():
    if not SOURCE.exists():
        raise SystemExit(f'Missing brand SVG: {SOURCE}')
    images = render_icons(SOURCE, SIZES)
    desktop = ROOT / 'desktop' / 'assets'
    public = ROOT / 'frontend' / 'public'
    icon = build_ico(images)
    outputs = {
        desktop / 'mens.ico': icon,
        desktop / 'mens.png': images[256],
        # Retain names used by existing upgrade and unpacked-build paths.
        desktop / 'campus.ico': icon,
        desktop / 'campus.png': images[256],
        desktop / 'mens.icns': build_icns(images),
        public / 'favicon.png': images[64],
        public / 'icon-192.png': images[192],
        public / 'icon-512.png': images[512],
        public / 'apple-touch-icon.png': images[180],
    }
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    template = (ROOT / 'scripts' / 'loading.html.tmpl').read_text(encoding='utf-8')
    logo_url = 'data:image/png;base64,' + base64.b64encode(images[256]).decode('ascii')
    (desktop / 'loading.html').write_text(
        template.replace('__MENS_LOGO_DATA_URL__', logo_url), encoding='utf-8')
    print('Mens monochrome icons generated (ico/icns/png) from mens-mark.svg.')


if __name__ == '__main__':
    main()
