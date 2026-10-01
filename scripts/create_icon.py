"""Generate all Mens branding assets from the supplied bitmap on Windows."""
import base64
from pathlib import Path
import struct
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def main():
    source = ROOT / 'assets' / 'branding' / 'mens-source.png'
    desktop = ROOT / 'desktop' / 'assets'
    frontend = ROOT / 'frontend'
    with tempfile.TemporaryDirectory(prefix='mens-icons-') as temporary:
        subprocess.run([
            'powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(ROOT / 'scripts' / 'resize_logo.ps1'),
            '-LogoSource', str(source), '-OutputDirectory', temporary,
        ], check=True)
        images = {size: (Path(temporary) / f'{size}.png').read_bytes() for size in SIZES}

    icon_sizes = tuple(size for size in SIZES if size <= 256)
    offset = 6 + 16 * len(icon_sizes)
    entries = bytearray(struct.pack('<HHH', 0, 1, len(icon_sizes)))
    for size in icon_sizes:
        image = images[size]
        entries.extend(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0,
                                   1, 32, len(image), offset))
        offset += len(image)
    icon = bytes(entries) + b''.join(images[size] for size in icon_sizes)
    outputs = {
        desktop / 'mens.ico': icon,
        desktop / 'mens.png': images[256],
        # Retain names used by existing upgrade and unpacked-build paths.
        desktop / 'campus.ico': icon,
        desktop / 'campus.png': images[256],
        frontend / 'src' / 'assets' / 'mens.png': images[512],
        frontend / 'public' / 'favicon.png': images[64],
    }
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    template = (ROOT / 'scripts' / 'loading.html.tmpl').read_text(encoding='utf-8')
    logo_url = 'data:image/png;base64,' + base64.b64encode(images[256]).decode('ascii')
    (desktop / 'loading.html').write_text(
        template.replace('__MENS_LOGO_DATA_URL__', logo_url), encoding='utf-8')
    print('Mens frontend, desktop, installer, and loading logos generated from mens-source.png.')


if __name__ == '__main__':
    main()
