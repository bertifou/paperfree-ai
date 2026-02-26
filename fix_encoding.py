#!/usr/bin/env python3
"""
Fix mojibake in all frontend and backend files.
Mojibake pattern: UTF-8 bytes of original text were interpreted as Windows-1252,
then stored as UTF-8 again.
"""
import os
import re

# CP1252 reverse mapping for chars that differ from Latin-1
CP1252_TO_BYTE = {
    0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84,
    0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87, 0x02C6: 0x88,
    0x2030: 0x89, 0x0160: 0x8A, 0x2039: 0x8B, 0x0152: 0x8C,
    0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92, 0x201C: 0x93,
    0x201D: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97,
    0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B,
    0x0153: 0x9C, 0x017E: 0x9E, 0x0178: 0x9F,
}

def char_to_cp1252_byte(ch):
    """Convert a single Unicode char to its CP1252 byte value, or None if not possible."""
    cp = ord(ch)
    if cp < 256:
        return cp
    return CP1252_TO_BYTE.get(cp)

def try_fix_sequence(chars):
    """Try to decode a sequence of non-ASCII chars as mojibake. Returns fixed string or None."""
    original_bytes = bytearray()
    for ch in chars:
        b = char_to_cp1252_byte(ch)
        if b is None:
            return None
        original_bytes.append(b)
    try:
        return original_bytes.decode('utf-8')
    except:
        return None

def fix_mojibake(text):
    """Fix all mojibake sequences in text."""
    result = []
    i = 0
    chars = list(text)
    fixed_count = 0

    while i < len(chars):
        if ord(chars[i]) > 127:
            # Collect run of non-ASCII chars
            j = i
            while j < len(chars) and ord(chars[j]) > 127:
                j += 1
            run = chars[i:j]

            # Try fixing the whole run, then progressively smaller chunks
            fixed = False
            pos = 0
            fixed_parts = []
            while pos < len(run):
                found = False
                for size in range(len(run) - pos, 0, -1):
                    chunk = run[pos:pos+size]
                    decoded = try_fix_sequence(chunk)
                    if decoded is not None:
                        fixed_parts.append(decoded)
                        pos += size
                        fixed_count += 1
                        found = True
                        break
                if not found:
                    fixed_parts.append(run[pos])
                    pos += 1

            result.extend(fixed_parts)
            i = j
        else:
            result.append(chars[i])
            i += 1

    return ''.join(result), fixed_count


def fix_file(fp):
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()
    fixed, count = fix_mojibake(content)
    if count > 0:
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(fixed)
        print(f'  Fixed {count} sequences in {fp}')
    return count


# Collect files
files = []
for root, dirs, fs in os.walk('frontend'):
    dirs[:] = [d for d in dirs if not d.startswith('.')]
    for fn in fs:
        if fn.endswith(('.html', '.js')):
            files.append(os.path.join(root, fn))

for root, dirs, fs in os.walk('backend'):
    dirs[:] = [d for d in dirs if not d.startswith('.')]
    for fn in fs:
        if fn.endswith('.py'):
            files.append(os.path.join(root, fn))

total = 0
for fp in files:
    try:
        total += fix_file(fp)
    except Exception as e:
        print(f'  ERROR {fp}: {e}')

print(f'\nTotal: {total} mojibake sequences fixed across {len(files)} files.')
