"""Only synthetic classroom data; CSV safe for Excel."""
import csv
import io
import re


def decode_utf8(raw: bytes) -> str:
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('UTF-8 텍스트가 아닙니다. UTF-8로 다시 저장하세요.') from exc


def export_csv(rows: list[dict], columns: list[str]) -> bytes:
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        escaped = {}
        for key in columns:
            val = str(row.get(key, ''))
            if (val.lstrip().startswith(('=', '+', '@', '\t', '\r'))
                    or (val.lstrip().startswith('-') and not re.fullmatch(r'-[0-9]+(?:\.[0-9]+)?', val.lstrip()))):
                val = "'" + val  # Excel formula injection protection (export only)
            escaped[key] = val
        writer.writerow(escaped)
    return ('\ufeff' + stream.getvalue()).encode('utf-8')
