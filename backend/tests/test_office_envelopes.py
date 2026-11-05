import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np


def test_pattern_envelope_never_drops_partial_live_load_bound():
 from office_envelopes import first_order_envelope
 from office_responses import DEMAND_KEYS
 shape=(1,len(DEMAND_KEYS));zero=np.zeros(shape)
 a={'demand_matrices':{'G':zero.copy(),'Q_OFFICE':np.ones(shape)},'master_displacements':{'G':np.zeros(3)},'drift_matrices':{'G':np.zeros((1,3))},'live_region_bounds':{'Q_OFFICE':np.ones(shape)*3},'live_region_u_bounds':{'Q_OFFICE':np.ones(3)*4},'live_region_drift_bounds':{'Q_OFFICE':np.ones((1,3))*5},'earthquake':{}}
 d,u,dr=first_order_envelope(a,{'factors':{'G':1.3,'Q_OFFICE':1.5}})
 assert np.all(d==4.5) and np.all(u==6) and np.all(dr==7.5)
