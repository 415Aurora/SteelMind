import copy
import json
import unittest
from pathlib import Path
import steel_section_optimizer as mod


class Tests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((Path(__file__).parent/'opensees_forces_example.json').read_text())
        self.lib = mod.load_library()

    def test_geometry_and_hand_calculation(self):
        s = self.lib['H200x100x4x6']
        self.assertEqual(s.area,1952)
        self.assertAlmostEqual(s.iy,13509290.6666667)
        self.assertAlmostEqual(s.iz,1001002.6666667)
        m = copy.deepcopy(self.data['members'][0])
        m['forces'] = [dict(case='axial',station='mid',N=1952*215,My=0,Mz=0,Vy=0,Vz=0,T=0)]
        r = mod.evaluate(s,m)
        self.assertAlmostEqual(r['strength_ratio'],1)
        self.assertTrue(r['strength_pass'])
        self.assertEqual(r['pending'],[])

    def test_exhaustive_minimum_and_all_samples(self):
        out = mod.optimize(self.data,self.lib)
        m = self.data['members'][0]
        selected = self.lib[out['assignments'][m['id']]]
        for s in self.lib.values():
            if s.area < selected.area:
                self.assertFalse(mod.evaluate(s,m)['strength_pass'])
        m['forces'].append(dict(case='overload',station='mid',N=1e15,My=0,Mz=0,Vy=0,Vz=0,T=0))
        self.assertEqual(mod.optimize(self.data,self.lib)['assignments'],{})

    def test_torsion_and_invalid_input(self):
        self.data['members'][0]['forces'][0]['T']=1
        out = mod.optimize(self.data,self.lib)
        self.assertEqual(out['assignments'],{})
        self.assertTrue(out['preliminary_proposals'])
        self.data['units']='kN-m'
        with self.assertRaises(ValueError): mod.optimize(self.data,self.lib)

    def test_group(self):
        other = copy.deepcopy(self.data['members'][0])
        other['id']='noncontinuous_9001'
        other['forces'][1]['My']*=3
        self.data['members'].append(other)
        out = mod.optimize(self.data,self.lib)
        self.assertEqual(len(set(out['assignments'].values())),1)
        self.assertEqual(len(out['assignments']),2)


if __name__=='__main__': unittest.main()
