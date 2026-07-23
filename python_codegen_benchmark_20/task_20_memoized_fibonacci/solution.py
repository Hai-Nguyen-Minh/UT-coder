class MemoizedFibonacci:
    def __init__(self):
        self._cache = {0: 0, 1: 1}
        self._computed_count = 0

    @property
    def computed_count(self):
        return self._computed_count

    def fib(self, n):
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise ValueError("n must be a non-negative integer")
        if n in self._cache:
            return self._cache[n]
        for i in range(max(self._cache) + 1, n + 1):
            self._cache[i] = self._cache[i - 1] + self._cache[i - 2]
            self._computed_count += 1
        return self._cache[n]
