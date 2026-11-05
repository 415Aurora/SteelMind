import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np


def test_roundoff_tolerance_is_unit_specific_and_never_masks_real_force_exceedance():
 from office_validation import compare_demands
 from office_responses import DEMAND_KEYS
 a=np.zeros((1,len(DEMAND_KEYS)));b=a.copy();a[0,DEMAND_KEYS.index('Twarp_Nmm')]=5e-10
 assert compare_demands(a,b)['status']=='PASS'
 a[0,DEMAND_KEYS.index('Mz_kNm')]=.01
 r=compare_demands(a,b);assert r['status']=='FAIL' and r['failures'][0]['component']=='Mz_kNm'
