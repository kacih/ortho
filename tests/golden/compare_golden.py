import argparse, json, math
from pathlib import Path

def load_by_id(p: Path):
    d={}
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            r=json.loads(line)
            d[r["id"]] = r
    return d

def pearson(xs, ys):
    n=len(xs)
    mx=sum(xs)/n; my=sum(ys)/n
    vx=sum((x-mx)**2 for x in xs); vy=sum((y-my)**2 for y in ys)
    if vx <= 1e-12 or vy <= 1e-12: return 0.0
    cov=sum((xs[i]-mx)*(ys[i]-my) for i in range(n))
    return cov / math.sqrt(vx*vy)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--max_fail_rate_delta", type=float, default=0.01)  # +1%
    ap.add_argument("--mean_score_tol", type=float, default=1.0)        # +/-1 point
    ap.add_argument("--min_r", type=float, default=0.98)
    ap.add_argument("--max_abs_delta", type=float, default=5.0)
    args=ap.parse_args()

    A=load_by_id(Path(args.baseline))
    B=load_by_id(Path(args.candidate))

    ids=sorted(set(A.keys()) & set(B.keys()))
    if not ids:
        raise SystemExit("Aucun id commun baseline/candidate.")

    okA=sum(1 for i in ids if A[i]["ok"])
    okB=sum(1 for i in ids if B[i]["ok"])
    failA=1 - okA/len(ids)
    failB=1 - okB/len(ids)

    scoresA=[A[i]["final_score"] for i in ids if A[i]["ok"] and B[i]["ok"]]
    scoresB=[B[i]["final_score"] for i in ids if A[i]["ok"] and B[i]["ok"]]
    if len(scoresA) == 0:
        print("❌ Aucun item OK en commun entre baseline et candidate.")
        print("➡️ Golden inexploitable (tout échoue).")
        print("VERDICT: FAIL")
        return

    mean_delta = (sum((scoresB[i]-scoresA[i]) for i in range(len(scoresA))) / max(1,len(scoresA))) if scoresA else 0.0
    max_abs = max((abs(scoresB[i]-scoresA[i]) for i in range(len(scoresA))), default=0.0)
    r = pearson(scoresA, scoresB) if len(scoresA) >= 10 else 0.0

    pass_fail = True
    if (failB - failA) > args.max_fail_rate_delta: pass_fail=False
    if not (-args.mean_score_tol <= mean_delta <= args.mean_score_tol): pass_fail=False
    if len(scoresA) >= 20 and r < args.min_r: pass_fail=False
    if max_abs > args.max_abs_delta: pass_fail=False

    print(f"Items communs: {len(ids)}")
    print(f"Fail rate A: {failA:.3%} | B: {failB:.3%} | Δ: {(failB-failA):.3%}")
    print(f"Δmoyenne score: {mean_delta:.3f} | max|Δ|: {max_abs:.3f} | r: {r:.4f}")
    print("VERDICT:", "PASS" if pass_fail else "FAIL")

    # Top 10 dérives
    deltas=[]
    for i in ids:
        if A[i]["ok"] and B[i]["ok"]:
            deltas.append((abs(B[i]["final_score"]-A[i]["final_score"]), i))
    deltas.sort(reverse=True)
    print("\nTop 10 |Δscore|:")
    for d,i in deltas[:10]:
        print(f"- {i}: |Δ|={d:.3f}  A={A[i]['final_score']:.2f}  B={B[i]['final_score']:.2f}")

if __name__=="__main__":
    main()
