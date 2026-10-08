"""Write uncompressed Wuthering Waves V12 localization archives.

SPDX-License-Identifier: GPL-3.0-or-later
Format references: FabianFG/CUE4Parse FPakEntry.cs and PakFileReader.cs;
Arkael-Dev/WuwaIDLauncher WuwaPakPacker.cs (GPL-3.0).
No encryption, signing, game code patches, or signature-check changes.
"""
import hashlib
import io
import struct
from pathlib import Path

MAGIC = 0x5A6F12E1

def u32(value): return struct.pack('<I', value)
def u64(value): return struct.pack('<Q', value)
def digest(data): return hashlib.sha1(data).digest()
def string(value):
    raw = value.encode('utf-8') + b'\0'
    return u32(len(raw)) + raw

def path_hash(path, seed=0):
    result = (0xCBF29CE484222325 + seed) & 0xFFFFFFFFFFFFFFFF
    for byte in path.lower().encode('utf-16le'):
        result = ((result ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return result

def pack(source, destination, cancelled=None):
    source, destination = Path(source), Path(destination)
    paths = sorted(p for p in source.rglob('*') if p.is_file())
    if not paths: raise ValueError('No localization databases to pack')
    entries = []
    with destination.open('wb') as out:
        for path in paths:
            if cancelled is not None:
                from translator import check_cancel
                check_cancel(cancelled)
            relative = path.relative_to(source).as_posix()
            if not relative.startswith('Client/Content/Aki/ConfigDB/en/') or path.suffix != '.db':
                raise ValueError('Only English localization databases may be packed')
            data = path.read_bytes()
            offset, size = out.tell(), len(data)
            if max(offset, size) > 0xFFFFFFFF:
                raise ValueError('V12 localization writer supports archives smaller than 4 GiB')
            # Serialized FPakEntry, followed by the uncompressed SQLite bytes.
            out.write(struct.pack('<QQQI', 0, size, size, 0))
            out.write(digest(data) + b'\0' + u32(0))
            out.write(data)
            entries.append((relative, offset, size))

        index_offset = out.tell()
        encoded = bytearray()
        directories = {'/': {}}
        hashes = bytearray(u32(len(entries)))
        for relative, offset, size in entries:
            entry_offset = len(encoded)
            # V12 permutations: all three 32-bit-safe flags set, no compression;
            # extra custom-data byte, then size BEFORE file offset.
            encoded += u32(0xE0000000) + b'\0' + u32(size) + u32(offset)
            hashes += u64(path_hash(relative)) + u32(entry_offset)
            parent, name = relative.rsplit('/', 1)
            directories.setdefault(parent + '/', {})[name] = entry_offset
            while '/' in parent:
                parent = parent.rsplit('/', 1)[0]
                directories.setdefault(parent + '/', {})
        hashes += u32(0)  # Empty pruned directory index.
        directory = bytearray(u32(len(directories)))
        for name, files in sorted(directories.items()):
            directory += string(name) + u32(len(files))
            for filename, offset in sorted(files.items()):
                directory += string(filename) + u32(offset)

        mount = string('../../../')
        primary_size = len(mount) + 4 + 8 + 2 * (4 + 8 + 8 + 20) + 4 + len(encoded) + 4
        hash_offset = index_offset + primary_size
        dir_offset = hash_offset + len(hashes)
        primary = (mount + u32(len(entries)) + u64(0)
                   + u32(1) + u64(hash_offset) + u64(len(hashes)) + digest(hashes)
                   + u32(1) + u64(dir_offset) + u64(len(directory)) + digest(directory)
                   + u32(len(encoded)) + encoded + u32(0))
        if len(primary) != primary_size: raise AssertionError('Primary index size mismatch')
        out.write(primary + hashes + directory)
        out.write(bytes(17) + u32(MAGIC) + u32(12)
                  + u64(index_offset) + u64(len(primary)) + digest(primary) + bytes(160))
    return destination
