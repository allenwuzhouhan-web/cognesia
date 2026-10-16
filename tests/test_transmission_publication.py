"""Public evidence verification, including tampering after superficial resealing.

These tests use only the small committed publication bundle, never local native
simulation data or a running worker. Rehashing tests exercise semantic checks
beyond a file checksum. No test alters the committed evidence.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("transmission_publication", ROOT / "scripts/verify_transmission_publication.py")
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)
BUNDLE = ROOT / "docs/paralimbo-transmission-v1"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def reseal(value, field):
    value[field] = v.identity({k: x for k, x in value.items() if k != field})
    return value


class PublicationVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = v.read_json(BUNDLE / "evidence/benchmark.json")["t4_protocol"]
        cls.cases, cls.obs = v.observations(BUNDLE, cls.protocol)
        cls.traces = v.verify_traces(BUNDLE)
        cls.selections, cls.multiplier = v.verify_calibration(BUNDLE, cls.protocol, cls.obs, cls.traces)

    def copied_bundle(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        target = Path(temp.name) / "bundle"
        shutil.copytree(BUNDLE, target)
        return target

    def update_public_receipt(self, folder, relative):
        """Simulate a changed file whose outer inventory was also updated."""
        path = folder / relative
        provenance = v.read_json(folder / "public-provenance.json")
        row = next(r for r in provenance["files"] if r["path"] == relative)
        row["public_sha256"] = v.sha(path.read_bytes())
        row["bytes"] = path.stat().st_size
        if row["original_path"] is not None:
            row["transformation"] = "tampered test derivative"
            row["changed_fields"] = ["test mutation"]
        write_json(folder / "public-provenance.json", provenance)

    def changed_seal(self, mutate):
        folder = self.copied_bundle()
        path = folder / "evidence/predictions/prediction-seal.json"
        seal = v.read_json(path)
        mutate(seal)
        write_json(path, reseal(seal, "prediction_seal_sha256"))
        return folder

    def check_prediction_seal(self, folder):
        return v.verify_prediction_seal(folder, "predictions", self.protocol, self.selections, self.multiplier, self.traces)

    def test_real_bundle_recomputes_both_correspondences(self):
        result = v.verify(BUNDLE)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["comparison"], "INCONCLUSIVE")
        self.assertEqual(result["biological_superiority"], "NOT_ESTABLISHED")
        for report in result["reports"].values():
            self.assertEqual(report["qualified_conditions"], {"banc": 5, "paralimbo": 9})
            self.assertTrue(all(x is None for x in report["endpoint_scores"]["banc"].values()))

    def test_changed_trace_bytes_rejected(self):
        folder = self.copied_bundle()
        target = next((folder / "evidence/predictions").glob("*.npz"))
        target.write_bytes(target.read_bytes() + b"tampering")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            v.verify(folder)

    def test_rehashed_metric_fails_independent_recomputation(self):
        folder = self.copied_bundle()
        path = folder / "evidence/scores.json"
        scores = v.read_json(path)
        scores["endpoints"]["paralimbo"]["motion_waveform_rmse"]["score"] = .01
        write_json(path, reseal(scores, "scores_sha256"))
        self.update_public_receipt(folder, "evidence/scores.json")
        with self.assertRaisesRegex(ValueError, "numeric mismatch"):
            v.verify(folder)

    def test_missing_failed_prediction_cannot_disappear_after_reseal(self):
        folder = self.changed_seal(lambda s: s["records"].remove(next(r for r in s["records"] if r["status"] == "FAILED")))
        with self.assertRaisesRegex(ValueError, "Missing or duplicate prediction"):
            self.check_prediction_seal(folder)

    def test_duplicate_failed_prediction_rejected_after_reseal(self):
        folder = self.changed_seal(lambda s: s["records"].append(deepcopy(next(r for r in s["records"] if r["status"] == "FAILED"))))
        with self.assertRaisesRegex(ValueError, "Missing or duplicate prediction"):
            self.check_prediction_seal(folder)

    def test_missing_failed_inventory_cannot_be_redefined(self):
        def mutate(seal):
            record = next(r for r in seal["records"] if r["status"] == "FAILED")
            seal["records"].remove(record)
            seal["expected_keys"].remove(record["key"])
        folder = self.changed_seal(mutate)
        with self.assertRaisesRegex(ValueError, "Missing or duplicate prediction"):
            self.check_prediction_seal(folder)

    def test_refinement_failure_cannot_be_promoted(self):
        def mutate(seal):
            next(r for r in seal["records"] if r["status"] == "FAILED")["status"] = "PREDICTED"
        folder = self.changed_seal(mutate)
        with self.assertRaisesRegex(ValueError, "Qualification failure promoted"):
            self.check_prediction_seal(folder)

    def test_altered_parameters_rejected_after_reseal(self):
        def mutate(seal):
            seal["records"][0]["parameters"]["spike_weight"] = .275
        folder = self.changed_seal(mutate)
        with self.assertRaisesRegex(ValueError, "parameters/model/input selection changed"):
            self.check_prediction_seal(folder)

    def test_shared_input_cannot_change_in_one_arm(self):
        folder = self.changed_seal(lambda s: s["records"][0].update(input_multiplier=1.))
        with self.assertRaisesRegex(ValueError, "parameters/model/input selection changed"):
            self.check_prediction_seal(folder)

    def test_refinement_receipt_is_recomputed(self):
        def mutate(seal):
            record = next(r for r in seal["records"] if r["status"] == "FAILED")
            record["qualification"]["timestep_max_abs_mv"] = 0.
        folder = self.changed_seal(mutate)
        with self.assertRaisesRegex(ValueError, "Numerical qualification.*numeric mismatch"):
            self.check_prediction_seal(folder)

    def test_native_population_receipt_cannot_claim_pruned_graph(self):
        receipt = deepcopy(self.selections["banc"]["attempts"][0]["predictions"][self.protocol["development_case_ids"][0]])
        receipt["population"] -= 1
        with self.assertRaisesRegex(ValueError, "full-population"):
            v.native_trace(receipt, self.traces)

    def test_native_projection_changed_with_updated_array_hash(self):
        folder = self.copied_bundle()
        inventory = v.read_json(folder / "trace-inventory.json")
        row = inventory["files"][0]
        path = folder / row["path"]
        arrays = v.load_arrays(path)
        arrays["observation_values_mv"] += 1.
        np.savez_compressed(path, **arrays)
        row["arrays"]["observation_values_mv"]["sha256"] = v.sha(arrays["observation_values_mv"].tobytes(order="C"))
        write_json(folder / "trace-inventory.json", inventory)
        self.update_public_receipt(folder, row["path"])
        self.update_public_receipt(folder, "trace-inventory.json")
        with self.assertRaisesRegex(ValueError, "Observation refinement.*numeric mismatch"):
            v.verify(folder)

    def test_evaluation_cannot_enter_candidate_selection(self):
        selection = deepcopy(self.selections["banc"])
        selection["attempts"][0]["case_ids"][0] = self.protocol["evaluation_case_ids"][0]
        reseal(selection, "selection_sha256")
        with self.assertRaisesRegex(ValueError, "crosses development split"):
            v.verify_selection(selection, self.protocol["development_case_ids"])

    def test_nonminimum_candidate_cannot_win(self):
        selection = deepcopy(self.selections["banc"])
        selection["selected"] = deepcopy(selection["attempts"][0])
        reseal(selection, "selection_sha256")
        with self.assertRaisesRegex(ValueError, "First minimum development selection"):
            v.verify_selection(selection, self.protocol["development_case_ids"])

    def test_failed_candidate_cannot_win(self):
        selection = deepcopy(self.selections["banc"])
        selected_index = selection["selected"]["proposal_index"]
        selection["attempts"][selected_index]["status"] = "FAILED"
        selection["selected"]["status"] = "FAILED"
        reseal(selection, "selection_sha256")
        with self.assertRaisesRegex(ValueError, "First minimum development selection"):
            v.verify_selection(selection, self.protocol["development_case_ids"])

    def test_equal_budget_cannot_be_shortened_for_one_arm(self):
        folder = self.copied_bundle()
        path = folder / "evidence/calibration-schedules.json"
        schedules = v.read_json(path)
        s = schedules["banc"]
        s["proposal_count"] = 7
        s["proposals"].pop()
        reseal(s, "schedule_sha256")
        write_json(path, schedules)
        with self.assertRaisesRegex(ValueError, "Equal eight-proposal"):
            v.verify_calibration(folder, self.protocol, self.obs, self.traces)

    def test_nondefault_first_proposal_rejected(self):
        folder = self.copied_bundle()
        path = folder / "evidence/calibration-schedules.json"
        schedules = v.read_json(path)
        schedules["banc"]["proposals"][0]["spike_weight"] = .3
        reseal(schedules["banc"], "schedule_sha256")
        write_json(path, schedules)
        with self.assertRaisesRegex(ValueError, "Defaults, bounds or cap"):
            v.verify_calibration(folder, self.protocol, self.obs, self.traces)

    def test_shared_input_objective_is_recomputed(self):
        folder = self.copied_bundle()
        path = folder / "evidence/input-selection.json"
        inputs = v.read_json(path)
        inputs["arm_results"][0]["balanced_training_mse"] = 1.
        write_json(path, inputs)
        with self.assertRaisesRegex(ValueError, "Development objective.*numeric mismatch"):
            v.verify_calibration(folder, self.protocol, self.obs, self.traces)

    def test_mean_trace_cannot_replace_selected_trial(self):
        protocol = deepcopy(self.protocol)
        cid = protocol["development_case_ids"][0]
        protocol["native_contract"]["scoring_observation"]["selected_trial_ids_by_case"][cid] = ["trial_999"]
        with self.assertRaisesRegex(ValueError, "minimum eligible trial"):
            v.observations(BUNDLE, protocol)

    def test_observation_mean_must_match_individual_trials(self):
        cid = self.protocol["development_case_ids"][0]
        arrays = v.load_arrays(BUNDLE / f"evidence/observations/development/{cid}.npz")
        arrays["observed_mv"][0] += .1
        with self.assertRaisesRegex(ValueError, "mean differs from repeats"):
            v.verify_observation_arrays(arrays, self.cases[cid])

    def test_uninventoried_evidence_rejected(self):
        folder = self.copied_bundle()
        (folder / "evidence/extra.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "Uninventoried publication"):
            v.verify(folder)

    def test_inventory_path_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsafe relative path"):
            v.safe_file(BUNDLE, "../unrelated-file")

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.json"
            path.write_text('{"score":1,"score":2}')
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                v.read_json(path)


if __name__ == "__main__":
    unittest.main()
