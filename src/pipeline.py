"""Underwriting Capsule Pipeline."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from loan_application    import LoanApplication
from underwriting_engine import underwrite
from csl                 import CSL
import wad18 as W

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA   = os.path.join(ROOT, "data", "reference_applications.json")
LEDGER = os.path.join(ROOT, "audit", "csl_ledger.json")
LOGS   = os.path.join(ROOT, "logs")


def run():
    os.makedirs(LOGS, exist_ok=True)
    csl = CSL(LEDGER)

    csl.append({
        "capsule":    "underwriting-capsule", "version": "1.0.0",
        "algorithm":  "Three-tier DTI/LTV/Score rule engine",
        "tiers":      {"PRIME": "score≥720,DTI≤36%,LTV≤80%,emp≥24m",
                       "STANDARD": "score≥680,DTI≤43%,LTV≤95%,emp≥24m",
                       "FHA_GRADE": "score≥620,DTI≤50%,LTV≤96.5%,emp≥12m"},
        "arithmetic": "WAD-18 exact integer",
        "network":    "DISABLED",
    }, label="GENESIS")

    raw     = json.load(open(DATA))
    results = []

    for ad in raw["applications"]:
        app    = LoanApplication.from_dict(ad)
        result = underwrite(app)
        label  = ad.get("label", app.application_id)
        exp_d  = ad.get("expected_decision")
        exp_t  = ad.get("expected_tier")
        pass_d = result["decision"] == exp_d
        pass_t = result["tier"]     == exp_t

        csl.append({
            "application_id":  result["application_id"],
            "label":           label,
            "decision":        result["decision"],
            "tier":            result["tier"],
            "ltv_pct":         result["ltv_pct"],
            "dti_back_pct":    result["dti_back_pct"],
            "credit_score":    result["credit_score"],
            "conditions":      result["conditions"],
            "pass_decision":   pass_d,
            "pass_tier":       pass_t,
        }, label=label)

        result["expected_decision"] = exp_d
        result["expected_tier"]     = exp_t
        result["pass_decision"]     = pass_d
        result["pass_tier"]         = pass_t
        results.append(result)

        status = "✓" if (pass_d and pass_t) else "✗"
        print(f"  {status} [{label}]  {result['decision']:<26} "
              f"LTV={result['ltv_pct']}%  DTI={result['dti_back_pct']}%  "
              f"score={result['credit_score']}")

    all_pass = all(r["pass_decision"] and r["pass_tier"] for r in results)
    csl.append({"all_pass": all_pass, "H_final": csl.root_hash(),
                "n_decisions": len(results)}, label="FINALIZATION")

    json.dump({"results": results, "all_pass": all_pass},
              open(os.path.join(LOGS, "decisions.json"), "w"),
              indent=2, sort_keys=True)

    print(f"\n{'='*55}")
    print(f"  All pass: {all_pass}  |  H_final: {csl.root_hash()[:24]}...")
    print(f"{'='*55}")
    return results


if __name__ == "__main__":
    run()
