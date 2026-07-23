import heapq

def dependency_order(graph):
    nodes = set(graph)
    for deps in graph.values():
        nodes.update(deps)

    indegree = {node: 0 for node in nodes}
    dependents = {node: [] for node in nodes}

    for node, deps in graph.items():
        unique_deps = set(deps)
        indegree[node] += len(unique_deps)
        for dep in unique_deps:
            dependents[dep].append(node)

    heap = [(str(node), i, node) for i, node in enumerate(nodes) if indegree[node] == 0]
    heapq.heapify(heap)
    result = []

    while heap:
        _, _, node = heapq.heappop(heap)
        result.append(node)
        for nxt in dependents[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(heap, (str(nxt), len(result) + len(heap), nxt))

    if len(result) != len(nodes):
        raise ValueError("cycle detected")
    return result
