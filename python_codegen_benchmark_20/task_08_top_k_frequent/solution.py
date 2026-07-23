def top_k_frequent(items, k):
    if k <= 0:
        return []
    counts = {}
    first = {}
    for i, item in enumerate(items):
        counts[item] = counts.get(item, 0) + 1
        first.setdefault(item, i)
    ordered = sorted(counts, key=lambda x: (-counts[x], first[x]))
    return ordered[:k]
