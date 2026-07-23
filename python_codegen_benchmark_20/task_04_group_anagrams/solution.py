def group_anagrams(words):
    groups = {}
    order = []
    for word in words:
        key = tuple(sorted(word))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(word)
    return [groups[key] for key in order]
