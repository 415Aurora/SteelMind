"""Closed-form benchmark independently checks physical units and section conventions."""
import pytest
from steelmind_export.examples import analytic_bundle
from steelmind_export.units import mm_to_m, m_to_mm, N_to_kN, Nmm_to_kNm


def test_units():
    assert mm_to_m(1250)==1.25
    assert m_to_mm(1.25)==1250
    assert N_to_kN(12345)==12.345
    assert Nmm_to_kNm(45000000)==45


def test_simply_supported_closed_form():
    b=analytic_bundle(); s=b['model']['sections'][0]
    # Independent rectangle decomposition for H300x200x8x12, no fillets.
    assert s['A_mm2']==7008
    assert s['Ix_mm4']==113606784
    assert s['Iy_mm4']==16011776
    assert s['Wx_mm3']==pytest.approx(757378.56)
    a=b['analysis']; forces=a['member_end_forces'][0]
    assert forces['Vi_kN']==30 and forces['Vj_kN']==30
    assert forces['Mi_kNm']==forces['Mj_kNm']==0
    samples=a['member_samples']; mid=next(p for p in samples if p['x_m']==3)
    assert mid['M_kNm']==45 and mid['V_kN']==0
    for p in samples:
        x=p['x_m']
        assert p['M_kNm']==pytest.approx(10*x*(6-x)/2)
        assert p['V_kN']==pytest.approx(10*(3-x))
    # Downward deflection, 10 kN/m = 10 N/mm, 6 m = 6000 mm.
    expected=5*10*6000**4/(384*206000*113606784)
    deflection=next(t for t in b['traces'] if t['id']=='T_DEFLECTION')
    assert deflection['result']==pytest.approx(expected)
    # End actions convert to interior section signs without flipping sagging moment.
    assert samples[0]['N_kN']==-forces['Ni_kN']
    assert samples[0]['V_kN']==forces['Vi_kN']
    assert samples[0]['M_kNm']==-forces['Mi_kNm']
    assert samples[-1]['N_kN']==forces['Nj_kN']
    assert samples[-1]['V_kN']==-forces['Vj_kN']
    assert samples[-1]['M_kNm']==forces['Mj_kNm']
