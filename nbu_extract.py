#!/usr/bin/env python3
"""
Nokia NBU v2 extractor
Extracts contacts (vCard), SMS (VMSG), photos (JPEG), video (3GP/MP4) and audio (MP3)
from Nokia PC Suite backup files (.nbu).

Usage:
    python3 nbu_extract.py file.nbu
    python3 nbu_extract.py *.nbu
"""

import sys
import os
import re
import struct
import hashlib
import shutil


def parse_jpeg_end(data, start):
    """Parse JPEG by segment length fields. Treats APP1/EXIF as opaque (skips embedded thumbnails)."""
    pos = start
    if data[pos:pos+2] != b'\xff\xd8':
        return None
    pos += 2
    while pos < len(data) - 1:
        if data[pos] != 0xFF:
            return None
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker == 0xD9:  # EOI
            return pos
        if marker == 0xD8:  # unexpected SOI
            return pos - 2
        if 0xD0 <= marker <= 0xD7:  # RSTn
            continue
        if marker == 0x01:  # TEM
            continue
        if pos + 2 > len(data):
            break
        seg_len = struct.unpack_from('>H', data, pos)[0]
        if seg_len < 2:
            return pos
        if marker == 0xDA:  # SOS: skip header then scan entropy data
            pos += seg_len
            while pos < len(data) - 1:
                if data[pos] != 0xFF:
                    pos += 1
                elif data[pos+1] == 0x00:   # byte stuffing
                    pos += 2
                elif 0xD0 <= data[pos+1] <= 0xD7:  # RST
                    pos += 2
                elif data[pos+1] == 0xD9:   # EOI
                    pos += 2
                    return pos
                else:
                    break
        else:
            pos += seg_len
    return pos


def extract_nbu(nbu_path):
    out_base = os.path.splitext(nbu_path)[0] + " (extracted)"
    if os.path.exists(out_base):
        shutil.rmtree(out_base)

    dirs = {}
    for d in ['contacts_utf8', 'contacts_utf16', 'sms', 'video', 'photos', 'audio', 'media_other']:
        dirs[d] = os.path.join(out_base, d)
        os.makedirs(dirs[d])

    with open(nbu_path, 'rb') as f:
        data = f.read()

    # Verify NBU magic
    magic = bytes.fromhex('cc5233fce92c1848afe336301a394006')
    if data[:16] != magic:
        print(f"  WARNING: NBU magic not found in {os.path.basename(nbu_path)}")

    seen = set()

    def save(folder, ext, chunk):
        if len(chunk) < 8:
            return False
        h = hashlib.md5(chunk).hexdigest()
        if h in seen:
            return False
        seen.add(h)
        cnt = len(os.listdir(folder)) + 1
        with open(os.path.join(folder, f'{cnt:04d}{ext}'), 'wb') as f:
            f.write(chunk)
        return True

    # UTF-8 vCards (vCard 2.1)
    for m in re.finditer(rb'BEGIN:VCARD\r?\n.*?END:VCARD\r?\n?', data, re.DOTALL):
        save(dirs['contacts_utf8'], '.vcf', m.group())

    # UTF-16-LE vCards (vCard 3.0)
    needle = 'BEGIN:VCARD'.encode('utf-16-le')
    ending = 'END:VCARD'.encode('utf-16-le')
    pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx == -1:
            break
        end_idx = data.find(ending, idx)
        if end_idx == -1:
            pos = idx + 2
            continue
        end_idx += len(ending) + 4
        save(dirs['contacts_utf16'], '.vcf', data[idx:end_idx])
        pos = end_idx

    # UTF-16-LE SMS (vMessage)
    needle_sms = 'BEGIN:VMSG'.encode('utf-16-le')
    ending_sms = 'END:VMSG'.encode('utf-16-le')
    pos = 0
    while True:
        idx = data.find(needle_sms, pos)
        if idx == -1:
            break
        end_idx = data.find(ending_sms, idx)
        if end_idx == -1:
            pos = idx + 2
            continue
        end_idx += len(ending_sms) + 4
        save(dirs['sms'], '.vmsg', data[idx:end_idx])
        pos = end_idx

    # 3GP / MP4 videos (ISOBMFF ftyp atom)
    pos = 0
    while True:
        idx = data.find(b'ftyp', pos)
        if idx == -1:
            break
        atom_start = idx - 4
        if atom_start < 0:
            pos = idx + 4
            continue
        p = atom_start
        file_end = atom_start
        for _ in range(500):
            if p + 8 > len(data):
                break
            sz = struct.unpack_from('>I', data, p)[0]
            if sz == 0:
                file_end = len(data)
                break
            if sz < 8 or sz > 60_000_000:
                break
            try:
                tp = data[p+4:p+8].decode('ascii')
            except Exception:
                break
            if not all(c.isalnum() or c in '_ .' for c in tp):
                break
            file_end = p + sz
            p += sz
        if file_end > atom_start + 1000:
            chunk = data[atom_start:file_end]
            brand = data[idx+4:idx+8].decode('ascii', 'replace')
            ext = '.3gp' if '3gp' in brand else '.mp4'
            save(dirs['video'], ext, chunk)
        pos = idx + 4

    # JPEG photos — proper parser, non-overlapping, skip tiny thumbnails (< 5 KB)
    pos = 0
    last_end = 0
    while True:
        idx = data.find(b'\xff\xd8\xff', pos)
        if idx == -1:
            break
        pos = idx + 3
        if idx < last_end:
            continue
        end = parse_jpeg_end(data, idx)
        if end is None or end - idx < 1000:
            continue
        folder = dirs['photos'] if end - idx >= 5000 else dirs['media_other']
        save(folder, '.jpg', data[idx:end])
        last_end = end

    # MP3 audio (ID3v2 tag + MPEG frames)
    pos = 0
    while True:
        idx = data.find(b'ID3', pos)
        if idx == -1:
            break
        pos = idx + 3
        if idx + 10 > len(data) or data[idx+3] > 4:
            continue
        sz_b = data[idx+6:idx+10]
        id3_size = (sz_b[0] << 21) | (sz_b[1] << 14) | (sz_b[2] << 7) | sz_b[3]
        tag_end = idx + 10 + id3_size
        p = tag_end
        mp3_end = p
        frame_count = 0
        bitrates = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
        samplerates = [44100, 48000, 32000, 0]
        while p < len(data) - 4:
            if data[p] == 0xFF and data[p+1] in (0xFB, 0xFA, 0xF3, 0xF2, 0xFE, 0xE2, 0xE3):
                hdr = struct.unpack_from('>I', data, p)[0]
                bitrate_idx = (hdr >> 12) & 0xF
                sr_idx = (hdr >> 10) & 3
                if bitrate_idx in (0, 15) or sr_idx == 3:
                    p += 1
                    continue
                br = bitrates[bitrate_idx] * 1000
                sr = samplerates[sr_idx]
                padding = (hdr >> 9) & 1
                frame_len = int(144 * br / sr) + padding
                if frame_len < 26 or frame_len > 2000:
                    p += 1
                    continue
                mp3_end = p + frame_len
                p += frame_len
                frame_count += 1
            else:
                if frame_count > 5:
                    break
                p += 1
        if frame_count > 10:
            save(dirs['audio'], '.mp3', data[idx:mp3_end])

    counts = {k: len(os.listdir(v)) for k, v in dirs.items()}
    return counts


def main():
    paths = sys.argv[1:]
    if not paths:
        print("Usage: python3 nbu_extract.py file.nbu [file2.nbu ...]")
        sys.exit(1)

    for path in paths:
        if not os.path.isfile(path):
            print(f"Not found: {path}")
            continue
        print(f"\n{os.path.basename(path)}")
        counts = extract_nbu(path)
        for folder, count in counts.items():
            if count > 0:
                print(f"  {folder:<18} {count}")


if __name__ == '__main__':
    main()
