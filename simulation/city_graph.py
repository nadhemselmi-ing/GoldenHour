"""
GoldenHour — simulation/city_graph.py
======================================
Procedural city road network generator.

Generates a realistic weighted graph representing a city's road network.
In production this would load from OSMnx (OpenStreetMap), but for the
hackathon demo we generate a parametric grid-based city with:
  - A downtown core (dense nodes, short edges)
  - Arterial roads (wider, faster, higher capacity)
  - Residential grids (slower, more blockable)
  - Hospital and ambulance depot locations

Graph model:
    Nodes = road intersections  (ID: "N_{row}_{col}")
    Edges = road segments       (bidirectional, stored as two directed edges)
    
Edge attributes:
    base_time   : free-flow travel time in seconds
    distance    : km
    traffic     : live multiplier (1.0 = clear)
    blocked     : bool (road closure)
    road_type   : 'arterial' | 'residential' | 'highway'
"""

import math
import random
from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class Hospital:
    node_id: str
    name: str
    lat: float
    lon: float
    capacity: int          # total ER beds
    current_load: int = 0  # currently occupied beds

    @property
    def load_ratio(self) -> float:
        return self.current_load / self.capacity

    @property
    def is_available(self) -> bool:
        return self.load_ratio < 0.95

    @property
    def load_penalty(self) -> float:
        """
        Extra time penalty (seconds) added to routing cost based on load.
        
        A full hospital means longer handoff time and potential rerouting
        of the patient once there — we bake this into dispatch cost.
        
        Penalty curve: exponential above 70% load
            penalty = 0                     if load < 0.70
            penalty = 300 × (load - 0.70)^2 if load >= 0.70
        """
        if self.load_ratio < 0.70:
            return 0.0
        excess = self.load_ratio - 0.70
        return 300.0 * (excess ** 2) * 50


@dataclass
class Ambulance:
    unit_id: str
    node_id: str          # current location node
    lat: float
    lon: float
    status: str = 'available'   # 'available' | 'dispatched' | 'at_scene' | 'transporting'
    crew: int = 2
    current_route: list = field(default_factory=list)
    assigned_incident: str = None


@dataclass
class Incident:
    incident_id: str
    node_id: str
    lat: float
    lon: float
    severity: int       # 1=critical, 2=urgent, 3=standard
    timestamp: float
    resolved: bool = False
    assigned_unit: str = None


class CityGraph:
    """
    Procedurally generated city road network.
    
    Grid dimensions: ROWS × COLS intersections
    Coordinate system: lat/lon centered on a reference city
    
    Road hierarchy:
        Every 5th row/col = arterial road (speed limit 60km/h)
        Others = residential (speed limit 30km/h)
        Border edges = ring road (speed limit 80km/h)
    """

    # Tunis, Tunisia as reference center (realistic for demo)
    BASE_LAT = 36.8190
    BASE_LON = 10.1658
    # ~100m between intersections in degrees
    GRID_SPACING_DEG = 0.0009

    def __init__(self, rows: int = 20, cols: int = 20, seed: int = 42):
        self.rows = rows
        self.cols = cols
        random.seed(seed)
        
        self.graph: dict = {}
        self.positions: dict = {}
        self.hospitals: list[Hospital] = []
        self.ambulances: list[Ambulance] = []
        
        self._build_grid()
        self._place_hospitals()
        self._place_ambulances()

    def _node_id(self, r: int, c: int) -> str:
        return f"N_{r:02d}_{c:02d}"

    def _road_type(self, r1: int, c1: int, r2: int, c2: int) -> str:
        """Classify road based on grid position."""
        # Border = ring road
        if r1 == 0 or r1 == self.rows-1 or c1 == 0 or c1 == self.cols-1:
            return 'highway'
        # Every 5th row or col = arterial
        if r1 % 5 == 0 or c1 % 5 == 0:
            return 'arterial'
        return 'residential'

    def _speed_for_type(self, road_type: str) -> float:
        """Free-flow speed in km/h."""
        return {'highway': 80.0, 'arterial': 60.0, 'residential': 30.0}[road_type]

    def _build_grid(self):
        """
        Build the road graph as a bidirectional weighted grid.
        
        Each cell (r, c) becomes a node. Edges connect horizontally
        and vertically adjacent nodes. Diagonal shortcuts do not exist
        (city blocks don't have diagonal roads).
        """
        # Place nodes
        for r in range(self.rows):
            for c in range(self.cols):
                nid = self._node_id(r, c)
                lat = self.BASE_LAT + r * self.GRID_SPACING_DEG
                lon = self.BASE_LON + c * self.GRID_SPACING_DEG
                self.positions[nid] = (lat, lon)
                self.graph[nid] = {}

        # Connect edges (4-directional grid)
        for r in range(self.rows):
            for c in range(self.cols):
                nid = self._node_id(r, c)
                neighbors = []
                if r + 1 < self.rows: neighbors.append((r+1, c))
                if r - 1 >= 0:        neighbors.append((r-1, c))
                if c + 1 < self.cols: neighbors.append((r, c+1))
                if c - 1 >= 0:        neighbors.append((r, c-1))

                for nr, nc in neighbors:
                    nbr = self._node_id(nr, nc)
                    rtype = self._road_type(r, c, nr, nc)
                    speed = self._speed_for_type(rtype)

                    # Distance: one grid cell ≈ 100m = 0.10 km
                    dist_km = 0.10 + random.uniform(-0.01, 0.02)  # slight variance

                    # base_time = distance / speed (hours) × 3600 = seconds
                    base_time = (dist_km / speed) * 3600

                    self.graph[nid][nbr] = {
                        'base_time': base_time,
                        'distance': dist_km,
                        'traffic': 1.0,
                        'blocked': False,
                        'road_type': rtype
                    }

    def _place_hospitals(self):
        """Distribute hospitals across quadrants of the city."""
        hospital_configs = [
            (4,  4,  "North-West General",      80),
            (4,  15, "North-East Trauma Center", 60),
            (10, 10, "City Central Hospital",   120),
            (15, 4,  "South-West Regional",      50),
            (15, 15, "South-East Medical",       70),
        ]
        for r, c, name, cap in hospital_configs:
            nid = self._node_id(r, c)
            lat, lon = self.positions[nid]
            self.hospitals.append(Hospital(
                node_id=nid, name=name, lat=lat, lon=lon,
                capacity=cap,
                current_load=random.randint(int(cap * 0.3), int(cap * 0.8))
            ))

    def _place_ambulances(self):
        """Place ambulance units at depot positions."""
        depot_configs = [
            (2,  2,  "ALPHA-1"),
            (2,  17, "ALPHA-2"),
            (10, 2,  "BRAVO-1"),
            (10, 17, "BRAVO-2"),
            (17, 10, "CHARLIE-1"),
            (5,  10, "DELTA-1"),
        ]
        for r, c, uid in depot_configs:
            nid = self._node_id(r, c)
            lat, lon = self.positions[nid]
            self.ambulances.append(Ambulance(
                unit_id=uid, node_id=nid, lat=lat, lon=lon
            ))

    def get_hospital_by_node(self, node_id: str) -> Hospital:
        for h in self.hospitals:
            if h.node_id == node_id:
                return h
        return None

    def get_available_ambulances(self) -> list[Ambulance]:
        return [a for a in self.ambulances if a.status == 'available']
