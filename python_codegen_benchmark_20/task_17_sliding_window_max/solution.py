from collections import deque

def sliding_window_max(nums, k):
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0 or k > len(nums):
        raise ValueError("invalid window size")
    dq = deque()
    result = []
    for i, value in enumerate(nums):
        while dq and dq[0] <= i - k:
            dq.popleft()
        while dq and nums[dq[-1]] <= value:
            dq.pop()
        dq.append(i)
        if i >= k - 1:
            result.append(nums[dq[0]])
    return result
