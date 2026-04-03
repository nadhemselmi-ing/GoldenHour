# GoldenHour — Dynamic EMS Routing Optimizer

> *"GPS routes cars. We route ambulances."*

Real-time multi-constraint EMS dispatch system using A* pathfinding
on a dynamically-weighted city road graph.

## Quick Start

```bash
pip install -r requirements.txt

# Demo mode (no server needed — runs in terminal)
python run_demo.py

# Full API server
uvicorn api.main:app --reload --port 8000
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/state` | Full simulation snapshot |
| POST | `/incident?severity=1` | Inject emergency (1=critical) |
| POST | `/traffic/jam` | Trigger traffic jam |
| POST | `/traffic/closure` | Block a road |
| GET | `/hospitals` | Hospital capacity status |
| GET | `/stats` | Dispatch statistics |
| WS | `/ws/live` | Real-time state stream |

## Architecture

```
Data Feeds (traffic/hospital/weather)
        ↓
Dynamic Weighted Graph (NetworkX-style dict-of-dicts)
        ↓
A* Optimizer  f(n) = g(n) + h(n)
        ↓
Dispatch Decision (unit + hospital + route)
        ↓
Live Re-routing (triggered on constraint change)
        ↓
Operator Dashboard (WebSocket push)
```

## Core Algorithm

**A* with dynamic edge weights:**

```
f(n) = g(n) + h(n)
  g(n) = actual cost from source (sum of live edge weights)
  h(n) = Euclidean distance heuristic (admissible → optimal)

edge_cost(u,v) = base_time × traffic_multiplier × closure_penalty
hospital_score = route_time + load_penalty(capacity_ratio)
```

## File Structure

```
goldenhour/
├── core/
│   └── router.py          ← A* engine with dynamic weights
├── simulation/
│   ├── city_graph.py      ← Procedural city network + entities
│   └── engine.py          ← Simulation loop, events, dispatch logic
├── api/
│   └── main.py            ← FastAPI + WebSocket server
├── run_demo.py            ← Standalone terminal demo
└── requirements.txt
```
