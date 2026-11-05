"""Current load factors; companion load absence included when favourable."""
import itertools

PSI={'Q_OFFICE':(.7,.6,.5),'Q_STAIR':(.7,.5,.3),'Q_ROOF':(.7,.5,0.)}
WIND=('W_XP','W_XN','W_YP','W_YN')


def build_combinations():
 rows=[];seen=set()
 def add(state,factors,**extra):
  factors={k:float(v) for k,v in factors.items() if v};key=(state,tuple(sorted(factors.items())),tuple(sorted(extra.items())))
  if key not in seen:
   seen.add(key);rows.append({'id':f'{state}-{sum(r["limit_state"]==state for r in rows)+1:03}','limit_state':state,'factors':factors,'basis':'GB55001-2021 2.4.6/3.1.13及GB55002-2021 4.3.2，50年γL=1',**extra})
 variables=list(PSI)
 for gamma_g in (1.3,1.):
  add('ULS',{'G':gamma_g})
  for leader in variables:
   others=[v for v in variables if v!=leader]
   for activity in itertools.product((0,1),repeat=len(others)):
    factors={'G':gamma_g,leader:1.5,**{v:1.5*PSI[v][0]*a for v,a in zip(others,activity)}}
    for wind in (None,)+WIND:add('ULS',{**factors,**({wind:.9} if wind else {})})
  for wind in WIND:
   for activity in itertools.product((0,1),repeat=3):add('ULS',{'G':gamma_g,wind:1.5,**{v:1.5*PSI[v][0]*a for v,a in zip(variables,activity)}})
  for direction in ('X','Y','XY'):
   # GE is G+0.5Q_office+0.5Q_stair, excluding roof imposed load.
   for sign in (-1,1):add('SEISMIC',{'G':gamma_g,'Q_OFFICE':.5*gamma_g,'Q_STAIR':.5*gamma_g},earthquake_direction=direction,earthquake_factor=1.4,earthquake_sign=sign)
 for state,mode in (('STANDARD',0),('FREQUENT',1),('QUASI',2)):
  add('SLS',{'G':1.},service_type=state)
  if mode==2:add('SLS',{'G':1.,**{v:PSI[v][2] for v in variables}},service_type=state)
  else:
   for leader in variables+list(WIND):
    for activity in itertools.product((0,1),repeat=3):
     factor={v:(1. if mode==0 else PSI[v][1]) if v==leader else (PSI[v][0 if mode==0 else 2]*a) for v,a in zip(variables,activity)}
     winds=(leader,) if leader in WIND else (None,)+WIND
     for wind in winds:add('SLS',{'G':1.,**factor,**({wind:(1. if mode==0 else .4) if wind==leader else (.6 if mode==0 else 0.)} if wind else {})},service_type=state)
 return rows
