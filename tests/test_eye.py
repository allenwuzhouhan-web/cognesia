import numpy as np
import pandas as pd
import pytest
from scipy import sparse
from flybrain.eye import (build_eye_mapping, column_directions, optical_quadrature,
                          Phototransduction, _strongest_column)


def test_export_conflicts_and_tied_anatomical_columns_stay_unresolved(tmp_path):
    neurons = pd.DataFrame({'root_id':range(10,18),'cell_type':['Mi1','Mi1','L1','L1','R1-6','R1-6','Mi1','R1-6'],
                            'side':['right']*8})
    export = pd.DataFrame({'root_id':[10,11,12,13,16], 'type':['Mi1','Mi1','L1','L1','C2'],
                           'hemisphere':['right']*5,'column_id':[1,2,1,2,1],
                           'p':[0,1,0,1,0],'q':[0,0,0,0,0],'x':[0]*5,'y':[0]*5})
    dest=tmp_path/'data/raw/codex';dest.mkdir(parents=True);export.to_csv(dest/'column_assignment.csv',index=False)
    # R4 has clear winning L1; R5 equally targets distinct columns; R7 has no outputs.
    counts=sparse.csr_matrix(([5,5,20,2,10,10],([0,1,2,3,2,3],[2,3,4,4,5,5])),shape=(8,8))
    mapping=build_eye_mapping(tmp_path,neurons,counts,persist=False)
    assert mapping.audit['anchors']==2
    assert mapping.photoreceptor_indices.tolist()==[4]
    assert mapping.photoreceptor_columns.tolist()==[0]
    assert mapping.assignments.iloc[6].assignment_source=='excluded_source_conflict'
    assert mapping.audit['photoreceptors_unassigned']==2
    assert mapping.audit['unresolved_mi1_root_ids']==['16']


def test_optical_gaussian_preserves_uniform_luminance_and_spherical_unit_rays():
    columns=pd.DataFrame({'hemisphere':['right']*3+['left']*3,'p':[0,1,0]*2,'q':[0,0,1]*2})
    columns=column_directions(columns)
    az,el,weights=optical_quadrature(columns)
    assert az.shape==(6,25)
    assert np.isfinite(az).all() and np.isfinite(el).all()
    assert weights.sum()==pytest.approx(1.)
    np.testing.assert_allclose(np.full(az.shape,.37)@weights,.37)
    assert columns.iloc[:3].azimuth_deg.mean()>0
    assert columns.iloc[3:].azimuth_deg.mean()<0


def test_optical_gaussian_at_center_attenuates_fine_grating():
    columns=pd.DataFrame({'azimuth_deg':[0.],'elevation_deg':[0.]})
    az,el,weights=optical_quadrature(columns,order=9)
    period=20
    observed=(np.cos(2*np.pi*az/period)@weights)[0]
    sigma=5.7/(2*np.sqrt(2*np.log(2)))
    expected=np.exp(-.5*(2*np.pi*sigma/period)**2)
    assert observed==pytest.approx(expected,abs=.001)


def test_phototransduction_passive_time_course_and_adaptation():
    params={'maximum_drive_mv':20.,'half_saturation':.2,'adaptation_strength':.5,
            'adaptation_tau_ms':200.,'phototransduction_tau_ms':12.}
    eye=Phototransduction(2,params)
    np.testing.assert_array_equal(eye.step([0,0],4),[0,0])
    first=eye.step([1,0],4)
    assert 0<first[0]<20 and first[1]==0
    responses=[eye.step([1,0],4)[0] for _ in range(250)]
    assert max(responses)>responses[-1]
    assert responses[-1]==pytest.approx(20/1.7,rel=.01)
    with pytest.raises(ValueError):eye.step([np.nan,0],4)


def test_dense_gaussian_rays_resolve_discontinuous_edge_and_small_disk():
    from scipy.special import ndtr
    from flybrain.eye import gaussian_ray_samples
    columns=pd.DataFrame({'azimuth_deg':np.linspace(-5,5,41),'elevation_deg':np.zeros(41)})
    az,el=gaussian_ray_samples(columns)
    fine_az,fine_el=gaussian_ray_samples(columns,sample_count=16384)
    sigma=5.7/(2*np.sqrt(2*np.log(2)))
    step=(az<=0).mean(axis=1)
    np.testing.assert_allclose(step,ndtr(-columns.azimuth_deg.to_numpy()/sigma),atol=.004)
    disk=(np.hypot(az,el)<=2.295).mean(axis=1)
    fine_disk=(np.hypot(fine_az,fine_el)<=2.295).mean(axis=1)
    assert np.max(np.abs(disk-fine_disk))<.005
    center_probability=1-np.exp(-2.295**2/(2*sigma**2))
    assert disk[20]==pytest.approx(center_probability,abs=.005)
    az2,el2=gaussian_ray_samples(columns)
    np.testing.assert_array_equal(az,az2)
    np.testing.assert_array_equal(el,el2)
