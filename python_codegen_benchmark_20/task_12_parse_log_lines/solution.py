from datetime import datetime

def parse_log_lines(lines):
    result = []
    for line_no, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        parts = raw.split("|", 2)
        if len(parts) != 3:
            raise ValueError(f"invalid log line {line_no}")
        ts_text, level, message = (part.strip() for part in parts)
        try:
            timestamp = datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError(f"invalid log line {line_no}") from exc
        if not level:
            raise ValueError(f"invalid log line {line_no}")
        result.append({
            "timestamp": timestamp,
            "level": level.upper(),
            "message": message,
        })
    return result
