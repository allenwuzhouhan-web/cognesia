import numpy as np
import pandas as pd
import pytest

from flybrain.visual_analysis import analysis_annotations


def source():
    return pd.DataFrame({"root_id": [720575940596125868, 720575940597856265, 720575940603042272],
        "cell_type": ["R1-6", "R7", "Mi1"], "side": ["left", "right", "right"],
        "super_class": ["optic", "optic", "optic"],
        "pos_x": [100., 900., np.nan], "pos_y": [200., 200., 200.], "pos_z": [10., 20., 10.]})


def test_receptor_identity_and_anatomical_side_follow_source():
    neurons = source()
    assignments = pd.DataFrame({"neuron_index": [0, 1, 2], "root_id": neurons.root_id,
        "column_index": [7, -1, 9], "assignment_source": ["inferred", "unassigned", "source"]})
    result = analysis_annotations(neurons, assignments, [2., .8, .6], 2.)
    assert len(result["receptors"]) == 2
    assert result["receptors"][0]["root_id"] == "720575940596125868"
    assert result["receptors"][0]["column_index"] == 7
    assert result["receptors"][1]["column_index"] is None
    assert result["receptors"][1]["side"] == "right"
    sides = result["orientation"]["positions"]
    np.testing.assert_allclose(sides["left"]["normalized"], [-.8, 0., -.1])
    np.testing.assert_allclose(sides["right"]["normalized"], [.8, 0., .1])
    assert sides["right"]["annotation_count"] == 1


def test_reordered_assignment_must_not_select_another_neuron():
    n = source()
    a = pd.DataFrame({"neuron_index": [1], "root_id": [n.root_id.iloc[0]],
        "column_index": [0], "assignment_source": ["source"]})
    with pytest.raises(ValueError, match="model neuron order"):
        analysis_annotations(n, a, [0, 0, 0], 1)


def test_missing_eye_mapping_retains_all_recorded_receptor_identities():
    result = analysis_annotations(source(), None, [0, 0, 0], 1)
    assert len(result["receptors"]) == 2
    assert all(r["column_index"] is None for r in result["receptors"])
