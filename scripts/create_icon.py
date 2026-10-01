"""Generate every Mens branding asset for Windows, macOS, Linux and the web client.

Pillow (`pip install -r requirements-build.txt`) is the preferred resizer and works on all
three desktop platforms. On Windows the original PowerShell/System.Drawing resizer is kept
as a fallback so the Windows-only release flow never depends on Pillow. The .icns container
for macOS is assembled in pure Python from the PNG sizes.
"""
import base64
import io
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 24, 32, 48, 64, 128, 180, 192, 256, 512, 1024)
POWERSHELL_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
# Rounded-square plate: radius is 20% of the side, matching the original artwork treatment.
CORNER_RADIUS_RATIO = 0.2
ICNS_TYPES = {16: b'icp4', 32: b'icp5', 64: b'icp6', 128: b'ic07', 256: b'ic08', 512: b'ic09', 1024: b'ic10'}


def resize_with_pillow(source: Path, sizes) -> dict:
    from PIL import Image, ImageDraw

    with Image.open(source) as original:
        image = original.convert('RGBA')
        side = min(image.width, image.height)
        left, top = (image.width - side) // 2, (image.height - side) // 2
        square = image.crop((left, top, left + side, top + side))
        images = {}
        for size in sizes:
            resized = square.resize((size, size), Image.LANCZOS)
            radius = max(1, int(size * CORNER_RADIUS_RATIO))
            mask = Image.new('L', (size, size), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
            plated = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            plated.paste(resized, (0, 0), mask)
            buffer = io.BytesIO()
            plated.save(buffer, format='PNG')
            images[size] = buffer.getvalue()
        return images


def resize_with_powershell(source: Path, directory: Path) -> dict:
    powershell = shutil.which('powershell.exe') or shutil.which('powershell')
    if not powershell:
        raise RuntimeError('PowerShell is unavailable')
    subprocess.run([
        powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', str(ROOT / 'scripts' / 'resize_logo.ps1'),
        '-LogoSource', str(source), '-OutputDirectory', str(directory),
    ], check=True)
    return {size: (directory / f'{size}.png').read_bytes() for size in POWERSHELL_SIZES}


def resize(source: Path, temporary: Path) -> dict:
    try:
        return resize_with_pillow(source, SIZES)
    except ImportError:
        if os.name != 'nt':
            raise SystemExit('需要 Pillow 生成图标：pip install -r requirements-build.txt') from None
        print('Pillow 不可用，改用 PowerShell 缩放（个别尺寸以邻近 PNG 代替）。', file=sys.stderr)
    images = resize_with_powershell(source, temporary)
    # Fill the sizes the legacy script does not know with the nearest available PNG.
    for size in SIZES:
        if size not in images:
            nearest = min(POWERSHELL_SIZES, key=lambda candidate: abs(candidate - size))
            images[size] = images[nearest]
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
    """macOS icon container: big-endian table of contents plus raw PNG payloads."""
    body = bytearray()
    for size, type_code in sorted(ICNS_TYPES.items()):
        if size not in images:
            continue
        payload = images[size]
        body += type_code + struct.pack('>I', len(payload) + 8) + payload
    return b'icns' + struct.pack('>I', len(body) + 8) + bytes(body)


def main():
    source = ROOT / 'assets' / 'branding' / 'mens-source.png'
    if not source.exists():
        raise SystemExit(f'缺少品牌源图：{source}')
    desktop = ROOT / 'desktop' / 'assets'
    frontend = ROOT / 'frontend'
    with tempfile.TemporaryDirectory(prefix='mens-icons-') as temporary:
        images = resize(source, Path(temporary))

    icon = build_ico(images)
    outputs = {
        # Windows / Electron
        desktop / 'mens.ico': icon,
        desktop / 'mens.png': images[256],
        # Retain names used by existing upgrade and unpacked-build paths.
        desktop / 'campus.ico': icon,
        desktop / 'campus.png': images[256],
        # macOS
        desktop / 'mens.icns': build_icns(images),
        # Linux plus the installable web client (PWA icons).
        frontend / 'src' / 'assets' / 'mens.png': images[512],
        frontend / 'public' / 'favicon.png': images[64],
        frontend / 'public' / 'icon-192.png': images[192],
        frontend / 'public' / 'icon-512.png': images[512],
        frontend / 'public' / 'apple-touch-icon.png': images[180],
    }
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    template = (ROOT / 'scripts' / 'loading.html.tmpl').read_text(encoding='utf-8')
    logo_url = 'data:image/png;base64,' + base64.b64encode(images[256]).decode('ascii')
    (desktop / 'loading.html').write_text(
        template.replace('__MENS_LOGO_DATA_URL__', logo_url), encoding='utf-8')
    print('Mens icons generated (ico/icns/png) from mens-source.png.')


if __name__ == '__main__':
    main()
