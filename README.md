# RUAX-Deterministic Underwriting Engine & Fixed-Point Actuarial Risk Verification Capsule

**Author:** Michael Aaron Russell  
**ORCID:** 0009-0001-3360-6709  
**Organization:** Universal Standard Axiom Corporation (USA Corp)

---

Production-ready deterministic underwriting pipeline under U.S. Patent Application No. 19/383,582 and the Safety Asset Class framework, featuring zero-drift WAD18 arithmetic and tamper-evident audit trails.

## Architecture & Specifications

- **Deterministic Compute Engine:** Built on zero-drift $10^{18}$ fixed-point integer arithmetic (`WAD18`) to eliminate floating-point non-determinism in financial calculations.
- **CSL Hardware Gate Integration:** Pure operational verification ensuring execution safety and strict boundary validation before state commitment.
- **Tamper-Evident Ledgers:** Immutable logging (`csl_ledger.json`) capturing decision states, mutation test results, and gap analysis for full auditability.
- **Safety Asset Class (SAC) Aligned:** Native compliance with constitutional mathematics and machine-verifiable law specifications.

## Repository Layout

```text
underwriting-capsule/
├── audit/
│   └── csl_ledger.json            # Immutable audit trail ledger
├── data/
│   └── reference_applications.json # Validation application sets
├── logs/
│   ├── decisions.json            # Deterministic decision output logs
│   └── mutation.json             # Mutation testing verification logs
├── spec/
│   └── mutation_equivalents.json # Formal mutation equivalence bounds
├── src/
│   ├── csl.py                    # CSL hardware gate & layer logic
│   ├── loan_application.py       # Data structures & application schema
│   ├── mutation.py               # Mutation testing & robustness verification
│   ├── pipeline.py               # Execution pipeline coordinator
│   ├── underwriting_engine.py    # Core underwriting decision logic
│   └── wad18.py                  # WAD18 fixed-point integer math engine
└── tests/
    ├── test_all.py               # Suite-wide integration tests
    ├── test_gap_audit.py         # Boundary & gap audit verification
    └── test_survivors.py         # Mutation survivor stress tests
