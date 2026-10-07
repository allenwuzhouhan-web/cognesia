import numpy as np
import pytest
from scipy import sparse
from flybrain.neuromod.core import prepare_core_counts


def test_kc_correction_and_recurrence_policy_do_not_mutate_base():
    base = sparse.csr_matrix([[0, -1, -4], [-3, 0, -7], [2, -5, 0]], dtype=np.float32)
    kc = np.array([True, True, False])
    before = base.toarray().copy()
    released, meta = prepare_core_counts(base, kc, "as_released")
    np.testing.assert_array_equal(released.toarray(), [[0, 1, -4], [3, 0, -7], [2, 5, 0]])
    assert meta["KC_fast_sign_corrected_edges"] == 3
    thresholded, meta = prepare_core_counts(base, kc, "thresholded")
    assert thresholded[0, 1] == 0 and thresholded[1, 0] == 3
    assert meta["removed_KC_KC_edges"] == 1
    off, meta = prepare_core_counts(base, kc, "off")
    assert off[0, 1] == 0 and off[1, 0] == 0 and off[2, 1] == 5
    np.testing.assert_array_equal(base.toarray(), before)


def test_invalid_recurrence_policy_rejected():
    with pytest.raises(ValueError, match="kc_kc_mode"):
        prepare_core_counts(sparse.eye(2), np.array([True, False]), "silence_all")
