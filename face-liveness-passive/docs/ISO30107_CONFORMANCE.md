# ISO/IEC 30107 – conformance assessment of the passive liveness module

This document checks the module against the parts of the ISO/IEC 30107 series that apply to
a software **PAD subsystem** (presentation attack detection). It records what is
implemented, where it is implemented, and what an evaluator still has to provide.

> **Source caveat.** This assessment uses the publicly documented content of ISO/IEC 30107-1
> (framework), -2 (data formats), -3 (testing and reporting; 2017 edition, revised 2023) and
> -4 (mobile profile). The normative texts are paywalled and were not available while this was
> written. Check every row against your licensed copy before quoting it as a conformance claim.

Status legend:
- **Met** – implemented and covered by tests.
- **Partial** – implemented with stated limits.
- **Evaluator** – cannot be met by code; the test organisation must supply it.
- **N/A** – not applicable to a PAD-only subsystem.

## Summary

| Area | Status |
|---|---|
| Terminology and PAD-subsystem model (30107-1) | Met |
| PAI types covered | Partial: 2D artefacts (print, screen replay). Masks are only covered through the model's generic "spoof" class |
| Output of a PAD decision plus a score | Met |
| Interchange-format PAD data block (30107-2 / 39794-5) | Partial: structured JSON / protobuf record, no binary encoder |
| Metrics for PAD-subsystem evaluation (30107-3) | Met: APCER per PAI species, worst-case APCER, BPCER, APNRR, BPNRR, BPCER@APCER, DET |
| Statistical reporting (confidence, sample size) | Met: Wilson 95 % CI, rule of 3, rule-of-30 warnings |
| Test-set composition, attack-potential rating, test crew | Evaluator |
| System-level metrics (IAPMR, FNMR with PAD) | N/A: needs a biometric comparator |
| **Measured performance on real PAD data** | **Not yet done: no licensed PAD dataset was available** |

## ISO/IEC 30107-1 – framework

| Requirement / concept | Implementation | Status |
|---|---|---|
| Distinguish *bona fide* presentations from *attack* presentations | `Decision.BONAFIDE / ATTACK`; `bonafide_probability` is the PAD score (higher means more bona fide) | Met |
| A PAD subsystem may fail to decide | `Decision.NON_RESPONSE` with `NonResponseReason` (no face, multiple faces, quality, too few frames, decode error). These cases are never counted as attack or bona fide decisions | Met |
| PAI (presentation attack instrument) and PAI species | `PAISpecies` (print, screen replay, unspecified). The species is a *heuristic suggestion* (`cues.py`) and is labelled as such in every output | Partial |
| Artefact PAIs: print, display/replay, masks | Print and replay: FSFM FAS model (trained on MSU-MFSD, CASIA-FASD, Idiap Replay-Attack, OULU-NPU), plus cues. Masks: only through the Unified model's generic "spoof" class. CASIA-FASD's cut-photo attacks are the only partial-mask data in training | Partial |
| Human-based PAIs (lifeless, altered, non-conformant, coerced, conformant) | Non-conformant capture is handled by the quality gate. The rest is out of scope for passive image analysis; the active challenges (hybrid mode) address non-cooperative and static presentations | Partial |
| Level of supervision | The resident, operator and supervisor workflows each have their own policy: passive accept/reject thresholds, active enablement, challenge count, pool, timeouts and retries (`SessionPolicy`, set from the Registration Client's global parameters per workflow) | Met |
| Digital injection (deepfake / AI-generated face fed as video) | Reported as `attack_category = deepfake / synthetic` by the Unified model. Strictly this is *injection-attack* detection (see CEN/TS 18099), not PAD, so it is reported separately and not as a PAI species | Partial (out of 30107 scope) |

## ISO/IEC 30107-2 – data formats

| Requirement / concept | Implementation | Status |
|---|---|---|
| Convey a PAD decision and a PAD score with the biometric sample | `FrameAnalysis` / `StreamResult` JSON, and the `FrameAnalysis` / `StreamResult` protobuf messages. Both carry the decision, the score in [0, 1], thresholds, quality and model provenance (file name and SHA-256) | Partial |
| Standard binary encoding (PAD data block in ISO/IEC 39794-5 / 19794) | Not implemented. The MOSIP integration layer must map `decision` and `bonafide_probability` into its record format. That mapping is straightforward but needs the target schema | Not met |
| No biometric data in logs | Audit log entries (`passive_liveness.audit`) hold the decision, score, category and species only. They never include pixels, landmarks or embeddings | Met |

## ISO/IEC 30107-3 – testing and reporting

The evaluation tool `passive-liveness-eval` (`src/passive_liveness/evaluate.py`, with the metrics
in `iso30107.py`) produces `metrics.json`, `report.md`, `scores.csv`, `det.csv` and `det.png`.
`tests/test_08_iso30107.py` checks every formula against hand-computed values.

| Requirement / concept | Implementation | Status |
|---|---|---|
| **APCER** computed per PAI species | `apcer_per_species`: attacks of that species classified as bona fide, divided by that species' attacks that received a decision | Met |
| Report the **worst-case APCER** over species (per attack-potential level) | `apcer_max` (with the species named). `apcer_per_attack_potential` when the manifest supplies an `attack_potential` column | Met |
| **BPCER** | `bpcer`, over bona fide presentations that received a decision | Met |
| Non-response reported separately (**APNRR / BPNRR**) | `non_response.apnrr`, `bpnrr`, plus per-species APNRR | Met |
| Fixed-APCER operating points (**BPCER10 / BPCER20 / BPCER100**) | `bpcer_at_apcer`, using the worst-case APCER | Met |
| DET curve | `det.csv` (threshold sweep) and `det.png` | Met |
| Do not summarise with a single combined error rate | ACER is shown only as "academic summary, not ISO/IEC 30107-3". EER and AUC are labelled informative | Met |
| Results at the operating threshold(s) actually deployed | Reported at both configured thresholds (`reject_threshold`, `accept_threshold`) plus any `--threshold` value | Met |
| Confidence / uncertainty of the error rates | Wilson 95 % interval on every rate. Rule-of-3 upper bound when there are zero errors. Warnings when a species has fewer than 30 presentations (ISO/IEC 19795-1 "rule of 30") | Met |
| Describe the PAI species, how they were made, and their attack potential | Manifest column `attack_potential`. Describing how the artefacts were made is the evaluator's job (see ISO/IEC 19989-3 for rating attack potential) | Evaluator |
| Test crew size and demographics, capture devices, environment, presentation protocol | Must be documented by the evaluator. Not derivable from code | Evaluator |
| Disjoint training and test data | The FSFM checkpoints were trained on public datasets (MCIO and the Unified-detector corpus). Any evaluation must use data not in those sets. Capture your own data on your MOSIP devices | Evaluator |
| IAPMR and other system-level metrics | Need a biometric comparator and enrolment, which a PAD-only module doesn't have | N/A |

### How to run a conformant evaluation

1. Collect labelled presentations on the **target capture devices**:
   - bona fide presentations from a documented test crew;
   - one folder per PAI species, e.g. `print_glossy/`, `print_matte/`, `phone_replay/`, `tablet_replay/`, `paper_mask/`, `silicone_mask/`.
2. Optionally write a manifest with `path,label,attack_potential`.
3. Run `passive-liveness-eval DATASET --out reports/<run>`, or `--manifest data.csv`.
4. Pick thresholds from `det.csv` to meet your APCER/BPCER targets (for example BPCER20). Set
   `decision.accept_threshold` / `reject_threshold` in `config/default.yaml`, then re-run so the
   report covers the deployed operating points.
5. Add the evaluator-supplied items above (crew, devices, environment, PAI creation and attack
   potential) to the report.

## Example run (pipeline demonstration only)

`docs/example-evaluation/` holds a report produced with the **real FSFM models**. The data is the
only data available offline: 4 bona fide images (two public sample portraits and their mirror
images) and 4 + 4 *synthetic* print and screen-replay renderings of them (`tests/synth.py`).
**These numbers are not a performance claim.** The samples are far too few, and the attacks are
digital imitations, not physical artefacts. The run shows that:

- **Reject threshold 0.40:** passive alone *rejects* none of the synthetic attacks (APCER 100 %).
  They score 0.49–0.77, which is "uncertain".
- **Accept threshold 0.80:** passive alone *accepts* none of them either (APCER 0 %, BPCER 0 %).
  In the hybrid flow every one of them is therefore sent to active challenges. That is the
  purpose of the two-threshold design.
- The heuristic species suggestion matched 7 of the 8 attacks. One screen render was a
  non-response: no face was found through the simulated pixel grid.
