def rotate_clockwise(matrix):
    if not matrix:
        return []
    width = len(matrix[0])
    if any(len(row) != width for row in matrix):
        raise ValueError("matrix must be rectangular")
    if width == 0:
        return []
    return [list(row) for row in zip(*matrix[::-1])]
