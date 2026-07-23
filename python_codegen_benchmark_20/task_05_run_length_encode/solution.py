def run_length_encode(text):
    if not text:
        return []
    result = []
    current = text[0]
    count = 1
    for ch in text[1:]:
        if ch == current:
            count += 1
        else:
            result.append((current, count))
            current, count = ch, 1
    result.append((current, count))
    return result
