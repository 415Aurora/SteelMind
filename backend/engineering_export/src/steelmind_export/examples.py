"""Deterministic examples. No example claims independent solver verification."""
from copy import deepcopy
from .models import DesignBundle


def _section():
    # Three idealized rectangles; no fillets, root radii or catalogue roundings.
    return dict(id='H300',name='H300×200×8×12',shape='H',h_mm=300,b_mm=200,
                tw_mm=8,tf_mm=12,A_mm2=7008,Ix_mm4=113606784,Iy_mm4=16011776,
                Wx_mm3=757378.56,Wy_mm3=160117.76,property_basis='idealized',
                source='Idealized rectangular decomposition, no root radii')


def _canonical(bundle):
    return DesignBundle.model_validate(bundle).model_dump(mode='json')


def minimal_bundle() -> dict:
    """One 6 m span with geometry only, deliberately a draft."""
    return _canonical(dict(
        schema_version='1.0',project=dict(name='单跨钢梁 · 最小输入',
            assumptions=['二维杆系；坐标单位 m；截面尺寸单位 mm'],
            limitations=['几何输入示例；未提供分析或规范验算']),
        provenance=dict(data_kind='upstream',source='User-editable minimal geometry',run_id='minimal-v1'),
        model=dict(nodes=[dict(id='N1',x_m=0,y_m=0),dict(id='N2',x_m=6,y_m=0)],
            materials=[dict(id='Q235',name='Q235 teaching material',E_MPa=206000,fy_MPa=235,
                            source='Illustrative material input; verify project specification')],
            sections=[_section()],
            members=[dict(id='B1',node_i='N1',node_j='N2',section_id='H300',material_id='Q235',
                          kind='beam',release_i=True,release_j=True)],
            supports=[dict(node_id='N1',ux=True,uy=True,rz=False),
                      dict(node_id='N2',ux=False,uy=True,rz=False)])))


def analytic_bundle() -> dict:
    """Closed-form simple beam: L=6 m, q=10 kN/m, E=206000 MPa.

    q=10 N/mm, L=6000 mm. Support end actions act upward on the member
    at BOTH ends. Section V decreases from +30 to -30 and M is sagging.
    Checks demonstrate data provenance only; no normative claim is made.
    """
    b=minimal_bundle()
    b['project'].update(name='解析基准 · 6m 简支梁',assumptions=[
        'Euler–Bernoulli 梁；小变形；恒定 EI；均布重力荷载 10 kN/m',
        '理想 H300×200×8×12，忽略圆角；未计自重或剪切变形'],
        limitations=['解析基准仅检验单位及符号约定；示意验算不代表完整规范校核'])
    b['provenance'].update(data_kind='analytic_benchmark',source='Closed-form elementary beam theory',
                           run_id='analytic-v1',tool_versions={'builder':'steelmind-export-1.0'})
    b['load_cases']=[dict(id='Q',name='均布竖向荷载',kind='variable',source='Analytic benchmark q=10 kN/m',
        loads=[dict(kind='uniform_member',target_id='B1',qx_kN_m=0,qy_kN_m=-10)])]
    b['combinations']=[dict(id=id,name=name,factors={'Q':1},limit_state=state,source='Benchmark factor 1.0; not normative combination')
        for id,name,state in [('ULS1','基准承载组合','ULS'),('SLS1','基准使用组合','SLS')]]
    a=dict(node_displacements=[],reactions=[],member_end_forces=[],member_samples=[])
    for combo in ('ULS1','SLS1'):
        for node in ('N1','N2'):
            a['reactions'].append(dict(node_id=node,combination_id=combo,fx_kN=0,fy_kN=30,mz_kNm=0))
            rotation=10*6000**3/(24*206000*113606784)
            a['node_displacements'].append(dict(node_id=node,combination_id=combo,ux_mm=0,uy_mm=0,
                rz_rad=-rotation if node=='N1' else rotation))
        a['member_end_forces'].append(dict(member_id='B1',combination_id=combo,
            Ni_kN=0,Vi_kN=30,Mi_kNm=0,Nj_kN=0,Vj_kN=30,Mj_kNm=0))
        for index in range(13):
            x=index*.5
            a['member_samples'].append(dict(member_id='B1',combination_id=combo,x_m=x,side='single',
                N_kN=0,V_kN=10*(3-x),M_kNm=10*x*(6-x)/2))
    b['analysis']=a
    delta=5*10*6000**4/(384*206000*113606784)
    stress=45_000_000/757378.56
    b['checks']=[
        dict(id='C_STRENGTH',target_id='B1',combination_id='ULS1',item='strength',status='PASS',
            demand=stress,limit=235,comparator='<=',unit='MPa',utilization=stress/235,
            formula_text='sigma = M_max / Wx <= fy (illustrative only)',
            substitution=f'45e6 / 757378.56 = {stress:.6f} MPa <= 235 MPa',
            source='Elementary elastic stress example, not normative design',clause='Illustrative benchmark',trace_ids=['T_STRESS']),
        dict(id='C_DEFLECTION',target_id='B1',combination_id='SLS1',item='deflection',status='PASS',
            demand=delta,limit=20,comparator='abs<=',unit='mm',utilization=delta/20,
            formula_text='delta_max = 5 q L^4 / (384 E Ix); illustrative limit L/300',
            substitution=f'5*10*6000^4/(384*206000*113606784) = {delta:.6f} mm <= 20 mm',
            source='Closed-form beam theory; limit illustrative only',clause='Illustrative benchmark',trace_ids=['T_DEFLECTION'])]
    b['traces']=[
        dict(id='T_STRESS',name='最大弹性弯曲正应力',formula_text='sigma = Mmax / Wx',
            inputs={'Mmax_Nmm':45_000_000,'Wx_mm3':757378.56},intermediate=['Mmax = q L² / 8 = 45 kN*m'],
            result=stress,unit='MPa',source='Closed-form simple beam theory',result_path='/checks/0/demand'),
        dict(id='T_DEFLECTION',name='跨中相对最大挠度',formula_text='delta = 5 q L^4 / (384 E Ix)',
            inputs={'q_N_mm':10,'L_mm':6000,'E_MPa':206000,'Ix_mm4':113606784},
            intermediate=['10 kN/m = 10 N/mm','6 m = 6000 mm','Downward signed uy = -delta'],
            result=delta,unit='mm',source='Closed-form Euler–Bernoulli simple beam theory',result_path='/checks/1/demand')]
    return _canonical(b)


def demo_bundle() -> dict:
    """Three storeys, 6 m + 8 m spans; fabricated representative results.

    This is presentation data, not an independently solved equilibrium model.
    A failing check and missing checks are intentional and must stay visible.
    """
    b=minimal_bundle()
    b['project'].update(name='SteelMind · 三层两跨钢框架演示',designer='演示作者',institution='教学演示',
        assumptions=['二维框架；刚接梁柱；柱脚固结','跨度 6m + 8m；层高 3.6m；统一理想 H 截面'],
        limitations=['DEMO 数据用于展示，不可用于工程设计或提交','结果为人工编排，未进行独立求解或平衡复核',
                     '部分验算缺失；一个不通过验算故意保留以展示真实状态'])
    b['provenance'].update(data_kind='demonstration',source='DEMO: manually authored presentation data; no independent solver',
                           run_id='demo-v1',tool_versions={'builder':'steelmind-export-1.0'})
    nodes=[dict(id=f'N{floor}{axis}',x_m=x,y_m=3.6*floor)
           for floor in range(4) for axis,x in enumerate((0,6,14))]
    members=[]
    for floor in range(1,4):
        for axis in range(3):
            members.append(dict(id=f'C{floor}{axis}',node_i=f'N{floor-1}{axis}',node_j=f'N{floor}{axis}',
                section_id='H300',material_id='Q235',kind='column'))
        for axis in range(2):
            members.append(dict(id=f'B{floor}{axis}',node_i=f'N{floor}{axis}',node_j=f'N{floor}{axis+1}',
                section_id='H300',material_id='Q235',kind='beam'))
    b['model'].update(nodes=nodes,members=members,supports=[dict(node_id=f'N0{axis}',ux=True,uy=True,rz=True) for axis in range(3)])
    b['load_cases']=[dict(id='G',name='DEMO 恒载',kind='permanent',source='DEMO teaching input',
        loads=[dict(kind='uniform_member',target_id=m['id'],qx_kN_m=0,qy_kN_m=-10) for m in members if m['kind']=='beam']),
        dict(id='Q',name='DEMO 活载',kind='variable',source='DEMO teaching input',
        loads=[dict(kind='uniform_member',target_id=m['id'],qx_kN_m=0,qy_kN_m=-5) for m in members if m['kind']=='beam'])]
    b['combinations']=[dict(id='ULS1',name='DEMO 承载组合',limit_state='ULS',factors={'G':1.3,'Q':1.5},source='DEMO illustrative factors; not normative'),
        dict(id='SLS1',name='DEMO 使用组合',limit_state='SLS',factors={'G':1,'Q':1},source='DEMO illustrative factors; not normative')]
    a=dict(node_displacements=[],reactions=[],member_end_forces=[],member_samples=[])
    for combo,scale in [('ULS1',1.4),('SLS1',1.0)]:
        for n in nodes:
            floor=int(n['id'][1])
            a['node_displacements'].append(dict(node_id=n['id'],combination_id=combo,
                ux_mm=scale*floor*2.5,uy_mm=-scale*floor*1.5,rz_rad=scale*floor*.0002))
        for axis in range(3):
            a['reactions'].append(dict(node_id=f'N0{axis}',combination_id=combo,fx_kN=-scale*10,
                fy_kN=scale*(180+axis*40),mz_kNm=scale*15))
        for m in members:
            beam=m['kind']=='beam'; length=6 if beam and m['id'][-1]=='0' else 8 if beam else 3.6
            q=15*scale if beam else 0
            axial=0 if beam else -120*scale
            a['member_end_forces'].append(dict(member_id=m['id'],combination_id=combo,
                Ni_kN=-axial,Vi_kN=q*length/2,Mi_kNm=0,Nj_kN=axial,Vj_kN=q*length/2,Mj_kNm=0))
            for station in range(9):
                x=length*station/8
                a['member_samples'].append(dict(member_id=m['id'],combination_id=combo,x_m=x,side='single',
                    N_kN=axial,V_kN=q*(length/2-x),M_kNm=q*x*(length-x)/2))
    b['analysis']=a
    b['checks']=[]; b['traces']=[]
    for index,(target,combo,item,demand,limit,unit) in enumerate([
        ('B10','ULS1','strength',120,235,'MPa'),
        ('B11','ULS1','strength',270,235,'MPa'),
        ('B10','SLS1','deflection',12,20,'mm'),
        ('C10','ULS1','stability',.72,1,'ratio'),
        ('FRAME','SLS1','drift',.002,1/250,'ratio'),
    ]):
        trace_id=f'T_DEMO_{index+1}'
        b['checks'].append(dict(id=f'C_DEMO_{index+1}',target_id=target,combination_id=combo,item=item,
            status='PASS' if demand<=limit else 'FAIL',demand=demand,limit=limit,comparator='<=',unit=unit,
            utilization=demand/limit,formula_text='DEMO: utilization = demand / limit',
            substitution=f'DEMO: {demand} / {limit} = {demand/limit:.6f}',
            source='DEMO manually authored; not a normative design check',clause='DEMO illustrative only',trace_ids=[trace_id]))
        b['traces'].append(dict(id=trace_id,name=f'DEMO {target} {item}',formula_text='DEMO supplied demand',
            inputs={'data_kind':'DEMO','supplied_demand':demand},intermediate=['No independent solver verification'],
            result=demand,unit=unit,source='DEMO presentation data',result_path=f'/checks/{index}/demand'))
    return _canonical(b)
