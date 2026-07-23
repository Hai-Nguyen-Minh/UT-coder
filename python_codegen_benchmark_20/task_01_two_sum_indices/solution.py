def two_sum_indices(nums, target):
    seen = {}
    for j, value in enumerate(nums):
        need = target - value
        if need in seen:
            return (seen[need], j)
        if value not in seen:
            seen[value] = j
    return None
