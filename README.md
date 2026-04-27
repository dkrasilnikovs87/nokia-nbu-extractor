# Nokia NBU Extractor

Extract contacts, SMS, photos, video and audio from Nokia PC Suite backup files (`.nbu`).

## What it extracts

| Folder | Content |
|---|---|
| `contacts_utf8/` | vCard 2.1 contacts (UTF-8) |
| `contacts_utf16/` | vCard 3.0 contacts (UTF-16-LE) |
| `sms/` | SMS messages (VMSG format) |
| `photos/` | JPEG photos ≥ 5 KB |
| `video/` | 3GP / MP4 video |
| `audio/` | MP3 audio |
| `media_other/` | Smaller JPEG thumbnails and misc media |

Output is saved next to the original file in a folder named `filename (extracted)/`.

## Usage

```bash
python3 nbu_extract.py file.nbu
python3 nbu_extract.py *.nbu
```

## Requirements

Python 3.6+, no external dependencies.

## Tested on

- Nokia 6280 (.nbu v2)

## Notes

- Duplicate files are skipped automatically (MD5 dedup)
- JPEG parser handles EXIF-embedded thumbnails correctly — extracts full-resolution images only
- SMS are stored as UTF-16-LE VMSG in Nokia backups — standard UTF-8 tools miss them
