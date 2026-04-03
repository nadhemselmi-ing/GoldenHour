"""
GoldenHour — run_demo.py
=========================
Standalone simulation demo. Run this to see the engine in action
WITHOUT needing to start the full API server.

Usage:
    python run_demo.py

Output: Live simulation log showing:
  - Traffic events spawning and clearing
  - Incidents being dispatched
  - A* routing decisions with costs
  - Mid-route re-routing when events hit active paths
  - Hospital load balancing
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import time
import json
from simulation.engine import SimulationEngine


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║          G O L D E N H O U R  —  EMS Optimizer          ║
║     Dynamic A* Routing · Real-Time Constraint Engine     ║
╚══════════════════════════════════════════════════════════╝
    """)


def print_state_summary(state: dict, tick: int):
    """Print a clean dashboard summary to the terminal."""
    print(f"\n{'─'*58}")
    print(f"  TICK {tick:04d}  |  Sim time: {state['sim_time']/60:.1f} min")
    print(f"{'─'*58}")
    
    # Ambulances
    print("  UNITS:")
    for a in state['ambulances']:
        status_icon = {'available': '🟢', 'dispatched': '🔴', 'transporting': '🟡'}.get(a['status'], '⚪')
        incident_str = f" → {a['incident']}" if a['incident'] else ""
        print(f"    {status_icon} {a['id']:12s}  {a['status']:12s}{incident_str}")

    # Hospitals
    print("  HOSPITALS:")
    for h in state['hospitals']:
        bar_len = int(h['load_ratio'] * 20)
        bar = '█' * bar_len + '░' * (20 - bar_len)
        avail = '✓' if h['available'] else '✗'
        print(f"    [{avail}] {h['name'][:22]:22s}  [{bar}] {h['load_ratio']:.0%}")

    # Active events
    if state['events']:
        print("  ACTIVE EVENTS:")
        for ev in state['events']:
            print(f"    ⚠  {ev['id']:16s}  {ev['type']:8s}  ×{ev['multiplier']:.1f}  TTL:{ev['ttl']:.0f}s")

    # Stats
    s = state['stats']
    print(f"  STATS: dispatches={s['total_dispatches']}  reroutes={s['total_reroutes']}  resolved={s['incidents_resolved']}")


def run_demo(ticks: int = 20, delay: float = 0.8):
    print_banner()
    print("  Initializing 20×20 city grid (400 intersections, ~3200 edges)...")
    
    engine = SimulationEngine(rows=20, cols=20)
    
    print(f"  City built:")
    print(f"    Nodes (intersections): {len(engine.city.graph)}")
    edge_count = sum(len(v) for v in engine.city.graph.values())
    print(f"    Edges (road segments): {edge_count}")
    print(f"    Hospitals:             {len(engine.city.hospitals)}")
    print(f"    Ambulance units:       {len(engine.city.ambulances)}")
    
    # Force some interesting events for demo
    print("\n  [DEMO] Forcing initial events for demonstration...")
    engine.spawn_incident(severity=1)     # critical incident
    engine.spawn_traffic_jam()            # jam immediately
    
    # Dispatch the incident
    for inc in engine.active_incidents:
        if not inc.resolved:
            decision = engine.dispatch(inc)
            if decision:
                print(f"\n  ✅ DISPATCH DECISION:")
                print(f"     Incident:    {decision.incident_id}  (severity {inc.severity})")
                print(f"     Unit:        {decision.ambulance_id}")
                print(f"     Hospital:    {engine.city.get_hospital_by_node(decision.hospital_id).name}")
                print(f"     ETA total:   {decision.estimated_total_time:.0f}s ({decision.estimated_total_time/60:.1f} min)")
                print(f"     Route hops:  {decision.route_to_scene.hops} to scene + {decision.route_to_hospital.hops} to hospital")
                print(f"     Distance:    {decision.route_to_scene.distance_km:.2f} km + {decision.route_to_hospital.distance_km:.2f} km")

    # Main simulation loop
    print(f"\n  Running {ticks} simulation ticks...\n")
    for i in range(ticks):
        engine.tick(dt=30.0)
        
        if i % 3 == 0:  # print every 3 ticks
            print_state_summary(engine.get_state(), i)
        
        time.sleep(delay)

    # Final summary
    print(f"\n{'═'*58}")
    print("  SIMULATION COMPLETE")
    print(f"{'═'*58}")
    final = engine.get_state()
    s = final['stats']
    print(f"  Total dispatches:   {s['total_dispatches']}")
    print(f"  Total re-routes:    {s['total_reroutes']}  ← dynamic adaptation in action")
    print(f"  Incidents resolved: {s['incidents_resolved']}")
    print(f"  Sim time elapsed:   {final['sim_time']/60:.1f} minutes")
    
    if s['total_dispatches'] > 0:
        reroute_pct = s['total_reroutes'] / s['total_dispatches'] * 100
        print(f"\n  → {reroute_pct:.1f}% of dispatches required mid-route re-optimization")
        print(f"  → This proves the system adapts to dynamic real-world constraints.")
    print()


if __name__ == "__main__":
    run_demo(ticks=20, delay=0.6)
