"""
GoldenHour — api/main.py
=========================
FastAPI application server.

Endpoints:
    GET  /state          — current simulation snapshot
    GET  /dispatch/{id}  — dispatch a specific incident manually
    POST /incident       — inject a custom incident
    WS   /ws/live        — WebSocket for real-time dashboard push

The simulation engine runs in a background asyncio task,
ticking every 5 seconds (= 30s simulated time per real second).
"""

import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from simulation.engine import SimulationEngine


# ─────────────────────────────────────────────
# App lifecycle: engine starts with the app
# ─────────────────────────────────────────────

engine = SimulationEngine(rows=20, cols=20)
connected_clients: list[WebSocket] = []


async def simulation_loop():
    """Background task: tick the engine and push state to all WebSocket clients."""
    while True:
        engine.tick(dt=30.0)
        state = engine.get_state()
        payload = json.dumps(state)
        
        # Broadcast to all connected dashboard clients
        dead = []
        for ws in connected_clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            connected_clients.remove(ws)
        
        await asyncio.sleep(5)  # 5 real seconds = 30 simulated seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(simulation_loop())
    yield
    task.cancel()


app = FastAPI(
    title="GoldenHour EMS Optimizer",
    description="Dynamic A* EMS routing with real-time constraint adaptation",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────

@app.get("/state")
async def get_state():
    """Full simulation snapshot — used for dashboard initial load."""
    return engine.get_state()


@app.post("/incident")
async def create_incident(severity: int = 2):
    """
    Manually inject an incident.
    Useful for live hackathon demos — judges can trigger emergencies.
    """
    incident = engine.spawn_incident(severity=severity)
    decision = engine.dispatch(incident)
    return {
        "incident": incident.incident_id,
        "severity": incident.severity,
        "assigned_unit": decision.ambulance_id if decision else None,
        "hospital": decision.hospital_id if decision else None,
        "eta_seconds": round(decision.estimated_total_time, 1) if decision else None,
        "route_hops": decision.route_to_scene.hops if decision else None,
    }


@app.post("/traffic/jam")
async def trigger_jam():
    """Manually trigger a traffic jam — for demo purposes."""
    event = engine.spawn_traffic_jam()
    engine.check_reroutes()
    return {"event_id": event.event_id, "multiplier": round(event.multiplier, 2)}


@app.post("/traffic/closure")
async def trigger_closure():
    """Manually trigger a road closure."""
    event = engine.spawn_road_closure()
    engine.check_reroutes()
    return {"event_id": event.event_id, "duration": event.duration}


@app.get("/hospitals")
async def get_hospitals():
    return [
        {
            "id": h.node_id,
            "name": h.name,
            "load_ratio": round(h.load_ratio, 3),
            "available": h.is_available,
            "load_penalty_seconds": round(h.load_penalty, 1),
        }
        for h in engine.city.hospitals
    ]


@app.get("/stats")
async def get_stats():
    return {
        **engine.stats,
        "active_events": len(engine.active_events),
        "pending_incidents": sum(1 for i in engine.active_incidents if not i.resolved),
        "sim_time_hours": round(engine.sim_time / 3600, 2),
    }


# ─────────────────────────────────────────────
# WebSocket — real-time dashboard feed
# ─────────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket connection for the live dashboard.
    
    On connect: send current state immediately.
    Then: simulation loop pushes updates every 5 seconds.
    On disconnect: client removed from broadcast list.
    """
    await websocket.accept()
    connected_clients.append(websocket)
    
    # Send current state immediately on connect
    await websocket.send_text(json.dumps(engine.get_state()))
    
    try:
        while True:
            # Keep connection alive; simulation loop handles pushes
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
