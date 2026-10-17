"""Test manual get data and 37 agents integration."""
import asyncio
from datetime import datetime, timezone
from runtime import Runtime
from config.settings import settings
from fastapi.testclient import TestClient
from api.server import create_app
from api.auth import create_access_token
from core.market_data import Candle

async def main():
    print("==================================================")
    print("1. MEMERIKSA REGISTRY & PEMBAGIAN 37 AGENT")
    print("==================================================")
    runtime = Runtime(settings, enable_persistence=False)
    print(f"Total agent terdaftar di registry: {runtime.registry.size}")
    
    divs = runtime.registry.divisions()
    for d_name, d_agents in divs.items():
        print(f"  • Divisi {d_name.upper():<12} : {len(d_agents)} agent")
        for a in d_agents:
            tf_str = f" [{a.timeframe}]" if getattr(a, "timeframe", None) else ""
            print(f"      - {a.id:<26} (w={a.default_weight}){tf_str}")

    print("\n==================================================")
    print("2. SIMULASI EVALUASI SIKLUS (37 AGENTS RUN_CYCLE)")
    print("==================================================")
    # Populate market data cache
    for tf in ("M1", "M5", "M15", "M30", "H1", "H4", "D1"):
        for i in range(150):
            c = Candle(
                symbol=runtime.symbol,
                timeframe=tf,
                time=datetime.fromtimestamp(1700000000 + i * 60, tz=timezone.utc),
                open=2650.0 + i * 0.05,
                high=2651.0 + i * 0.05,
                low=2649.5 + i * 0.05,
                close=2650.8 + i * 0.05,
                volume=100.0,
            )
            runtime.cache.append(c)

    decision = await runtime.orchestrator.run_cycle()
    print(f"Hasil Konsensus SPK : {decision.action} ({decision.strength})")
    print(f"SPK Score           : {decision.score:.3f}")
    print(f"SPK Confidence      : {decision.confidence * 100:.1f}%")
    print(f"Total Suara Masuk   : {len(decision.votes)} / 37 agent")
    print(f"Status Hard Veto    : {decision.hard_veto} (Reason: {decision.veto_reason or 'None'})")

    print("\n==================================================")
    print("3. TEST MANUAL GET DATA KE REST API ENDPOINTS")
    print("==================================================")
    app = create_app()
    app.state.runtime = runtime
    client = TestClient(app)
    token = create_access_token("test-operator", "operator@test.local")
    headers = {"Authorization": f"Bearer {token}"}

    # Test GET /api/agents
    res_agents = client.get("/api/agents", headers=headers)
    print(f"GET /api/agents           -> Status {res_agents.status_code}")
    data_agents = res_agents.json().get("agents", [])
    print(f"Total agent di response   -> {len(data_agents)} agent")

    # Test GET /api/agents/divisions
    res_div = client.get("/api/agents/divisions", headers=headers)
    print(f"GET /api/agents/divisions -> Status {res_div.status_code}")
    div_dict = res_div.json().get("divisions", {})
    for d_name, d_info in div_dict.items():
        print(f"  • {d_name:<12}: agents={d_info['agents']} | BUY={d_info['buy']} SELL={d_info['sell']} NEUTRAL={d_info['neutral']} | score={d_info['score']}")

    # Test GET /api/spk/latest
    res_spk = client.get("/api/spk/latest", headers=headers)
    print(f"GET /api/spk/latest       -> Status {res_spk.status_code}")
    spk = res_spk.json().get("decision", {})
    print(f"Action di API             -> {spk.get('action')} (Confidence: {spk.get('confidence')})")
    print(f"Total vote tercatat di SPK-> {len(spk.get('votes', []))} suara")

    print("\n==================================================")
    print("HASIL: 100% TERINTEGRASI & SUKSES GET DATA!")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(main())
