#!/usr/bin/env python3
"""Resume los resultados de las baterías de pruebas en una tabla.

Lee los JSON de validation/sweep/ y validation/campaign/ y produce una tabla
comparativa contra las referencias de Ladson (NASA TM 4074).

Uso:
    python3 validation/summarize.py
    python3 validation/summarize.py --csv resultados.csv
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.join(HERE, "sweep")
CAMPAIGN = os.path.join(HERE, "campaign")

REF = {0.0: (-0.0121, 0.00807), 4.0: (0.4272, 0.00823),
       8.0: (0.8615, 0.00989), 10.0: (1.0669, 0.01168),
       12.0: (1.2284, 0.01651)}


def fmt(v, w=8, p=4):
    if v is None:
        return " " * w
    try:
        return f"{v:>{w}.{p}f}"
    except (TypeError, ValueError):
        return " " * w


def collect() -> list:
    rows = []

    for path in sorted(glob.glob(os.path.join(SWEEP, "*.json"))):
        try:
            d = json.load(open(path))
        except Exception:
            continue
        for r in d.get("results", []):
            c = r.get("coeffs") or {}
            cl = c.get("cl")
            cd = c.get("cd")
            aoa = r.get("aoa")
            if cl is not None and abs(cl) > 100:
                cl = None
            if cd is not None and abs(cd) > 10:
                cd = None
            ref = REF.get(aoa)
            rows.append({
                "fuente": os.path.basename(path).replace(".json", ""),
                "caso": r.get("test", "?"),
                "aoa": aoa,
                "esquema": r.get("scheme", "—"),
                "cl": cl, "cd": cd,
                "cl_ref": ref[0] if ref else None,
                "cd_ref": ref[1] if ref else None,
                "cl_err": ((cl - ref[0]) / abs(ref[0]) * 100
                           if cl is not None and ref and abs(ref[0]) > 0.05 else None),
                "cd_err": ((cd - ref[1]) / ref[1] * 100
                           if cd is not None and ref else None),
                "iters": r.get("iters"),
                "ok": r.get("ok", False),
                "nota": r.get("error", ""),
            })

    for path in sorted(glob.glob(os.path.join(CAMPAIGN, "*", "results.json"))):
        try:
            d = json.load(open(path))
        except Exception:
            continue
        for r in d.get("results", []):
            if not r.get("ok"):
                continue
            rows.append({
                "fuente": "campaign",
                "caso": d.get("case", "?"),
                "aoa": r.get("aoa"),
                "esquema": "linearUpwind",
                "cl": r.get("cl"), "cd": r.get("cd"),
                "cl_ref": r.get("cl_ref"), "cd_ref": r.get("cd_ref"),
                "cl_err": r.get("dcl_pct"), "cd_err": r.get("dcd_pct"),
                "iters": None, "ok": True, "nota": "",
            })
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    args = ap.parse_args(argv)

    rows = collect()
    if not rows:
        print("Sin resultados todavía.")
        return 1

    hdr = (f"{'fuente':<18} {'caso':<28} {'α':>5} {'esquema':<16} "
           f"{'Cl':>9} {'ref':>8} {'err%':>7} {'Cd':>9} {'ref':>9} {'err%':>7}")
    print(hdr)
    print("-" * len(hdr))

    for r in rows:
        print(f"{r['fuente']:<18} {r['caso']:<28} "
              f"{fmt(r['aoa'], 5, 0)} {r['esquema']:<16} "
              f"{fmt(r['cl'])} {fmt(r['cl_ref'], 8)} {fmt(r['cl_err'], 7, 1)} "
              f"{fmt(r['cd'], 9, 5)} {fmt(r['cd_ref'], 9, 5)} "
              f"{fmt(r['cd_err'], 7, 1)}"
              + (f"  ← {r['nota']}" if r["nota"] else ""))

    # Estadísticas
    good = [r for r in rows if r["cd_err"] is not None and r["cd"] is not None]
    if good:
        import statistics as st
        cds = [abs(r["cd_err"]) for r in good]
        print(f"\n{len(good)} casos con Cd comparable")
        print(f"  error medio |Cd|: {st.mean(cds):.1f}%")
        print(f"  error máximo  |Cd|: {max(cds):.1f}%")
        cls = [abs(r["cl_err"]) for r in good if r["cl_err"] is not None]
        if cls:
            print(f"  error medio |Cl|: {st.mean(cls):.1f}%")
            print(f"  error máximo  |Cl|: {max(cls):.1f}%")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
