"""
GoldenHour — core/router.py
============================
Dynamic A* routing engine for EMS dispatch.

Mathematical foundation:
    f(n) = g(n) + h(n)
    where:
        g(n) = actual accumulated cost from source to node n
               = sum of edge weights along the best-known path
        h(n) = admissible heuristic (Euclidean distance to goal)
               = sqrt((x2-x1)^2 + (y2-y1)^2)

    Admissibility guarantee: h(n) never OVERESTIMATES true cost,
    which guarantees A* finds the globally optimal path.

Dynamic edge cost formula:
    cost(u, v) = base_time(u,v)
                 × traffic_multiplier(u,v)   [1.0 = clear, 5.0 = standstill]
                 × closure_penalty(u,v)       [999 = effectively impassable]
"""

import heapq
import math
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class RouteResult:
    """Returned by the router for each dispatch decision."""
    path: list[str]                    # ordered list of node IDs
    total_cost: float                  # estimated travel time in seconds
    distance_km: float
    hops: int
    recomputed: bool = False           # True if this was a mid-route re-plan
    blocked_edges: list[tuple] = field(default_factory=list)


class DynamicRouter:
    """
    A* router that operates on a live-weighted graph.
    
    The graph is a dict-of-dicts:
        graph[u][v] = {
            'base_time': float,      # seconds at free-flow speed
            'distance': float,       # km
            'traffic': float,        # multiplier, updated by simulation
            'blocked': bool          # True = road closure
        }
    
    Node positions stored separately for the heuristic:
        positions[node_id] = (lat, lon)
    """

    def __init__(self, graph: dict, positions: dict):
        self.graph = graph
        self.positions = positions

    def _heuristic(self, node: str, goal: str) -> float:
        """
        Euclidean distance heuristic in 'time units'.
        
        We convert lat/lon distance to an optimistic travel time
        assuming maximum possible speed (120 km/h with siren).
        
        h(n) = euclidean_distance_km / max_speed_kmh * 3600 seconds
        
        This is ADMISSIBLE because no ambulance can exceed max_speed_kmh,
        so h(n) can never overestimate actual remaining travel time.
        """
        MAX_SPEED_KMH = 120.0
        lat1, lon1 = self.positions[node]
        lat2, lon2 = self.positions[goal]
        # Approximate km from degrees (valid for city-scale distances)
        dlat = (lat2 - lat1) * 111.0
        dlon = (lon2 - lon1) * 111.0 * math.cos(math.radians(lat1))
        dist_km = math.sqrt(dlat**2 + dlon**2)
        return (dist_km / MAX_SPEED_KMH) * 3600

    def _edge_cost(self, u: str, v: str) -> float:
        """
        Live edge cost incorporating all dynamic constraints.
        
        cost(u,v) = base_time × traffic_multiplier × closure_penalty
        
        Traffic multiplier comes from the simulation engine and is
        updated in real-time. Blocked roads get penalty=999 (effectively
        infinite, but finite so the graph stays navigable — the algorithm
        will route around them rather than declaring no path found).
        """
        edge = self.graph[u][v]
        base = edge['base_time']
        traffic = edge.get('traffic', 1.0)
        blocked = edge.get('blocked', False)
        closure_penalty = 999.0 if blocked else 1.0
        return base * traffic * closure_penalty

    def find_route(self, source: str, target: str) -> Optional[RouteResult]:
        """
        Standard A* search with a binary min-heap (priority queue).
        
        Time complexity: O((V + E) log V) where V = nodes, E = edges
        Space complexity: O(V) for the open/closed sets
        
        The heap stores (f_cost, g_cost, node, path_so_far).
        We use g_cost as a tiebreaker to prefer shorter paths
        when two nodes have identical f scores.
        """
        if source not in self.graph or target not in self.graph:
            return None

        # g_score[n] = best known actual cost from source to n
        g_score = {source: 0.0}
        
        # Priority queue: (f, g, node, path)
        # f = g + h  — the A* priority
        h0 = self._heuristic(source, target)
        open_heap = [(h0, 0.0, source, [source])]
        
        visited = set()
        blocked_edges_encountered = []

        while open_heap:
            f, g, current, path = heapq.heappop(open_heap)

            if current in visited:
                continue
            visited.add(current)

            if current == target:
                # Reconstruct distance along path
                total_dist = sum(
                    self.graph[path[i]][path[i+1]]['distance']
                    for i in range(len(path)-1)
                )
                return RouteResult(
                    path=path,
                    total_cost=g,
                    distance_km=round(total_dist, 2),
                    hops=len(path)-1,
                    blocked_edges=blocked_edges_encountered
                )

            if current not in self.graph:
                continue

            for neighbor in self.graph[current]:
                if neighbor in visited:
                    continue

                edge = self.graph[current].get(neighbor, {})
                if edge.get('blocked', False):
                    blocked_edges_encountered.append((current, neighbor))

                tentative_g = g + self._edge_cost(current, neighbor)

                # Only explore if this is a better path to neighbor
                if tentative_g < g_score.get(neighbor, float('inf')):
                    g_score[neighbor] = tentative_g
                    h = self._heuristic(neighbor, target)
                    f_new = tentative_g + h
                    heapq.heappush(open_heap, (f_new, tentative_g, neighbor, path + [neighbor]))

        return None  # No path found (disconnected graph)

    def update_edge_weight(self, u: str, v: str, traffic: float = None, blocked: bool = None):
        """
        Live update of a single edge — called by the simulation engine
        when a traffic event fires or clears.
        
        This is the key to dynamic re-routing: we mutate the graph
        in-place, then any subsequent A* call reflects the new reality.
        """
        if u in self.graph and v in self.graph[u]:
            if traffic is not None:
                self.graph[u][v]['traffic'] = traffic
            if blocked is not None:
                self.graph[u][v]['blocked'] = blocked
