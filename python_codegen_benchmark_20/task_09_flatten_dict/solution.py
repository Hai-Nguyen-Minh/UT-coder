def flatten_dict(data, sep="."):
    result = {}

    def walk(obj, prefix):
        if isinstance(obj, dict):
            if not obj and prefix:
                result[prefix] = {}
                return
            for key, value in obj.items():
                new_key = str(key) if not prefix else prefix + sep + str(key)
                walk(value, new_key)
        else:
            result[prefix] = obj

    walk(data, "")
    return result
