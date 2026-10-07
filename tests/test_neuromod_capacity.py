import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace

from flybrain.rt.capacity import mutual_information,benjamini_hochberg,information_statistics,decode_action,enumerate_handles


def test_information_known_independence_perfect_and_multiclass():
    assert mutual_information([0,0,1,1],[0,1,0,1])==pytest.approx(0)
    assert mutual_information([0,0,1,1],[0,0,1,1])==pytest.approx(1)
    assert mutual_information([0,1,2],[0,1,2])==pytest.approx(np.log2(3))
    with pytest.raises(ValueError):mutual_information([],[])
    with pytest.raises(ValueError):mutual_information([1],[1,2])


def test_bh_uses_all_handles_and_restores_order():
    np.testing.assert_allclose(benjamini_hochberg([.04,.001,.03,.9]),[.053333333333,.004,.053333333333,.9])
    with pytest.raises(ValueError):benjamini_hochberg([np.nan])


def test_zero_valence_is_explicit_neutral_and_not_fabricated_approach():
    assert [decode_action(x) for x in [-1,0,1]]==[0,2,1]
    with pytest.raises(ValueError):decode_action(np.nan)


def test_handle_identity_uses_annotation_and_retains_ta_without_inventing_driver():
    cells=np.array(['OA-AL2b2','OA-VPM3','mixed','mixed','IPC'])
    sources={name:np.zeros(5,bool) for name in ('DA','OA','5HT','TA')}
    sources['TA'][0]=True;sources['OA'][1]=True;sources['DA'][2]=True
    runtime=SimpleNamespace(cells=cells,sources=sources,
        neurons=pd.DataFrame({'super_class':['central']*4+['endocrine']}))
    table=enumerate_handles(runtime).set_index('cell_type')
    assert table.loc['OA-AL2b2','species']=='TA'
    assert table.loc['OA-AL2b2','addressable_in_runtime']
    assert table.loc['OA-VPM3','species']=='OA'
    assert not table.loc['mixed','addressable_in_runtime']
    assert table.loc['IPC','species']=='endocrine'
    assert set(table.published_driver_line)=={''}


def test_protocol_cluster_null_preserves_shared_training_memory_and_floor():
    rows=[]
    for protocol in range(2):
        for seed in range(3):
            for odor in range(2):
                target=int(protocol==odor)
                rows.append(dict(protocol=str(protocol),seed=seed,odor=str(odor),intended=target,decision=target,baseline_decision=odor))
    table=pd.DataFrame(rows)
    a=information_statistics(table,randomizations=1000,seed=19)
    b=information_statistics(table,randomizations=1000,seed=19)
    assert a==b
    assert a['mutual_information_bits']==1 and a['baseline_information_bits']==0
    # Only two trained mappings: a global assignment swap leaves MI invariant.
    # Replicated test seeds must never manufacture a significant protocol null.
    assert a['empirical_p']==1 and a['independent_training_protocols']==2
    assert a['empirical_p_floor']==1/1001
    with pytest.raises(ValueError):information_statistics(table,randomizations=999)


def test_malformed_protocol_mapping_is_rejected():
    table=pd.DataFrame({'protocol':[0,0,1,1],'odor':['A','A','A','A'],
                        'intended':[0,1,1,1],'decision':[0,0,0,0],'baseline_decision':[0,0,0,0]})
    with pytest.raises(ValueError,match='one intended action'):information_statistics(table)
