def deep_get(data, path, default=None):
    if path == "":
        return data
    current = data
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                return default
            current = current[segment]
        elif isinstance(current, (list, tuple)):
            try:
                index = int(segment)
            except ValueError:
                return default
            if str(index) != segment or index < 0 or index >= len(current):
                return default
            current = current[index]
        else:
            return default
    return current
