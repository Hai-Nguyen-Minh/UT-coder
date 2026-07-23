def merge_intervals(intervals):
    items = []
    for start, end in intervals:
        if start > end:
            raise ValueError("start must be <= end")
        items.append((start, end))
    items.sort()
    merged = []
    for start, end in items:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [tuple(x) for x in merged]
