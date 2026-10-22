"""Load generator — steady, varied, reproducible traffic (note 06).

Poisson arrivals at --rate requests/s (queueing-theory nod), random users / items / qty.
Rare-but-normal paths (declined cards, out of stock, one retry, auth rejects) come from
the services themselves, so the model learns they are normal.

    python scripts/load.py --rate 20 --duration 600 --seed 42
"""
import argparse
import asyncio
import random
import time

import httpx

ITEMS = ["pen", "book", "mug", "lamp"]


async def main(url: str, rate: float, duration: float, seed: int):
    rng = random.Random(seed)
    stats = {"sent": 0, "ok": 0, "err": 0}
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    async with httpx.AsyncClient(timeout=15, limits=limits) as client:
        async def one(body):
            try:
                r = await client.post(f"{url}/checkout", json=body)
                stats["ok" if r.status_code < 300 else "err"] += 1
            except httpx.HTTPError:
                stats["err"] += 1

        t0 = time.time()
        last = t0
        tasks = set()
        while duration <= 0 or time.time() - t0 < duration:
            body = {"user": rng.randint(1, 500), "item": rng.choice(ITEMS), "qty": rng.randint(1, 3)}
            t = asyncio.create_task(one(body))
            tasks.add(t)
            t.add_done_callback(tasks.discard)
            stats["sent"] += 1
            await asyncio.sleep(rng.expovariate(rate))
            if time.time() - last > 30:
                last = time.time()
                print(f"[load] {time.time() - t0:.0f}s sent={stats['sent']} ok={stats['ok']} non2xx/err={stats['err']}",
                      flush=True)
        await asyncio.gather(*tasks, return_exceptions=True)
    print("[load] done", stats, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--rate", type=float, default=20)
    ap.add_argument("--duration", type=float, default=0, help="seconds; 0 = forever")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    asyncio.run(main(a.url, a.rate, a.duration, a.seed))
