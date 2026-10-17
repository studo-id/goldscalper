import asyncio
from data.db import get_session_factory
from sqlalchemy import text

async def check():
    async with get_session_factory()() as session:
        # Check decisions at trade time
        stmt = text("""
            SELECT time, agent_id, division, timeframe, vote, confidence, weight, veto, reasoning
            FROM agent_decisions
            WHERE time >= '2026-10-15 08:31:00+00' AND time <= '2026-10-15 08:33:30+00'
              AND vote != 0
            ORDER BY time ASC, vote DESC
        """)
        rows = await session.execute(stmt)
        print("=== AGENT VOTES DURING THE 3 ENTRIES ===")
        seen = set()
        for r in rows.all():
            k = (r.agent_id, r.vote, r.timeframe, r.reasoning)
            if k in seen:
                continue
            seen.add(k)
            c = r.confidence if r.confidence is not None else 0.0
            w = r.weight if r.weight is not None else 0.0
            tf = r.timeframe or "ALL"
            print(f"[{r.time}] {r.agent_id:25} | {r.division:12} | TF:{tf:4} | VOTE:{r.vote:2} | CONF:{c:.2f} | W:{w:.2f} | REASON: {r.reasoning}")

asyncio.run(check())
