"""Offline Q235 section checking and discrete section selection. Python 3.10+, stdlib only."""
import argparse
import csv
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / '焊接对称工字型截面_Q235_筛选保留.csv'
E_MPA = 206000.0
POISSON = 0.3
DENSITY_KG_M3 = 7850.0
TARGET_UTILIZATION = 1.0
# All interfaces use N, mm, N*mm, MPa. Local y = flange width, z = section height.
# This module never calls OpenSees. Reanalyse after applying every proposed assignment.


def number(value):
    x = float(value)
    if not math.isfinite(x):
        raise ValueError('Non-finite input')
    return x


def q235_strength(t):
    if 0 < t <= 16:
        return 215.0, 125.0
    if t <= 40 and t > 0:
        return 205.0, 120.0
    if t <= 100 and t > 0:
        return 200.0, 115.0
    raise ValueError('Q235 thickness outside supported range (0,100] mm')


@dataclass(frozen=True)
class Section:
    name: str
    h: float
    b: float
    tw: float
    tf: float

    def __post_init__(self):
        if not all(math.isfinite(v) and v > 0 for v in (self.h,self.b,self.tw,self.tf)):
            raise ValueError('Invalid section dimensions')
        if self.h <= 2*self.tf or self.b <= self.tw:
            raise ValueError('Invalid I-section geometry')

    @property
    def h0(self): return self.h-2*self.tf
    @property
    def area(self): return 2*self.b*self.tf+self.h0*self.tw
    @property
    def iy(self): return (self.b*self.h**3-(self.b-self.tw)*self.h0**3)/12
    @property
    def iz(self): return (2*self.tf*self.b**3+self.h0*self.tw**3)/12
    @property
    def wy(self): return self.iy/(self.h/2)
    @property
    def wz(self): return self.iz/(self.b/2)

    def export(self):
        # J is thin-wall approximation, not an exact torsion/warping stiffness.
        return dict(asdict(self), A_mm2=self.area, Iy_mm4=self.iy, Iz_mm4=self.iz,
                    J_approx_mm4=(2*self.b*self.tf**3+self.h0*self.tw**3)/3,
                    E_MPa=E_MPA, G_MPa=E_MPA/(2*(1+POISSON)),
                    mass_kg_per_m=self.area*1e-6*DENSITY_KG_M3)


def load_library(path=LIBRARY):
    raw = Path(path).read_bytes()
    try: text = raw.decode('utf-8-sig')
    except UnicodeDecodeError: text = raw.decode('gb18030')
    sections = {}
    for r in csv.DictReader(text.splitlines()):
        s = Section(r['截面名称'], *(number(r[k]) for k in ('b2','b3','t2','t3')))
        if s.name in sections: raise ValueError('Duplicate section '+s.name)
        if (s.b-s.tw)/(2*s.tf) > 15+1e-9:
            raise ValueError('Library contains section exceeding Q235 S4 flange limit')
        sections[s.name] = s
    if not sections: raise ValueError('Empty library')
    return sections


def validate(data, library):
    if data.get('units') != 'N-mm-MPa': raise ValueError('units must be N-mm-MPa')
    if data.get('axes') != 'y=flange_width,z=section_height':
        raise ValueError('Explicit local-axis convention required')
    members = data.get('members', [])
    if not members: raise ValueError('No members')
    ids = set()
    for m in members:
        if not isinstance(m['id'], str) or m['id'] in ids: raise ValueError('Member IDs must be unique strings')
        ids.add(m['id'])
        if not str(m.get('current_section', '')).strip(): raise ValueError('Missing current section')
        if number(m['length_mm']) <= 0: raise ValueError('Invalid physical member length')
        if not m.get('forces'): raise ValueError('No force samples for '+m['id'])
        for f in m['forces']:
            if not str(f.get('case','')).strip() or not str(f.get('station','')).strip():
                raise ValueError('Each force sample needs case and station')
            for k in ('N','My','Mz','Vy','Vz','T'): number(f[k])


def evaluate(section, member):
    s = section
    # Use thickest plate strength for all stress terms, conservatively.
    f, fv = q235_strength(max(s.tf,s.tw))
    ratios = []
    governing = ''
    peak = -1
    for sample in member['forces']:
        N,My,Mz,Vy,Vz,T = (number(sample[k]) for k in ('N','My','Mz','Vy','Vz','T'))
        sigma = abs(N)/s.area+abs(My)/s.wy+abs(Mz)/s.wz
        q_strong = s.b*s.tf*(s.h-s.tf)/2+s.tw*s.h0**2/8
        q_weak = s.tf*s.b**2/4+s.h0*s.tw**2/8
        tau_strong = abs(Vz)*q_strong/(s.iy*s.tw)
        tau_weak = abs(Vy)*q_weak/(s.iz*2*s.tf)
        # Sum of component maxima is a conservative screening bound.
        tau = tau_strong+tau_weak
        eq = math.sqrt(sigma**2+3*tau**2)/f
        ratio = max(sigma/f,tau/fv,eq)
        ratios.append(ratio)
        if ratio > peak:
            peak = ratio
            governing = str(sample['case'])+'@'+str(sample['station'])
    flange_ratio = (s.b-s.tw)/(2*s.tf)/15
    web_ratio = s.h0/s.tw/80
    pending = []
    if any(abs(number(r['T'])) > 1e-8 for r in member['forces']):
        pending.append('存在扭矩：本模块未计入扭转应力')
    # No claim of complete code compliance: serviceability/connections remain external.
    return dict(section=s.name, strength_ratio=peak, flange_ratio=flange_ratio,
                web_80epsilon_ratio=web_ratio, governing_sample=governing,
                strength_pass=peak <= TARGET_UTILIZATION+1e-10,
                flange_pass=flange_ratio <= 1+1e-10, pending=pending)


def optimize(data, library=None):
    lib = load_library() if library is None else library
    if not 0 < TARGET_UTILIZATION <= 1: raise ValueError('Invalid target utilization')
    validate(data,lib)
    # Members with same design_group share a section; never optimize FE mesh pieces blindly.
    groups = {}
    for m in data['members']:
        groups.setdefault(str(m.get('design_group') or m['id']),[]).append(m)
    result = []
    assignments = {}
    proposals = {}
    for group, members in groups.items():
        chosen = None
        preliminary = None
        for s in sorted(lib.values(),key=lambda v:(v.area,v.h,v.b,v.name)):
            checks = [evaluate(s,m) for m in members]
            if all(c['strength_pass'] for c in checks):
                if preliminary is None: preliminary = s
                if all(not c['pending'] for c in checks):
                    chosen = s
                    break
        for m in members:
            current_section = str(m['current_section'])
            current = (evaluate(lib[current_section], m) if current_section in lib else
                       dict(section=current_section, status='当前截面不在本Q235焊接候选库中，未按本库复算'))
            proposal = chosen or preliminary
            result.append(dict(member_id=m['id'],design_group=group,current=current,
                candidate=evaluate(proposal,m) if proposal else None,
                status='可供下一轮重分析的截面建议' if chosen else
                       '仅强度初选，补充验算前不输出正式分配' if preliminary else '截面库无强度可行解'))
            if proposal: proposals[m['id']] = proposal.name
            if chosen: assignments[m['id']] = chosen.name
    return dict(scope='仅强度验算；不进行整体稳定、局部稳定及长细比验算；单轮固定内力选截面，需重分析',
                units='N-mm-MPa', axes=data['axes'], results=result,
                assignments=assignments, preliminary_proposals=proposals,
                candidate_sections={n:lib[n].export() for n in sorted(set(proposals.values()))},
                requires_reanalysis=True,
                external_checks=['变形','支座承压/支承加劲肋','连接','抗震要求',
                                 '内力采样完整性与单元内极值','剪切变形与剪切面积','整体模型稳定'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path)
    p.add_argument('--library',type=Path,default=LIBRARY)
    p.add_argument('--output',type=Path,default=ROOT/'steel_check_result.json')
    args = p.parse_args()
    if args.output.resolve() in (args.input.resolve(),args.library.resolve()):
        raise ValueError('Output may not overwrite an input')
    result = optimize(json.loads(args.input.read_text(encoding='utf-8-sig')),load_library(args.library))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('Members:',len(result['results']),'Assignments:',len(result['assignments']))
    print(args.output)


if __name__ == '__main__': main()
