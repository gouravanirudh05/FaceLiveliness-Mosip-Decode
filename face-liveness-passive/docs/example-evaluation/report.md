# Passive liveness - ISO/IEC 30107-3 evaluation report

## Target of evaluation

- **date**: 2026-10-01 08:49:58
- **decision rule**: attack if fused bona fide probability < threshold
- **accept / reject thresholds**: 0.8 / 0.4
- **quality gate enforced**: True
- **models**: unified (fsfm_unified_4class_vitb16.pth, weight 0.5), fas (fsfm_fas_mcio_vitb16.pth, weight 0.5)
- **dataset**: synthetic-demo

## Test set

- Bona fide presentations: 4
- Attack presentations: 8
  - PAI species `print`: 4
  - PAI species `screen_replay`: 4

## Non-response (failure to process)

- APNRR: 12.50 % (1/8, 95 % CI 2.24-47.09 %)
- BPNRR: 0.00 % (0/4, 95 % CI 0.00-48.99 %, rule-of-3 <= 75.00 %)
  - APNRR `print`: 0.00 % (0/4, 95 % CI 0.00-48.99 %, rule-of-3 <= 75.00 %)
  - APNRR `screen_replay`: 25.00 % (1/4, 95 % CI 4.56-69.94 %)

## Operating point `reject_threshold` (attack if score < 0.4000)

| Metric | Value |
|---|---|
| APCER `print` | 100.00 % (4/4, 95 % CI 51.01-100.00 %) |
| APCER `screen_replay` | 100.00 % (3/3, 95 % CI 43.85-100.00 %) |
| **APCER (max over species: `print`)** | 100.00 % (4/4, 95 % CI 51.01-100.00 %) |
| APCER pooled (informative) | 100.00 % (7/7, 95 % CI 64.57-100.00 %) |
| **BPCER** | 0.00 % (0/4, 95 % CI 0.00-48.99 %, rule-of-3 <= 75.00 %) |
| ACER (academic summary, not ISO/IEC 30107-3) | 50.00 % |

## Operating point `accept_threshold` (attack if score < 0.8000)

| Metric | Value |
|---|---|
| APCER `print` | 0.00 % (0/4, 95 % CI 0.00-48.99 %, rule-of-3 <= 75.00 %) |
| APCER `screen_replay` | 0.00 % (0/3, 95 % CI 0.00-56.15 %, rule-of-3 <= 100.00 %) |
| **APCER (max over species: `print`)** | 0.00 % (0/4, 95 % CI 0.00-48.99 %, rule-of-3 <= 75.00 %) |
| APCER pooled (informative) | 0.00 % (0/7, 95 % CI 0.00-35.43 %, rule-of-3 <= 42.86 %) |
| **BPCER** | 0.00 % (0/4, 95 % CI 0.00-48.99 %, rule-of-3 <= 75.00 %) |
| ACER (academic summary, not ISO/IEC 30107-3) | 0.00 % |

## Threshold-independent summaries

| Metric | Value | Threshold |
|---|---|---|
| BPCER10 | 0.00 % | 0.8379 |
| BPCER20 | 0.00 % | 0.8379 |
| BPCER100 | 0.00 % | 0.8379 |
| EER (pooled attacks) | 0.00 % | 0.8379 |
| AUC | 1.0000 | |

## Heuristic PAI-species suggestion vs ground truth (attacks only)

Counts of `suspected_pai_species` per true species. These suggestions come from hand-crafted
cues, not from the models.

- `print`: print=4
- `screen_replay`: none=1, screen_replay=3

## Notes

- PAI species 'print' has only 4 presentations; its APCER confidence interval is wide (ISO/IEC 19795-1 'rule of 30' needs >= 30 errors for +/-30 % at 90 % confidence).
- PAI species 'screen_replay' has only 4 presentations; its APCER confidence interval is wide (ISO/IEC 19795-1 'rule of 30' needs >= 30 errors for +/-30 % at 90 % confidence).
- only 4 bona fide presentations; BPCER is poorly estimated.

## Not covered by this report

- IAPMR / impostor attack presentation match rate: requires a biometric comparator (out of scope for a PAD-only subsystem).
- Attack potential rating of each PAI species (see ISO/IEC 30107-3 and ISO/IEC 19989-3): supply `attack_potential` in the manifest.
- Test-crew demographics, capture devices and environment must be documented by the evaluator.
