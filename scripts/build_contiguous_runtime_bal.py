"""Pull the EIP-8279 runtime-BAL meter over contiguous block ranges.

Phase 2 of the empirical block-shock workstream. Phase 1 established that the
primitive resource residuals carry integrated correlation times of roughly
10-38 blocks and cluster in the tail, so the access-composition residual

    a_t = g_BAL_observed / (w_E q_E^0 R_E^rho_A + w_S q_S)

cannot be assumed serially independent without measurement. The 6,000-block
calibration sample is spaced ~102 blocks apart and cannot resolve structure at
those lags.

This queries block-level runtime BAL over explicit contiguous ranges, sized to
resolve dependence out to a few multiples of the Phase 1 correlation times,
rather than reproducing the whole Phase 1 horizon through the expensive
structlog and trace path.

Usage:
    python3 scripts/build_contiguous_runtime_bal.py --range 25201436 25203435 --label busy
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sim.xatu_bal_8279 import query_xatu_eip8279_runtime_blocks  # noqa: E402


def client():
    import clickhouse_connect

    load_dotenv(ROOT / ".env")
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_RAW_HOST", "clickhouse-raw.xatu.ethpandaops.io"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "443")),
        username=os.environ["CLICKHOUSE_USER"],
        password=os.environ["CLICKHOUSE_PASSWORD"],
        secure=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--range", nargs=2, type=int, required=True, metavar=("LO", "HI"))
    parser.add_argument("--label", required=True, help="regime label, e.g. busy or quiet")
    parser.add_argument("--chunk-size", type=int, default=250)
    parser.add_argument("--network", default="mainnet")
    args = parser.parse_args()

    lo, hi = args.range
    targets = list(range(lo, hi + 1))
    out_dir = ROOT / "data" / "contiguous"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"contiguous_runtime_bal_{args.label}_{lo}_{hi}.csv"
    partial = out.with_suffix(".partial.csv")

    done = pd.read_csv(partial) if partial.exists() else pd.DataFrame()
    have = set(done.get("block_number", pd.Series(dtype="int64")).astype(int))
    missing = [b for b in targets if b not in have]
    print(f"{args.label}: blocks {lo}..{hi} ({len(targets):,}); {len(missing):,} to query")

    conn = client()
    pieces = [done] if len(done) else []
    t0 = time.time()
    for start in range(0, len(missing), args.chunk_size):
        chunk = missing[start : start + args.chunk_size]
        pieces.append(query_xatu_eip8279_runtime_blocks(conn, chunk, network=args.network))
        checkpoint = (
            pd.concat(pieces, ignore_index=True)
            .drop_duplicates("block_number", keep="last")
            .sort_values("block_number")
        )
        checkpoint.to_csv(partial, index=False)
        done_n = min(start + len(chunk), len(missing))
        rate = done_n / max(time.time() - t0, 1e-9)
        print(f"  {done_n:,}/{len(missing):,}  {rate:6.1f} blocks/s", flush=True)

    panel = (
        pd.concat(pieces, ignore_index=True)
        .drop_duplicates("block_number", keep="last")
        .sort_values("block_number")
        .reset_index(drop=True)
    )
    # Blocks with no metered events are genuine zeros, not gaps.
    panel = pd.DataFrame({"block_number": targets}).merge(
        panel.drop(columns=["date", "sample_rank"], errors="ignore"),
        on="block_number", how="left",
    )
    numeric = [c for c in panel.columns if c != "block_number" and panel[c].dtype != object]
    panel[numeric] = panel[numeric].fillna(0)
    panel["regime"] = args.label
    panel.to_csv(out, index=False)
    if partial.exists():
        partial.unlink()

    print(f"\nwrote {out.relative_to(ROOT)}  ({len(panel):,} blocks, {time.time() - t0:.0f}s)")
    print(f"  mean runtime BAL: {panel.bal_runtime_bytes_8279.mean():,.0f} bytes/block")
    print(f"  zero-BAL blocks : {int((panel.bal_runtime_bytes_8279 == 0).sum()):,}")


if __name__ == "__main__":
    main()
