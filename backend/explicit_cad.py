"""Exact Z-up XYZ slices and editable A3 scheme drawings for explicit frames."""
from pathlib import Path
import json
import math
import ezdxf
from ezdxf.enums import TextEntityAlignment
from steelmind_export.runtime import resolve_font
from steelmind_export.cad import _new_doc, _viewport, _dimension, _text, _line, _render_pdf, _wrap


def generate_explicit_cad(tables, analysis, output_dir, include_pdf=True, upstream_status='INCOMPLETE'):
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    font, _ = resolve_font()
    nodes = {n['node_id']: n for n in analysis['nodes']}
    members = analysis['members']; sections = analysis['sections']
    marks = {m['member_id']: m['member_id'] if len(m['member_id']) <= 10 else f'M{i:03d}' for i,m in enumerate(members,1)}
    sheets, files, pdfs, errors, covered, section_sheets = [], [], [], [], set(), []
    project = next((str(r.get('value') or r.get('字段名称') or '原模型钢框架') for name,rows in tables.items() if name.lower()=='project' for r in rows if r.get('field_id')=='project_name'), '原模型钢框架')
    def frame(layout, title, scale=None, note=''):
        layout.add_lwpolyline([(10,10),(410,10),(410,287),(10,287)], close=True, dxfattribs={'layer':'P-FRAME'})
        _line(layout,(10,48),(410,48),'P-FRAME')
        _text(layout,title,18,277,4)
        _text(layout,project[:50],18,267,2.5)
        _text(layout,f'方案草稿 / 非施工图    规范汇总 {upstream_status}',18,36,3)
        _text(layout,'原XYZ坐标，Z竖向；模型单位mm，1:1；未设计连接、楼板及节点深化。',18,25,2.5)
        _text(layout,note,18,15,2.5)
        if scale:_text(layout,f'视口 1:{scale:g}',340,267,2.5)
    def make():
        d,l = _new_doc(font); d.layers.new('S-MEMBER',dxfattribs={'color':7});d.appids.new('SOURCE')
        return d,l
    def save(d,name,kind,expected=(),ids=(),scale=1):
        path=out/(name+'.dxf');d.saveas(path);read=ezdxf.readfile(path)
        if read.audit().has_errors:raise ValueError('DXF实体审查失败：'+path.name)
        measured=[float(x.get_measurement()) for x in read.modelspace().query('DIMENSION')]
        if len(measured)!=len(expected) or any(not math.isclose(a,b,rel_tol=0,abs_tol=1e-5) for a,b in zip(measured,expected)):
            raise ValueError('DXF真实尺寸核对失败：'+path.name)
        heights=[e.dxf.height/scale for e in read.modelspace().query('TEXT')] + [e.dxf.height for e in read.layouts.get('A3').query('TEXT')]
        if heights and min(heights)<2.5-1e-8:raise ValueError('纸面文字小于2.5mm：'+path.name)
        row={'file':path.name,'kind':kind,'members':sorted(set(ids)),'dimension_mm':measured,'model_units':'mm','model_scale':'1:1','viewport_scale':scale,'min_paper_text_mm':min(heights) if heights else 2.5,'audit_errors':[]}
        sheets.append(row);files.append(path)
        if include_pdf:
            pdf_dir=out/'_rendered';pdf_dir.mkdir(exist_ok=True);pdf=pdf_dir/(name+'.pdf')
            try:_render_pdf(path,pdf,font);pdfs.append(pdf)
            except Exception as e:errors.append({'sheet':path.name,'error':str(e)})
    def choose_scale(u0,v0,u1,v1):
        required=max((u1-u0)*1000/285,(v1-v0)*1000/145,1)
        for scale in (1,2,5,10,20,25,50,75,100,150,200,250,500,1000,2000,5000,10000,20000,50000,100000):
            if scale>=required:return scale
        raise ValueError('图纸比例超出支持范围')
    def coord(n,axis):return n['xyz_m'][axis]
    views=[]
    for z in sorted({n['xyz_m'][2] for n in nodes.values()}):
        if z>min(n['xyz_m'][2] for n in nodes.values())+1e-8:views.append(('plan',2,z,0,1,f'XY层平面 Z={z:g}m'))
    for y in sorted({n['xyz_m'][1] for n in nodes.values()}):views.append(('elevation',1,y,0,2,f'XZ立面 Y={y:g}m'))
    for x in sorted({n['xyz_m'][0] for n in nodes.values()}):views.append(('elevation',0,x,1,2,f'YZ立面 X={x:g}m'))
    if len(views)>100:raise ValueError('精确切片图超过100张，请按分区出图')
    for number,(kind,fixed,value,u,v,title) in enumerate(views,1):
        selected=[m for m in members if all(abs(coord(nodes[m[k]],fixed)-value)<1e-8 for k in ('i_node','j_node'))]
        columns=[]
        if kind=='plan':
            for m in members:
                a,b=nodes[m['i_node']]['xyz_m'],nodes[m['j_node']]['xyz_m']
                if abs(a[0]-b[0])<1e-8 and abs(a[1]-b[1])<1e-8 and min(a[2],b[2])+1e-8<value<=max(a[2],b[2])+1e-8:columns.append(m)
        points=[nodes[m[k]]['xyz_m'] for m in selected+columns for k in ('i_node','j_node')]
        if not points:continue
        u0,u1=min(p[u] for p in points),max(p[u] for p in points);v0,v1=min(p[v] for p in points),max(p[v] for p in points)
        scale=choose_scale(u0,v0,u1,v1);d,l=make();model=d.modelspace();expected=[];ids=[]
        def source(e,m):e.set_xdata('SOURCE',[(1000,m['member_id']),(1000,m['section_id']),(1000,f'{title}; original XYZ retained in input snapshot')])
        for m in selected:
            a,b=nodes[m['i_node']]['xyz_m'],nodes[m['j_node']]['xyz_m'];p1=(a[u]*1000,a[v]*1000);p2=(b[u]*1000,b[v]*1000)
            if math.dist(p1,p2)<1e-7:continue
            source(model.add_line(p1,p2,dxfattribs={'layer':'S-MEMBER'}),m);ids.append(m['member_id']);covered.add(m['member_id'])
            vertical=abs(p1[0]-p2[0])<1e-7
            label_pos=((p1[0]+p2[0])/2+(3*scale if vertical else 0),(p1[1]+p2[1])/2+(0 if vertical else 3*scale))
            label=_text(model,marks[m['member_id']],*label_pos,2.5*scale,'S-TEXT',90 if vertical else 0)
            label.set_placement(label_pos,align=TextEntityAlignment.MIDDLE_CENTER)
            length=math.dist(p1,p2)
            for p,end,other in [(p1,'i',p2),(p2,'j',p1)]:
                if m['hinge_'+end]:
                    pos=(p[0]+(other[0]-p[0])/length*2.5*scale,p[1]+(other[1]-p[1])/length*2.5*scale)
                    model.add_circle(pos,1.5*scale,dxfattribs={'layer':'S-RELEASE'})
        for m in columns:
            p=nodes[m['i_node']]['xyz_m'];s=sections[m['section_id']];x,y=p[u]*1000,p[v]*1000;w,h=float(s['width_mm']),float(s['depth_mm'])
            axes=m['axes'];corners=[(x+db*axes[2][0]+dh*axes[1][0],y+db*axes[2][1]+dh*axes[1][1]) for db,dh in [(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)]]
            e=model.add_lwpolyline(corners,close=True,dxfattribs={'layer':'S-OUTLINE'});source(e,m)
            _text(model,marks[m['member_id']],x+5*scale,y+4*scale,2.5*scale,'S-TEXT');ids.append(m['member_id']);covered.add(m['member_id'])
        us=sorted({p[u]*1000 for p in points});vs=sorted({p[v]*1000 for p in points})
        for a,b in zip(us,us[1:]):_dimension(model,expected,(a,v0*1000),(b,v0*1000),(a,v0*1000-9*scale),0,scale)
        for a,b in zip(vs,vs[1:]):_dimension(model,expected,(u0*1000,a),(u0*1000,b),(u0*1000-11*scale,a),90,scale)
        for i,x in enumerate(us,1):
            _line(model,(x,v0*1000-5*scale),(x,v1*1000+6*scale),'S-AXIS');_text(model,f'{"XYZ"[u]}{i}',x-2*scale,v1*1000+7*scale,2.5*scale,'S-TEXT')
        for i,y in enumerate(vs,1):
            _line(model,(u0*1000-5*scale,y),(u1*1000+6*scale,y),'S-AXIS');_text(model,f'{"XYZ"[v]}{i}',u1*1000+7*scale,y,2.5*scale,'S-TEXT')
        for n in nodes.values():
            if abs(coord(n,fixed)-value)>1e-8:continue
            row=next((r for name,rows in tables.items() if name.lower()=='nodes' for r in rows if r.get('node_id')==n['node_id']),{})
            flags=[int(float(row.get(k) or 0)) for k in ('ux','uy','uz','rx','ry','rz')]
            if not any(flags):continue
            x,y=coord(n,u)*1000,coord(n,v)*1000
            for dx in (-3,0,3):_line(model,(x+dx*scale,y),(x+(dx-2)*scale,y-4*scale),'S-SUPPORT')
            _text(model,''.join(map(str,flags)),x+4*scale,y-6*scale,2.5*scale,'S-TEXT')
        _viewport(l,(25,60,395,255),((u0+u1)*500,(v0+v1)*500),scale)
        note='编号对应构件表；圆圈为两弯矩释放；支座六位=ux uy uz rx ry rz；轴序按实际坐标排序。'
        if kind=='plan':note='柱符号取该标高下侧真实构件；构件编号见表；轴序按实际坐标排序。'
        frame(l,title,scale,note)
        save(d,f'{number:02d}_{"XY平面" if kind=="plan" else "XZ立面" if u==0 else "YZ立面"}_{value:g}',kind,[e['expected_mm'] for e in expected],ids,scale)
    uncovered=set(marks)-covered
    if uncovered:errors.append({'error':'部分构件不在轴向精确切片内，未投影冒充平面杆件','members':sorted(uncovered)})
    # Original IDs and section assignments travel with every drawn mark.
    columns=(18,48,135,260,320);widths=(27,83,120,56,70);page=1;d,l=make();frame(l,'构件与截面表 第1页',note='长度为轴线长度；本表不含连接、节点域或施工下料长度。');y=248
    def headings(layout):
        for x,t in zip(columns,('图中编号','原始构件编号','截面型号','材料','轴线长度m')):_text(layout,t,x,257,2.7)
    headings(l)
    for m in members:
        values=(marks[m['member_id']],m['member_id'],sections[m['section_id']].get('section_name',m['section_id']),analysis['materials'][m['material_id']].get('grade','未提供'),f'{m["length_m"]:.6g}')
        wrapped=[_wrap(t,w,2.5) for t,w in zip(values,widths)];height=max(6,max(map(len,wrapped))*4+2)
        if y-height<58:
            save(d,f'80_构件表_{page:02d}','schedule');page+=1;d,l=make();frame(l,f'构件与截面表 第{page}页',note='长度为轴线长度，非施工下料长度。');headings(l);y=248
        for x,lines in zip(columns,wrapped):
            for k,line in enumerate(lines):_text(l,line,x,y-k*4,2.5)
        _line(l,(18,y-height+3.5),(395,y-height+3.5),'P-FRAME');y-=height
    save(d,f'80_构件表_{page:02d}','schedule')
    for i,(sid,s) in enumerate(sections.items(),1):
        d,l=make();model=d.modelspace();h,b,tw,tf=[float(s[k]) for k in ('depth_mm','width_mm','tw_mm','tf_mm')];shape=str(s['shape']).upper();scale=choose_scale(-b/1000,-h/1000,b/1000,h/1000)
        if shape in ('BOX','SHS','RHS'):
            rings=[[(-b/2,0),(b/2,0),(b/2,h),(-b/2,h)],[(-b/2+tw,tf),(b/2-tw,tf),(b/2-tw,h-tf),(-b/2+tw,h-tf)]]
        elif shape in ('H','I','H-WELDED'):
            rings=[[(-b/2,0),(b/2,0),(b/2,tf),(tw/2,tf),(tw/2,h-tf),(b/2,h-tf),(b/2,h),(-b/2,h),(-b/2,h-tf),(-tw/2,h-tf),(-tw/2,tf),(-b/2,tf)]]
        else:raise ValueError('截面绘图不支持：'+shape)
        for ring in rings:
            for a,c in zip(ring,ring[1:]+ring[:1]):_line(model,a,c,'S-OUTLINE')
        expected=[];_dimension(model,expected,(-b/2,0),(b/2,0),(0,-10*scale),0,scale);_dimension(model,expected,(-b/2,0),(-b/2,h),(-b/2-10*scale,0),90,scale)
        _viewport(l,(25,65,220,250),(0,h/2),scale);frame(l,'截面示意 '+str(s.get('section_name',sid)),scale,'按上游尺寸与权威属性绘制；圆角及焊缝未深化，J为薄壁近似。')
        for j,(key,value) in enumerate([('h / mm',h),('b / mm',b),('tw / mm',tw),('tf / mm',tf),('A / mm2',s['A']),('Iy / mm4',s['Iy']),('Iz / mm4',s['Iz'])]):_text(l,f'{key} = {value:.6g}',240,235-j*18,2.7)
        save(d,f'85_截面_{i:02d}','section',[e['expected_mm'] for e in expected],scale=scale);section_sheets.append({'section_id':sid,'shape':shape,'rings':len(rings),'file':files[-1].name})
    if include_pdf and pdfs:
        from pypdf import PdfWriter
        writer=PdfWriter()
        for p in pdfs:writer.append(p)
        target=out/'钢框架方案图册.pdf'
        with target.open('wb') as f:writer.write(f)
        writer.close();files.append(target)
    if include_pdf and len(pdfs)!=len(sheets):errors.append({'error':'部分DXF布局未成功渲染PDF','expected_pages':len(sheets),'actual_pages':len(pdfs)})
    quality={'schema_version':'ExplicitCAD/1.0','status':'PARTIAL' if errors else 'PASS','scope':'原XYZ/Z竖向轴向精确切片；方案草稿，非施工图','covered_members':sorted(covered),'uncovered_members':sorted(uncovered),'sheets':sheets,'section_sheets':section_sheets,'pdf_pages':len(pdfs),'errors':errors}
    path=out/'出图质量记录.json';path.write_text(json.dumps(quality,ensure_ascii=False,indent=2));files.append(path)
    return files,quality
