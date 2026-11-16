"""Fixed image parser worker. Uploaded bytes are data, never executable code."""
import io
import json
import resource
import sys
import warnings
from PIL import Image


def main():
    pixels, side, memory, cpu = map(int, sys.argv[1:])
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    except (ValueError, OSError):
        # Darwin can reject address-space limits. Pixel/dimension bounds, parser
        # limits, CPU budget and the parent's wall timeout still apply there.
        if sys.platform != 'darwin':
            raise
    Image.MAX_IMAGE_PIXELS = pixels
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    source = sys.stdin.buffer
    # stdin is a regular, seekable descriptor, not a pipe or path from the upload.
    with Image.open(source, formats=['PNG', 'JPEG']) as image:
        kind = image.format.lower()
        width, height = image.size
        if width < 1 or height < 1 or width * height > pixels or max(width, height) > side or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Image resource limit exceeded.')
        image.verify()
    source.seek(0)
    with Image.open(source, formats=['PNG', 'JPEG']) as image:
        image.load()
        image.thumbnail((512, 512))
        # Fresh pixels strip all uploaded metadata, profiles and ancillary chunks.
        converted = image.convert('RGB')
        clean = Image.new('RGB', converted.size)
        clean.paste(converted)
        output = io.BytesIO()
        clean.save(output, format='PNG')
    result = output.getvalue()
    if len(result) > 2 * 1024 * 1024:
        raise ValueError('Thumbnail exceeds limit.')
    sys.stdout.buffer.write(json.dumps({'kind': kind}).encode() + b'\n' + result)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Do not emit parser messages, paths or uploaded data.
        sys.exit(1)
