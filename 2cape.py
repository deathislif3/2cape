#!/usr/bin/env python3
"""Convert a Windows cursor theme folder (.ani / .cur) to a Mousecape .cape.

No third-party packages are required. The converter reads standard Windows ANI,
CUR, DIB, and embedded PNG cursor data, preserves animation frames and cursor
hotspots, and writes Mousecape's binary-plist Cape format (version 2).

Usage examples:
  python3 convert_windows_cursors_to_cape.py
  python3 convert_windows_cursors_to_cape.py --input ./MyTheme --name "My Theme"
  python3 convert_windows_cursors_to_cape.py --input ./MyTheme --output ~/Desktop/MyTheme.cape
"""

from __future__ import annotations

import argparse
import plistlib
import re
import struct
import sys
import zlib
from pathlib import Path


MAX_ANIMATION_FRAMES = 24
DEFAULT_LOGICAL_WIDTH = 32.0

# Standard Windows cursor roles, mapped to Mousecape/macOS cursor identifiers.
# Pin (Location Select) and Person have no exact system-level macOS equivalent;
# Cell and Pointing are the closest available configurable slots.
MAC_ROLE_MAP: dict[str, list[str]] = {
    "Arrow": [
        "com.apple.coregraphics.Arrow",
        "com.apple.coregraphics.ArrowCtx",
        "com.apple.coregraphics.ArrowS",
    ],
    "Help": ["com.apple.cursor.40"],
    "AppStarting": ["com.apple.cursor.4"],
    "Wait": ["com.apple.coregraphics.Wait"],
    "Crosshair": ["com.apple.cursor.7", "com.apple.cursor.8"],
    "IBeam": [
        "com.apple.coregraphics.IBeam",
        "com.apple.coregraphics.IBeamXOR",
        "com.apple.coregraphics.IBeamS",
    ],
    "NWPen": ["com.apple.cursor.26"],
    "No": ["com.apple.cursor.3"],
    "SizeNS": ["com.apple.cursor.23", "com.apple.cursor.32"],
    "SizeWE": ["com.apple.cursor.19", "com.apple.cursor.28"],
    "SizeNWSE": ["com.apple.cursor.34"],
    "SizeNESW": ["com.apple.cursor.30"],
    "SizeAll": ["com.apple.coregraphics.Move"],
    "UpArrow": ["com.apple.coregraphics.Alias"],
    "Hand": ["com.apple.cursor.2"],
    "Pin": ["com.apple.cursor.41"],
    "Person": ["com.apple.cursor.13"],
}

# Fallback names used when the Windows scheme has no .inf manifest.
FILENAME_ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "Arrow": ("arrow", "pointer", "normal", "default"),
    "Help": ("help",),
    "AppStarting": ("appstarting", "working", "starting"),
    "Wait": ("wait", "busy"),
    "Crosshair": ("crosshair", "cross", "precision"),
    "IBeam": ("ibeam", "text"),
    "NWPen": ("nwpen", "handwriting", "pen"),
    "No": ("no", "unavailable", "forbidden"),
    "SizeNS": ("sizens", "vert", "vertical"),
    "SizeWE": ("sizewe", "horz", "horizontal"),
    "SizeNWSE": ("sizenwse", "dgn1", "nwse"),
    "SizeNESW": ("sizenesw", "dgn2", "nesw"),
    "SizeAll": ("sizeall", "move"),
    "UpArrow": ("uparrow", "alternate", "alt"),
    "Hand": ("hand", "link"),
    "Pin": ("pin", "loc", "location"),
    "Person": ("person",),
}

# Variables used inside a Windows .inf's cursor-scheme registry entry. The
# seventh item in that registry list is NWPen (handwriting), not Hand (link).
INF_VARIABLE_ROLES: dict[str, str] = {
    "arrow": "Arrow",
    "pointer": "Arrow",
    "normal": "Arrow",
    "help": "Help",
    "work": "AppStarting",
    "working": "AppStarting",
    "appstarting": "AppStarting",
    "busy": "Wait",
    "wait": "Wait",
    "cross": "Crosshair",
    "crosshair": "Crosshair",
    "text": "IBeam",
    "ibeam": "IBeam",
    "hand": "NWPen",
    "handwriting": "NWPen",
    "nwpen": "NWPen",
    "unavailable": "No",
    "no": "No",
    "vert": "SizeNS",
    "sizens": "SizeNS",
    "horz": "SizeWE",
    "sizewe": "SizeWE",
    "dgn1": "SizeNWSE",
    "sizenwse": "SizeNWSE",
    "dgn2": "SizeNESW",
    "sizenesw": "SizeNESW",
    "move": "SizeAll",
    "sizeall": "SizeAll",
    "alternate": "UpArrow",
    "uparrow": "UpArrow",
    "link": "Hand",
    "pin": "Pin",
    "loc": "Pin",
    "location": "Pin",
    "person": "Person",
}


class CursorFormatError(ValueError):
    """The source file is a cursor format that cannot be converted safely."""


def read_u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise CursorFormatError("unexpected end of file")
    return struct.unpack_from("<I", data, offset)[0]


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def iter_riff_chunks(data: bytes, start: int, end: int):
    offset = start
    while offset + 8 <= end:
        tag = data[offset : offset + 4]
        length = read_u32(data, offset + 4)
        body_start = offset + 8
        body_end = body_start + length
        if body_end > end:
            raise CursorFormatError("invalid RIFF chunk length")
        yield tag, data[body_start:body_end]
        offset = body_end + (length & 1)


def parse_ani(data: bytes) -> tuple[list[bytes], list[int], list[int]]:
    """Return ANI CUR frames, animation sequence, and per-step rates in jiffies."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"ACON":
        raise CursorFormatError("not a Windows animated cursor (.ani) file")

    # Some cursor pack generators incorrectly record the complete file size
    # instead of RIFF's usual size-minus-eight. Chunk boundaries remain valid,
    # so bound traversal to the real file in either case.
    end = min(read_u32(data, 4) + 8, len(data))
    frame_count: int | None = None
    step_count: int | None = None
    rates: list[int] = []
    sequence: list[int] = []
    frames: list[bytes] = []

    for tag, body in iter_riff_chunks(data, 12, end):
        if tag == b"anih":
            if len(body) < 36:
                raise CursorFormatError("truncated ANI header")
            _, frame_count, step_count, *_ = struct.unpack_from("<9I", body)
        elif tag == b"rate":
            count = len(body) // 4
            rates = list(struct.unpack("<" + "I" * count, body[: count * 4]))
        elif tag == b"seq ":
            count = len(body) // 4
            sequence = list(struct.unpack("<" + "I" * count, body[: count * 4]))
        elif tag == b"LIST" and body[:4] == b"fram":
            for frame_tag, frame_body in iter_riff_chunks(body, 4, len(body)):
                if frame_tag == b"icon":
                    frames.append(frame_body)

    if not frames:
        raise CursorFormatError("ANI contains no cursor frames")
    if frame_count is not None and frame_count != len(frames):
        raise CursorFormatError("ANI frame count does not match its frame data")
    if step_count is None:
        step_count = len(frames)
    if not 1 <= step_count <= MAX_ANIMATION_FRAMES:
        raise CursorFormatError(
            f"animation has {step_count} frames; Mousecape supports 1–{MAX_ANIMATION_FRAMES}"
        )

    if not sequence:
        sequence = list(range(step_count))
    if len(sequence) < step_count:
        raise CursorFormatError("ANI sequence table is shorter than the animation")
    sequence = sequence[:step_count]
    if any(index >= len(frames) for index in sequence):
        raise CursorFormatError("ANI sequence refers to a missing frame")

    if not rates:
        rates = [6] * step_count  # Windows default: 6 jiffies (1/10 second).
    if len(rates) < step_count:
        rates.extend([rates[-1]] * (step_count - len(rates)))
    return frames, sequence, rates[:step_count]


def parse_png(data: bytes) -> tuple[int, int, bytes]:
    """Decode ordinary non-interlaced RGB/RGBA PNG cursor image data."""
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise CursorFormatError("not a PNG image")

    offset = len(signature)
    width = height = bit_depth = color_type = None
    compressed = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        body_start = offset + 8
        body_end = body_start + length
        if body_end + 4 > len(data):
            raise CursorFormatError("truncated PNG chunk")
        body = data[body_start:body_end]
        if kind == b"IHDR":
            if len(body) != 13:
                raise CursorFormatError("invalid PNG header")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            if compression != 0 or filtering != 0 or interlace != 0:
                raise CursorFormatError("interlaced or non-standard PNG cursor frame")
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            break
        offset = body_end + 4

    if not width or not height or bit_depth != 8 or color_type not in (2, 6):
        raise CursorFormatError("only 8-bit RGB/RGBA PNG cursor frames are supported")
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    raw = zlib.decompress(bytes(compressed))
    if len(raw) != height * (stride + 1):
        raise CursorFormatError("invalid decompressed PNG length")

    rows: list[bytearray] = []
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        source = raw[position + 1 : position + 1 + stride]
        position += stride + 1
        current = bytearray(stride)
        previous = rows[-1] if rows else bytearray(stride)
        for index, value in enumerate(source):
            left = current[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                decoded = value
            elif filter_type == 1:
                decoded = value + left
            elif filter_type == 2:
                decoded = value + up
            elif filter_type == 3:
                decoded = value + ((left + up) // 2)
            elif filter_type == 4:
                p = left + up - upper_left
                pa = abs(p - left)
                pb = abs(p - up)
                pc = abs(p - upper_left)
                predictor = left if pa <= pb and pa <= pc else (up if pb <= pc else upper_left)
                decoded = value + predictor
            else:
                raise CursorFormatError(f"unsupported PNG filter type {filter_type}")
            current[index] = decoded & 0xFF
        rows.append(current)

    rgba = bytearray(width * height * 4)
    destination = 0
    for row in rows:
        for pixel in range(width):
            start = pixel * channels
            rgba[destination : destination + 4] = row[start : start + 3] + bytes((row[start + 3] if channels == 4 else 255,))
            destination += 4
    return width, height, bytes(rgba)


def mask_bit(mask: bytes, width: int, height: int, y: int, x: int, top_down: bool) -> bool:
    row_stride = ((width + 31) // 32) * 4
    source_y = y if top_down else height - 1 - y
    offset = source_y * row_stride + x // 8
    return offset < len(mask) and bool(mask[offset] & (0x80 >> (x % 8)))


def parse_dib(data: bytes, directory_width: int, directory_height: int) -> tuple[int, int, bytes]:
    """Decode an uncompressed standard icon DIB to top-down RGBA bytes."""
    if len(data) < 40:
        raise CursorFormatError("truncated DIB image")
    (
        header_size,
        width,
        full_height,
        planes,
        bpp,
        compression,
        _,
        _,
        _,
        colors_used,
        _,
    ) = struct.unpack_from("<IiiHHIIiiII", data)
    if header_size < 40 or width < 1 or full_height == 0 or planes != 1:
        raise CursorFormatError("invalid DIB cursor frame")
    if bpp not in (1, 4, 8, 24, 32) or compression != 0:
        raise CursorFormatError("only uncompressed 1/4/8/24/32-bit DIB cursor frames are supported")

    height = abs(full_height) // 2
    if height < 1:
        raise CursorFormatError("invalid DIB cursor height")
    if directory_width and directory_width != width:
        raise CursorFormatError("CUR directory width and DIB width disagree")
    if directory_height and directory_height != height:
        raise CursorFormatError("CUR directory height and DIB height disagree")

    palette_count = colors_used or ((1 << bpp) if bpp <= 8 else 0)
    palette_start = header_size
    pixels_start = palette_start + palette_count * 4
    if pixels_start > len(data):
        raise CursorFormatError("truncated DIB palette")
    palette = []
    for index in range(palette_count):
        b, g, r, _ = data[palette_start + index * 4 : palette_start + index * 4 + 4]
        palette.append((r, g, b))

    row_stride = ((width * bpp + 31) // 32) * 4
    xor_end = pixels_start + row_stride * height
    if xor_end > len(data):
        raise CursorFormatError("truncated DIB pixel data")
    xor = data[pixels_start:xor_end]
    and_mask = data[xor_end:]
    top_down = full_height < 0
    alpha_is_present = bpp == 32 and any(xor[offset] for offset in range(3, len(xor), 4))

    rgba = bytearray(width * height * 4)
    for y in range(height):
        source_y = y if top_down else height - 1 - y
        row_start = source_y * row_stride
        for x in range(width):
            if bpp == 32:
                b, g, r, alpha = xor[row_start + x * 4 : row_start + x * 4 + 4]
            elif bpp == 24:
                b, g, r = xor[row_start + x * 3 : row_start + x * 3 + 3]
                alpha = 255
            else:
                if bpp == 8:
                    palette_index = xor[row_start + x]
                elif bpp == 4:
                    packed = xor[row_start + x // 2]
                    palette_index = packed >> 4 if x % 2 == 0 else packed & 0x0F
                else:
                    packed = xor[row_start + x // 8]
                    palette_index = 1 if packed & (0x80 >> (x % 8)) else 0
                if palette_index >= len(palette):
                    raise CursorFormatError("DIB pixel refers to a missing palette color")
                r, g, b = palette[palette_index]
                alpha = 255

            if not alpha_is_present and mask_bit(and_mask, width, height, y, x, top_down):
                alpha = 0
            elif not alpha_is_present:
                alpha = 255
            destination = (y * width + x) * 4
            rgba[destination : destination + 4] = bytes((r, g, b, alpha))
    return width, height, bytes(rgba)


def decode_icon_image(data: bytes, width: int, height: int) -> tuple[int, int, bytes]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        decoded_width, decoded_height, rgba = parse_png(data)
        if width and decoded_width != width or height and decoded_height != height:
            raise CursorFormatError("CUR directory size and embedded PNG size disagree")
        return decoded_width, decoded_height, rgba
    return parse_dib(data, width, height)


def decode_cur(data: bytes) -> tuple[int, int, float, float, bytes]:
    if len(data) < 22:
        raise CursorFormatError("truncated CUR frame")
    reserved, kind, count = struct.unpack_from("<HHH", data)
    if reserved != 0 or kind != 2 or count < 1:
        raise CursorFormatError("invalid CUR frame header")
    if len(data) < 6 + count * 16:
        raise CursorFormatError("truncated CUR directory")

    candidates = []
    for index in range(count):
        width_byte, height_byte, _, _, hotspot_x, hotspot_y, byte_count, image_offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + index * 16
        )
        width = width_byte or 256
        height = height_byte or 256
        if image_offset + byte_count <= len(data):
            candidates.append((width * height, width, height, hotspot_x, hotspot_y, data[image_offset : image_offset + byte_count]))
    if not candidates:
        raise CursorFormatError("CUR frame has no valid image")

    _, width, height, hotspot_x, hotspot_y, image = max(candidates, key=lambda item: item[0])
    width, height, rgba = decode_icon_image(image, width, height)
    return width, height, float(hotspot_x), float(hotspot_y), rgba


def resize_nearest(rgba: bytes, source_width: int, source_height: int, width: int, height: int) -> bytes:
    """Normalise mixed-size ANI frames without introducing a dependency."""
    result = bytearray(width * height * 4)
    for y in range(height):
        source_y = min(source_height - 1, int(y * source_height / height))
        for x in range(width):
            source_x = min(source_width - 1, int(x * source_width / width))
            source = (source_y * source_width + source_x) * 4
            destination = (y * width + x) * 4
            result[destination : destination + 4] = rgba[source : source + 4]
    return bytes(result)


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    if len(rgba) != width * height * 4:
        raise CursorFormatError("invalid RGBA image buffer")
    filtered = bytearray()
    stride = width * 4
    for y in range(height):
        filtered.append(0)  # PNG's None filter
        filtered.extend(rgba[y * stride : (y + 1) * stride])
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            png_chunk(b"IDAT", zlib.compress(bytes(filtered), 9)),
            png_chunk(b"IEND", b""),
        )
    )


def convert_cursor(path: Path) -> dict:
    source = path.read_bytes()
    if path.suffix.lower() == ".ani":
        cur_frames, sequence, rates = parse_ani(source)
    else:
        cur_frames, sequence, rates = [source], [0], [6]

    frames = [decode_cur(frame) for frame in cur_frames]
    width, height, hotspot_x, hotspot_y, _ = frames[sequence[0]]
    sprite_frames = []
    for index in sequence:
        frame_width, frame_height, frame_hotspot_x, frame_hotspot_y, rgba = frames[index]
        if (frame_hotspot_x, frame_hotspot_y) != (hotspot_x, hotspot_y):
            raise CursorFormatError("animation frames use inconsistent hotspots")
        if (frame_width, frame_height) != (width, height):
            rgba = resize_nearest(rgba, frame_width, frame_height, width, height)
        sprite_frames.append(rgba)

    logical_width = min(DEFAULT_LOGICAL_WIDTH, float(width))
    scale = width / logical_width
    logical_height = height / scale
    return {
        "FrameCount": len(sprite_frames),
        # Mousecape has one duration per animation. Averaging preserves the
        # total loop time when ANI has a different rate per frame.
        "FrameDuration": sum(rates) / len(rates) / 60.0,
        "HotSpotX": min(hotspot_x / scale, 31.99),
        "HotSpotY": min(hotspot_y / scale, 31.99),
        "PointsWide": logical_width,
        "PointsHigh": logical_height,
        "Representations": [encode_png(width, height * len(sprite_frames), b"".join(sprite_frames))],
    }


def all_cursor_files(folder: Path) -> dict[str, Path]:
    files = [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in {".ani", ".cur"}]
    return {path.name.casefold(): path for path in files}


def roles_from_inf(folder: Path, files: dict[str, Path]) -> dict[str, Path]:
    """Read standard INF cursor-scheme order, falling back to string aliases."""
    roles: dict[str, Path] = {}
    for inf in sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".inf"):
        text = read_text_file(inf)
        definitions: dict[str, Path] = {}
        for line in text.splitlines():
            definition = re.match(r"\s*([^=;\s]+)\s*=\s*[\"']?([^\"',;\s]+\.(?:ani|cur))", line, flags=re.IGNORECASE)
            if not definition:
                continue
            variable = definition.group(1).casefold()
            filename = Path(definition.group(2).replace("\\", "/")).name.casefold()
            if filename in files:
                definitions[variable] = files[filename]

        # A standard cursor-scheme .inf registers seventeen variables in this
        # fixed Windows order: Arrow, Help, AppStarting, Wait, Crosshair,
        # IBeam, NWPen, No, SizeNS, SizeWE, SizeNWSE, SizeNESW, SizeAll,
        # UpArrow, Hand, Pin, Person.
        for line in text.splitlines():
            if "Control Panel\\Cursors\\Schemes" not in line:
                continue
            variable_names = [name.casefold() for name in re.findall(r"%([^%]+)%", line)]
            variable_names = [name for name in variable_names if name in definitions]
            if len(variable_names) < len(MAC_ROLE_MAP):
                continue
            for role, variable in zip(MAC_ROLE_MAP, variable_names[: len(MAC_ROLE_MAP)]):
                roles.setdefault(role, definitions[variable])

        # Some smaller INF packages simply define each cursor role directly.
        for variable, path in definitions.items():
            role = INF_VARIABLE_ROLES.get(variable)
            if role:
                roles.setdefault(role, path)
    return roles


def roles_from_filenames(files: dict[str, Path]) -> dict[str, Path]:
    roles: dict[str, Path] = {}
    for role, aliases in FILENAME_ROLE_ALIASES.items():
        for alias in aliases:
            exact = files.get(f"{alias}.ani") or files.get(f"{alias}.cur")
            if exact:
                roles[role] = exact
                break
        if role in roles:
            continue
        for path in files.values():
            stem = path.stem.casefold()
            if any(
                len(alias) >= 4
                and (stem.startswith(alias + "_") or stem.endswith("_" + alias) or stem.startswith(alias + "-") or stem.endswith("-" + alias))
                for alias in aliases
            ):
                roles[role] = path
                break
    return roles


def display_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def safe_identifier(name: str) -> str:
    identifier = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return f"local.{identifier or 'windows-cursor'}.windows-cursor"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a Windows cursor theme folder to a Mousecape .cape file.")
    parser.add_argument("--input", type=Path, default=Path.cwd(), help="Theme folder (default: current folder)")
    parser.add_argument("--output", type=Path, help="Destination .cape path (default: <name>.cape in the input folder)")
    parser.add_argument("--name", help="Cape display name (default: input folder name)")
    parser.add_argument("--author", default="Converted from a Windows cursor theme", help="Cape author metadata")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    folder = args.input.expanduser().resolve()
    if not folder.is_dir():
        raise CursorFormatError(f"input is not a folder: {folder}")
    name = args.name or folder.name
    output = (args.output.expanduser() if args.output else folder / f"{name}.cape").resolve()
    if output.suffix.casefold() != ".cape":
        output = output.with_suffix(".cape")

    files = all_cursor_files(folder)
    if not files:
        raise CursorFormatError("the input folder contains no .ani or .cur files")
    roles = roles_from_inf(folder, files)
    discovered_from = ".inf" if roles else "filenames"
    if not roles:
        roles = roles_from_filenames(files)
    if not roles:
        raise CursorFormatError("could not identify any standard Windows cursor roles")

    cursors: dict[str, dict] = {}
    converted = []
    failures = []
    for role, source in roles.items():
        try:
            cursor = convert_cursor(source)
        except CursorFormatError as error:
            failures.append(f"{source.name}: {error}")
            continue
        for identifier in MAC_ROLE_MAP[role]:
            cursors[identifier] = cursor
        converted.append((role, source, cursor["FrameCount"], MAC_ROLE_MAP[role]))

    if not cursors:
        raise CursorFormatError("none of the detected cursor files could be converted")

    cape = {
        "Author": args.author,
        "CapeName": name,
        "CapeVersion": 1.0,
        "Cloud": False,
        "Cursors": cursors,
        "HiDPI": True,
        "Identifier": safe_identifier(name),
        "MinimumVersion": 2.0,
        "Version": 2.0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as destination:
        plistlib.dump(cape, destination, fmt=plistlib.FMT_BINARY, sort_keys=True)

    print(f"Created: {output}")
    print(f"Cursor-role detection: {discovered_from}; {len(converted)} roles → {len(cursors)} macOS mappings")
    for role, source, frames, identifiers in converted:
        print(f"  {role:12} {display_path(source, folder):24} {frames:2} frame(s) → {', '.join(identifiers)}")
    if failures:
        print("\nSkipped unsupported files:", file=sys.stderr)
        print("\n".join(f"  {failure}" for failure in failures), file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (CursorFormatError, OSError, plistlib.InvalidFileException) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
