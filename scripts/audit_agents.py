import asyncio
from runtime import Runtime
from agents.divisions import build_all_agents

async def audit():
    rt = Runtime()
    await rt._warmup_cache()
    st = await rt._build_state()
    agents = build_all_agents()
    print(f"TOTAL AGENTS: {len(agents)}")
    print("=" * 110)
    print(f"{'AGENT ID':<25} | {'DIVISION':<12} | {'VOTE':<4} | {'CONF':<5} | {'VETO':<10} | {'STATUS':<10} | REASONING")
    print("-" * 110)
    
    passive_count = 0
    active_count = 0
    meta_count = 0
    
    for a in agents:
        sig = await a.evaluate(st)
        
        # Categorize
        if a.division in ("spk_core", "infra"):
            status = "DIAGNOSTIC"
            meta_count += 1
        elif a.division == "risk":
            status = "RISK_PARAM"
            meta_count += 1
        elif sig.vote == 0 and (sig.confidence == 0.0 or "no " in (sig.reasoning or "").lower() or "missing" in (sig.reasoning or "").lower()):
            status = "PASIF / SLEEP"
            passive_count += 1
        else:
            status = "ACTIVE"
            active_count += 1
            
        veto_str = str(sig.veto) if sig.veto else "-"
        reason = (sig.reasoning or "")[:45]
        print(f"{a.id:<25} | {a.division:<12} | {sig.vote:>4} | {sig.confidence:>5.2f} | {veto_str:<10} | {status:<13} | {reason}")
        
    print("=" * 110)
    print(f"SUMMARY: Active={active_count}, Diagnostic/Risk={meta_count}, Truly Passive/Dormant={passive_count}")

if __name__ == "__main__":
    asyncio.run(audit())
