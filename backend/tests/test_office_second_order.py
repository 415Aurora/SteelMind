import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np


def test_positive_second_order_bound_matches_single_dof_pdelta():
 from office_second_order import positive_second_order_bound
 r=positive_second_order_bound(np.array([[.1]]),[np.array([[.01]])],np.array([2.]),np.array([[0.]]),np.array([1.]))
 assert r['ok'],r
 assert math.isclose(r['displacement_abs_bound'][0],1/(1-.1*.02),rel_tol=1e-3)
 assert r['displacement_abs_bound'][0]>=1/(1-.1*.02)
 assert r['column_compression_cap_kN'][0]>=2


def test_noncontractive_second_order_is_not_a_pass():
 from office_second_order import positive_second_order_bound
 r=positive_second_order_bound(np.array([[1.]]),[np.array([[1.]])],np.array([2.]),np.array([[0.]]),np.array([1.]))
 assert not r['ok'] and r['status']=='BOUND_NOT_SATISFIED'
