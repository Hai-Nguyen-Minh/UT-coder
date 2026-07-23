def deduplicate_records(records, key):
    seen = set()
    result = []
    for record in records:
        value = record[key]
        if value not in seen:
            seen.add(value)
            result.append(dict(record))
    return result
