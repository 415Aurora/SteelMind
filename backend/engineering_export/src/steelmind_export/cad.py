"""Editable 2D steel-frame drawings. Coordinates and DIMENSION values are mm.

Each saved DXF owns an A3 paperspace sheet; PDF renders that saved layout.
No structural analysis or connection design is performed here.
"""
from __future__ import annotations

from collections import Counter
from contextvars import ContextVar
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unicodedata

import ezdxf
from .models import DesignBundle
from .results import ExportOutcome, GenerationOptions
from .validation import ValidationReport
from . import runtime

LAYERS = {
    'S-OUTLINE': 35, 'S-AXIS': 13, 'S-DIM': 18, 'S-TEXT': 18,
    'S-SUPPORT': 25, 'S-RELEASE': 18, 'P-FRAME': 35, 'P-TEXT': 18, 'P-VPORT': 0,
}
FRAME_SCALES = (50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000)
VIEW_RECT = (30., 80., 390., 260.)
_TEXT_METRIC = ContextVar('steelmind_cad_text_metric', default=None)


def _wrap(value, width, height=2.7):
    """Deterministic conservative wrapping; keeps every character including IDs."""
    result, line, used = [], '', 0.
    for ch in str(value):
        if ch == '\n':
            result.append(line); line, used = '', 0.
            continue
        metric = _TEXT_METRIC.get()
        advance = height * (metric.text_width(ch) + .04 if metric else (1.6 if unicodedata.east_asian_width(ch) in 'WF' else 1.2))
        if used + advance > width and line:
            result.append(line); line, used = '', 0.
        line += ch; used += advance
    result.append(line)
    return result


def _text(layout, value, x, y, height=2.7, layer='P-TEXT', rotation=0):
    # TEXT has no MTEXT formatting interpretation: arbitrary user strings stay literal.
    return layout.add_text(str(value), dxfattribs=dict(insert=(x,y), height=height,
        style='STEELMIND', layer=layer, rotation=rotation))


def _paragraph(layout, value, x, y, width, height=2.7, layer='P-TEXT'):
    lines = _wrap(value, width, height)
    for line in lines:
        _text(layout, line, x, y, height, layer)
        y -= height*1.45
    return y


def _line(layout, a, b, layer):
    return layout.add_line(a,b,dxfattribs={'layer':layer})


def _new_doc(font_path):
    doc = ezdxf.new('R2018', setup=['linetypes'])
    doc.units = 4
    doc.header['$MEASUREMENT'] = 1
    doc.header['$LUNITS'] = 2
    doc.header['$LUPREC'] = 3
    for name, weight in LAYERS.items():
        doc.layers.new(name, dxfattribs={'color':7,'lineweight':weight, 'plot':int(name!='P-VPORT')})
    # Filename travels with the editable drawing; rendering registers its full path.
    doc.styles.new('STEELMIND',dxfattribs={'font':font_path.name})
    doc.styles.get('Standard').dxf.font = font_path.name
    doc.layouts.rename('Layout1','A3'); layout = doc.layouts.get('A3')
    layout.page_setup(size=(420,297),margins=(0,0,0,0),units='mm',scale=(1,1))
    layout.set_plot_type(5)
    return doc, layout


def _sheet_frame(layout, bundle, validation, title, sheet_no, scale='—'):
    layout.add_lwpolyline([(10,10),(410,10),(410,287),(10,287)],close=True,dxfattribs={'layer':'P-FRAME'})
    _line(layout,(10,70),(410,70),'P-FRAME')
    _line(layout,(235,10),(235,70),'P-FRAME')
    for y in (22,34,46,58): _line(layout,(235,y),(410,y),'P-FRAME')
    _text(layout,title,18,276,4.0)
    flag = '草稿 | ' if validation.draft else ''
    _text(layout,flag+'二维框架方案图 / 非施工图',241,62,3.2)
    _text(layout,'图名: '+title,241,50,2.7)
    _text(layout,f'图号: {sheet_no}    比例: {scale}',241,38,2.7)
    _text(layout,'单位: mm    Global X → / Y ↑',241,26,2.7)
    credit='设计: '+bundle.project.designer+'    日期: '+bundle.project.date
    if len(_wrap(credit,163,2.5))>1: credit='设计 / 日期详见项目资料页'
    _text(layout,credit,241,14,2.5)
    name_lines = _wrap(bundle.project.name,380,2.8)
    # Unbounded metadata is carried on dedicated table pages below; this header
    # refers to that record when too long to fit its reserved strip.
    for j,line in enumerate(name_lines[:3]): _text(layout,line,18,269-j*3.9,2.8)
    if len(name_lines)>3: _text(layout,'项目全名见项目资料页',18,257,2.5)
    note = '上游验算汇总: '+validation.upstream_check_summary
    if validation.upstream_check_summary=='FAIL': note += ' | 警告：上游存在 FAIL 验算'
    _text(layout,note,18,61,3.0)
    _text(layout,'仅按输入二维杆系绘制；未推定面外构造或节点连接。',18,53,2.7)
    _text(layout,'模型单位 mm；坐标 = 输入 m × 1000；全局 X 向右，Y 向上。',18,45,2.7)
    _text(layout,'圆圈 = 指定杆端转动释放；不代表实体连接构造。',18,37,2.7)
    _text(layout,'支座旁 ux / uy / rz: 1=约束，0=自由；未补充约束。',18,29,2.7)
    _text(layout,'截面及材料采用输入值；图纸不替代施工图与工程校核。',18,21,2.7)
    institution='机构: '+bundle.project.institution+'  学号: '+bundle.project.student_id
    if len(_wrap(institution,210,2.5))>1: institution='机构 / 学号详见项目资料页'
    _text(layout,institution,18,13,2.5)


def _viewport(layout, rect, center, scale):
    x0,y0,x1,y1 = rect
    vp = layout.add_viewport(center=((x0+x1)/2,(y0+y1)/2),size=(x1-x0,y1-y0),
         view_center_point=center,view_height=(y1-y0)*scale,dxfattribs={'layer':'P-VPORT'})
    vp.dxf.flags = vp.dxf.flags | 16384  # lock zoom in CAD
    return vp


def _dimension(model, expected, p1,p2,base,angle,scale):
    dim = model.add_linear_dim(base=base,p1=p1,p2=p2,angle=angle,text='<>',
        override={'dimtxt':2.7*scale,'dimasz':2.0*scale,'dimgap':.8*scale,
                  'dimexo':1.0*scale,'dimexe':1.5*scale,'dimtad':1,'dimdec':3,
                  'dimzin':8,'dimclrd':7,'dimclre':7,'dimclrt':7,'dimtxsty':'STEELMIND'},
        dxfattribs={'layer':'S-DIM'})
    dim.render()
    expected.append({'handle':dim.dimension.dxf.handle,'expected_mm':float(abs(
        (p2[0]-p1[0])*math.cos(math.radians(angle))+(p2[1]-p1[1])*math.sin(math.radians(angle))))})


def _geometry_bounds(bundle):
    xs=[n.x_m*1000 for n in bundle.model.nodes]; ys=[n.y_m*1000 for n in bundle.model.nodes]
    return min(xs),min(ys),max(xs),max(ys)


def _frame_tiles(bundle):
    x0,y0,x1,y1=_geometry_bounds(bundle)
    # The 180 mm viewport leaves 60 mm for axes and outer dimension chains.
    # Using only 100 mm needlessly shrank normal three-storey frames and made
    # adjacent support labels collide even though the sheet had ample space.
    fit=max((x1-x0)/270,(y1-y0)/120)
    scale=next((s for s in FRAME_SCALES if s>=fit),FRAME_SCALES[-1])
    nodes={n.id:(n.x_m*1000,n.y_m*1000) for n in bundle.model.nodes}
    lengths=[math.dist(nodes[m.node_i],nodes[m.node_j]) for m in bundle.model.members]
    # Do not shrink a short bay into an illegible speck. Tile at a smaller
    # standard scale and state each viewport's exact model bounds.
    eligible=[s for s in FRAME_SCALES if s<=max(50,min(lengths)/18)]
    scale=min(scale,max(eligible))
    content_w,content_h=270*scale,120*scale
    nx=max(1,math.ceil((x1-x0)/content_w)); ny=max(1,math.ceil((y1-y0)/content_h))
    if nx*ny>200: raise ValueError(f'框架需要 {nx*ny} 张分幅图；超出支持范围 200，请按模型分区导出。')
    tiles=[]
    for row in range(ny):
        for col in range(nx):
            center=(x0+(col+.5)*(x1-x0)/nx, y0+(row+.5)*(y1-y0)/ny)
            tiles.append((center,scale,(col+1,row+1,nx,ny)))
    return tiles


def _frame_model(doc,bundle,scale,expected,assignments=False):
    model=doc.modelspace(); nodes={n.id:(n.x_m*1000,n.y_m*1000) for n in bundle.model.nodes}
    sections={s.id:s for s in bundle.model.sections}
    x0,y0,x1,y1=_geometry_bounds(bundle)
    h=2.7*scale
    # Every actual member is one independently editable line at original coords.
    # Offset parallel/coincident labels into lanes without altering geometry.
    lanes=Counter()
    for member in bundle.model.members:
        a,b=nodes[member.node_i],nodes[member.node_j]
        _line(model,a,b,'S-OUTLINE')
        dx,dy=b[0]-a[0],b[1]-a[1]; length=math.hypot(dx,dy)
        key=tuple(sorted((member.node_i,member.node_j)))
        lane=lanes[key]; lanes[key]+=1
        nx,ny=-dy/length,dx/length
        label=member.id
        if assignments: label+=' / '+member.section_id
        # Full material assignments stay in the member table. Horizontal column
        # labels at midheight cannot extend vertically into the next storey.
        metric=_TEXT_METRIC.get()
        width=metric.text_width(label)*h if metric else len(label)*h
        midx,midy=(a[0]+b[0])/2,(a[1]+b[1])/2
        if member.kind=='column' and abs(dy)>abs(dx):
            tx,ty=midx+(4+6*lane)*scale,midy-h*.5
        else:
            tx,ty=midx-width/2,midy+(4+4*lane)*scale
        _text(model,label,tx,ty,h,'S-TEXT')
        for pt,other,released in ((a,b,member.release_i),(b,a,member.release_j)):
            if released:
                delta=(other[0]-pt[0],other[1]-pt[1]); ratio=min(3*scale/length,.15)
                model.add_circle((pt[0]+delta[0]*ratio,pt[1]+delta[1]*ratio),1.4*scale,dxfattribs={'layer':'S-RELEASE'})
    for node in bundle.model.nodes:
        x,y=nodes[node.id]
        model.add_circle((x,y),.7*scale,dxfattribs={'layer':'S-AXIS'})
        _text(model,node.id,x+2*scale,y-5*scale,h,'S-TEXT')
    # Span/level axes reflect actual distinct coordinates. Native dimensions
    # outside the outline measure coordinate differences, never display overrides.
    xs=sorted(set(pt[0] for pt in nodes.values())); ys=sorted(set(pt[1] for pt in nodes.values()))
    for i,x in enumerate(xs):
        _line(model,(x,y0-12*scale),(x,y1+7*scale),'S-AXIS')
        _text(model,f'X{i+1}',x-2*scale,y1+9*scale,h,'S-AXIS')
    for i,y in enumerate(ys):
        _line(model,(x0-7*scale,y),(x1+9*scale,y),'S-AXIS')
        _text(model,f'Y{i+1}',x1+10*scale,y,h,'S-AXIS')
    for a,b in zip(xs,xs[1:]): _dimension(model,expected,(a,y0),(b,y0),(a,y0-22*scale),0,scale)
    if len(xs)>2: _dimension(model,expected,(x0,y0),(x1,y0),(x0,y0-32*scale),0,scale)
    for a,b in zip(ys,ys[1:]): _dimension(model,expected,(x0,a),(x0,b),(x0-22*scale,a),90,scale)
    if len(ys)>2: _dimension(model,expected,(x0,y0),(x0,y1),(x0-32*scale,y0),90,scale)
    for sup in bundle.model.supports:
        x,y=nodes[sup.node_id]; r=3*scale
        if sup.ux: _line(model,(x-r,y-r),(x-r,y+r),'S-SUPPORT')
        if sup.uy: _line(model,(x-r,y-r),(x+r,y-r),'S-SUPPORT')
        if sup.rz: model.add_lwpolyline([(x-r,y-r),(x+r,y-r),(x+r,y+r),(x-r,y+r)],close=True,dxfattribs={'layer':'S-SUPPORT'})
        if not (sup.ux or sup.uy or sup.rz): model.add_circle((x,y-r),r,dxfattribs={'layer':'S-SUPPORT'})
        _text(model,f'{sup.node_id} ux={int(sup.ux)} uy={int(sup.uy)} rz={int(sup.rz)}',x+4*scale,y-10*scale,2.5*scale,'S-SUPPORT')


def _section_model(doc,section,scale,expected):
    m=doc.modelspace(); h,b,tw,tf=section.h_mm,section.b_mm,section.tw_mm,section.tf_mm
    points=[(-b/2,0),(b/2,0),(b/2,tf),(tw/2,tf),(tw/2,h-tf),(b/2,h-tf),
            (b/2,h),(-b/2,h),(-b/2,h-tf),(-tw/2,h-tf),(-tw/2,tf),(-b/2,tf)]
    m.add_lwpolyline(points,close=True,dxfattribs={'layer':'S-OUTLINE'})
    _dimension(m,expected,(-b/2,0),(-b/2,h),(-b/2-12*scale,0),90,scale)
    _dimension(m,expected,(-b/2,0),(b/2,0),(0,-12*scale),0,scale)
    _dimension(m,expected,(-tw/2,h/2),(tw/2,h/2),(0,h+14*scale),0,scale)
    _dimension(m,expected,(b/2,0),(b/2,tf),(b/2+12*scale,0),90,scale)


def _all_text(doc):
    return [e.dxf.text if e.dxftype()=='TEXT' else e.plain_text()
            for layout in doc.layouts for e in layout if e.dxftype() in ('TEXT','MTEXT')]


def _audit_saved(path,expected,scale,font_path,required_ids=()):
    doc=ezdxf.readfile(path); errors=[]; measurements=[]
    if doc.units!=4: errors.append('模型单位不是 mm (INSUNITS=4)')
    native=doc.audit()
    if native.has_errors: errors.append('DXF audit errors: '+str(native.errors))
    dims=list(doc.modelspace().query('DIMENSION'))
    if len(dims)!=len(expected): errors.append('DIMENSION count changed')
    by_handle={e.dxf.handle:e for e in dims}
    for record in expected:
        entity=by_handle.get(record['handle']); actual=entity.get_measurement() if entity else None
        measurements.append(dict(record,actual_mm=actual))
        if actual is None or not math.isclose(actual,record['expected_mm'],rel_tol=1e-9,abs_tol=1e-6): errors.append('原生尺寸实测值不符: '+str(record))
        if entity and entity.dxf.text not in ('','<>'): errors.append('DIMENSION contains text override')
    layout=doc.layouts.get('A3'); paper=[layout.dxf.paper_width,layout.dxf.paper_height]
    if paper!=[420,297]: errors.append('页面不是 A3 420×297 mm')
    scales=[v.dxf.view_height/v.dxf.height for v in layout.viewports() if v.dxf.id>1]
    if scale is not None and (not scales or any(not math.isclose(s,scale) for s in scales)): errors.append('视口比例不符')
    text='\n'.join(_all_text(doc))
    for value in required_ids:
        if value not in text: errors.append('图中文字缺少 ID: '+value)
    font=doc.styles.get('STEELMIND').dxf.font
    if Path(font).name!=font_path.name: errors.append('字体记录不符')
    return {'file':str(path.name),'errors':errors,'measurements':measurements,'modelunits':doc.units,
            'paper_mm':paper,'viewport_scales':scales,'font_filename':font,'local_origin_mm':[0,0],
            'model_entity_count':len(doc.modelspace()),'dimension_count':len(dims)},doc


def _verify_glyphs(doc,font_path):
    from fontTools.ttLib import TTFont
    font=TTFont(font_path,fontNumber=0)
    try: cmap=font.getBestCmap()
    finally: font.close()
    chars=set(''.join(_all_text(doc)))
    # Also validate dimension numerals and renderer substitutions.
    missing=sorted(ch for ch in chars if not ch.isspace() and ord(ch) not in cmap)
    if missing: raise ValueError('字体缺少字形: '+''.join(missing))


def _render_pdf(dxf_path,pdf_path,font_path):
    """The only PDF source is the saved CAD A3 layout, including viewports."""
    with runtime.RENDER_LOCK:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        from ezdxf.addons.drawing.properties import LayoutProperties
        from ezdxf.addons.drawing.config import Configuration, ColorPolicy
        from ezdxf.fonts import fonts
        from ezdxf.fonts.font_manager import get_ttf_font_face
        # A filename in DXF plus a registered absolute path in ezdxf's font
        # cache avoids basename fallback to a Western default.
        fonts.font_manager._font_cache.add_entry(font_path,get_ttf_font_face(font_path))
        doc=ezdxf.readfile(dxf_path); _verify_glyphs(doc,font_path)
        layout=doc.layouts.get('A3')
        fig=plt.figure(figsize=(420/25.4,297/25.4),dpi=150)
        try:
            ax=fig.add_axes([0,0,1,1]); backend=MatplotlibBackend(ax,adjust_figure=False)
            props=LayoutProperties.from_layout(layout); props.set_colors('#ffffff','#000000')
            config=Configuration(color_policy=ColorPolicy.BLACK,min_lineweight=.05)
            Frontend(RenderContext(doc),backend,config=config).draw_layout(layout,layout_properties=props)
            ax.set_xlim(0,420); ax.set_ylim(0,297); ax.set_aspect('equal',adjustable='box')
            fig.savefig(pdf_path,format='pdf',dpi=150,facecolor='white')
        finally: plt.close(fig)
    from pypdf import PdfReader
    pages=PdfReader(pdf_path).pages
    if len(pages)!=1 or not pdf_path.read_bytes().startswith(b'%PDF-'): raise ValueError('CAD PDF 无有效页面')
    if abs(float(pages[0].mediabox.width)-420/25.4*72)>2 or abs(float(pages[0].mediabox.height)-297/25.4*72)>2:
        raise ValueError('CAD PDF 纸张尺寸不符')


# Absolute mm tolerance for CAD roundtrip coordinates; no relative tolerance
# that could admit large movements in models with large global coordinates.
ROUNDTRIP_TOLERANCE = 1e-5
_GEOMETRY_FIELDS = {
    'LINE': ('start','end','thickness','extrusion'),
    'LWPOLYLINE': ('elevation','flags','const_width','thickness','extrusion'),
    'CIRCLE': ('center','radius','thickness','extrusion'),
    'ARC': ('center','radius','start_angle','end_angle','thickness','extrusion'),
    'SOLID': ('vtx0','vtx1','vtx2','vtx3','thickness','extrusion'),
    'TRACE': ('vtx0','vtx1','vtx2','vtx3','thickness','extrusion'),
    'POINT': ('location','thickness','extrusion','angle'),
    'TEXT': ('insert','align_point','height','width','rotation','oblique','style','text',
             'halign','valign','text_generation_flag','extrusion','thickness'),
    'MTEXT': ('insert','char_height','width','rotation','attachment_point','drawing_direction',
              'extrusion','text_direction','line_spacing_style','line_spacing_factor'),
    'DIMENSION': ('defpoint','defpoint2','defpoint3','defpoint4','defpoint5','defpoint6',
                  'text_midpoint','insert','angle','oblique_angle','text_rotation','extrusion',
                  'horizontal_direction','dimtype','text','dimstyle','attachment_point',
                  'text_line_spacing_factor','text_line_spacing_style','leader_length'),
    'VIEWPORT': ('center','width','height','view_center_point','view_height',
                 'view_direction_vector','view_target_point','view_twist_angle',
                 'perspective_lens_length','front_clip_plane_z_value','back_clip_plane_z_value',
                 'ucs_origin','ucs_x_axis','ucs_y_axis','flags','status'),
    'INSERT': ('insert','xscale','yscale','zscale','rotation','extrusion',
               'row_count','column_count','row_spacing','column_spacing'),
}


def _geometry_value(value):
    if isinstance(value,(str,int,float,bool)) or value is None: return value
    return tuple(_geometry_value(v) for v in value)


def _entity_geometry(entity):
    kind=entity.dxftype()
    if kind not in _GEOMETRY_FIELDS:
        raise ValueError('DWG roundtrip has unsupported geometry: '+kind)
    data={key:_geometry_value(getattr(entity.dxf,key,None)) for key in _GEOMETRY_FIELDS[kind]}
    data.update(type=kind,layer=entity.dxf.get('layer','0'))
    if kind=='LWPOLYLINE': data['vertices']=tuple(tuple(float(v) for v in point) for point in entity.get_points('xyseb'))
    if kind=='MTEXT': data['text']=entity.text
    return data


def _geometry_records(doc):
    # Entity handles and ordering are transport details. Anonymous dimension
    # blocks are checked through their actual virtual picture, not block names.
    records=[]
    def collect(entity,scope):
        records.append({'scope':scope,'geometry':_entity_geometry(entity)})
        if entity.dxftype() in ('DIMENSION','INSERT'):
            for child in entity.virtual_entities(): collect(child,scope+'/'+entity.dxftype())
    for layout in doc.layouts:
        for entity in layout: collect(entity,layout.name)
    return records


def _values_equal(a,b):
    if isinstance(a,float) or isinstance(b,float):
        return isinstance(a,(int,float)) and isinstance(b,(int,float)) and math.isclose(a,b,rel_tol=0,abs_tol=ROUNDTRIP_TOLERANCE)
    if isinstance(a,dict) and isinstance(b,dict):
        return a.keys()==b.keys() and all(_values_equal(a[k],b[k]) for k in a)
    if isinstance(a,(tuple,list)) and isinstance(b,(tuple,list)):
        return len(a)==len(b) and all(_values_equal(x,y) for x,y in zip(a,b))
    return a==b


def _same_geometry(a,b):
    # Match a multiset with absolute numeric tolerance, independent of entity
    # order and handles. Grouping prevents unrelated types/layers from matching.
    def group(records):
        result={}
        for record in records:
            g=record['geometry']; key=(record['scope'],g['type'],g['layer'])
            result.setdefault(key,[]).append(g)
        return result
    left,right=group(a),group(b)
    if left.keys()!=right.keys(): return False
    for key,items in left.items():
        remaining=list(right[key])
        if len(items)!=len(remaining): return False
        for item in items:
            match=next((i for i,other in enumerate(remaining) if _values_equal(item,other)),None)
            if match is None: return False
            remaining.pop(match)
    return True


def _semantic_signature(path):
    doc=ezdxf.readfile(path)
    dims=[]
    for e in doc.modelspace().query('DIMENSION'):
        dims.append((e.get_measurement(),e.dxf.text))
    layouts={}
    for layout in doc.layouts:
        if layout.name=='Model': continue
        layouts[layout.name]={'paper':(layout.dxf.paper_width,layout.dxf.paper_height),
            'viewports':sorted((round(v.dxf.width,7),round(v.dxf.height,7),round(v.dxf.view_height,7),
                tuple(round(c,7) for c in v.dxf.view_center_point)) for v in layout.viewports() if v.dxf.id>1)}
    return {'units':doc.units,'model_entities':dict(Counter(e.dxftype() for e in doc.modelspace())),
        'dimensions':sorted(dims),'texts':sorted(_all_text(doc)),
        'geometry':_geometry_records(doc),
        'entity_lineweights':sorted((layout.name,e.dxftype(),e.dxf.get('layer','0'),e.dxf.get('lineweight',-1))
            for layout in doc.layouts for e in layout),
        'styles':sorted((s.dxf.name,s.dxf.font,s.dxf.get('bigfont','')) for s in doc.styles),
        'layers':sorted((l.dxf.name,l.dxf.lineweight,l.dxf.color,l.dxf.linetype,l.dxf.plot) for l in doc.layers),
        'layouts':layouts}


def compare_roundtrip(original:Path,roundtrip:Path)->list[str]:
    """Reject lossy ODA output before publishing its corresponding DWG."""
    try:
        a,b=_semantic_signature(original),_semantic_signature(roundtrip)
        errors=[f'DWG 往返校核不符: {key}' for key in a
                if not (_same_geometry(a[key],b[key]) if key=='geometry' else _values_equal(a[key],b[key]))]
        doc=ezdxf.readfile(roundtrip)
        if doc.audit().has_errors: errors.append('DWG 往返 DXF audit failed')
        if any(e.dxf.text not in ('','<>') for e in doc.modelspace().query('DIMENSION')):
            errors.append('DWG 往返尺寸包含文字替代')
        return errors
    except Exception as exc: return ['DWG 往返 DXF 无效: '+str(exc)]


def _find_oda():
    configured=os.environ.get('STEELMIND_ODA') or os.environ.get('ODA_FILE_CONVERTER')
    if configured:
        found=shutil.which(configured)
        if found: return found
        raise FileNotFoundError('ODA 配置路径无效；设置 STEELMIND_ODA 为 ODAFileConverter 可执行文件。')
    candidates=[shutil.which('ODAFileConverter'),shutil.which('ODAFileConverter.exe'),
        '/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter',
        '/Applications/ODAFileConverter/ODAFileConverter.app/Contents/MacOS/ODAFileConverter']
    programfiles=Path(os.environ.get('PROGRAMFILES','C:/Program Files'))
    candidates+=list((programfiles/'ODA').glob('ODAFileConverter*/ODAFileConverter.exe'))
    for item in candidates:
        if item and Path(item).is_file(): return str(item)
    raise FileNotFoundError('未找到 ODAFileConverter；DXF 已保留。安装 ODA 或设置 STEELMIND_ODA。')


def _convert_dwg(dxf_path,exe):
    # Converter arguments and filenames are operator controlled; user metadata
    # never reaches an executable or shell. ASCII temporary paths isolate ODA.
    with tempfile.TemporaryDirectory(prefix='steelmind-oda-',dir='/tmp' if Path('/tmp').is_dir() else None) as tmp:
        base=Path(tmp); source=base/'in'; target=base/'dwg'; back=base/'back'
        for p in (source,target,back): p.mkdir()
        shutil.copyfile(dxf_path,source/'drawing.dxf')
        for a,b,kind in ((source,target,'DWG'),(target,back,'DXF')):
            completed=subprocess.run([exe,str(a),str(b),'ACAD2018',kind,'0','1','*.dxf' if kind=='DWG' else '*.dwg'],
                shell=False,capture_output=True,timeout=180,check=False)
            if completed.returncode: raise RuntimeError('ODA 转换失败: '+completed.stderr.decode('utf-8','replace')[-400:])
        dwg=target/'drawing.dwg'; roundtrip=back/'drawing.dxf'
        if not dwg.is_file() or dwg.stat().st_size<32 or dwg.read_bytes()[:6]!=b'AC1032':
            raise RuntimeError('ODA 未生成有效 AC1032 DWG')
        if not roundtrip.is_file(): raise RuntimeError('ODA 未生成往返 DXF')
        errors=compare_roundtrip(dxf_path,roundtrip)
        if errors: raise RuntimeError('; '.join(errors))
        dest=dxf_path.with_suffix('.dwg'); shutil.copyfile(dwg,dest)
        return dest


def _table_pages(rows,headers,widths):
    """Page both records and exceptionally long cells, retaining each character."""
    pages=[]; page=[]; remaining=162.
    for row in rows:
        wrapped=[_wrap(value,width-5,2.7) for value,width in zip(row,widths)]
        count=max(map(len,wrapped)); start=0
        while start<count:
            available=min(12-len(page),int((remaining-4)/4))
            if available<1:
                pages.append(page); page=[]; remaining=162.; continue
            lines=min(count-start,available,32)
            chunk=[cell[start:start+lines] for cell in wrapped]
            height=max(12.,lines*4.+4.)
            if height>remaining:
                pages.append(page); page=[]; remaining=162.; continue
            page.append((chunk,height)); remaining-=height; start+=lines
            if len(page)>=12:
                pages.append(page); page=[]; remaining=162.
    if page: pages.append(page)
    return pages or [[]]


def _draw_table(layout,headers,widths,rows):
    x0=30; top=251; total=sum(widths)
    for x,y in [((x0,top),(x0+total,top)),((x0,top-10),(x0+total,top-10))]: _line(layout,x,y,'P-FRAME')
    x=x0
    for label,width in zip(headers,widths):
        _text(layout,label,x+2,top-7,2.7); x+=width
    y=top-10
    for cells,height in rows:
        x=x0
        for lines,width in zip(cells,widths):
            for i,line in enumerate(lines): _text(layout,line,x+2,y-5-i*4,2.7)
            x+=width
        y-=height; _line(layout,(x0,y),(x0+total,y),'P-FRAME')
    x=x0
    for width in [0]+widths:
        x+=width; _line(layout,(x,top),(x,y),'P-FRAME')


def _export_design_files(bundle:DesignBundle,validation:ValidationReport,out:Path,options:GenerationOptions)->ExportOutcome:
    outcome=ExportOutcome(); out=Path(out); cad=out/'cad'; cad.mkdir(parents=True,exist_ok=True)
    audit={'schema_version':'1.0','sheets':[],'errors':[],'dwg':{'status':'disabled' if not options.include_dwg else 'requested'},
           'font':{},'coordinate_transform':'model_mm = input_m * 1000; no translation',
           'pdf_source':'saved DXF A3 paperspace via ezdxf Frontend / matplotlib Agg'}
    try:
        font_path,family=runtime.resolve_font(); audit['font']={'file':str(font_path),'family':family}
        from ezdxf.fonts import fonts
        from ezdxf.fonts.font_manager import get_ttf_font_face
        fonts.font_manager._font_cache.add_entry(font_path,get_ttf_font_face(font_path))
        _TEXT_METRIC.set(fonts.sideload_ttf(font_path,cap_height=1.0))
    except Exception as exc:
        outcome.errors.append('CAD 字体不可用: '+str(exc)); audit['errors']=outcome.errors
        path=out/'drawing_audit.json'; path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8'); outcome.files.append(path)
        return outcome

    def save(doc,filename,expected,scale,required=(),extra=None):
        path=cad/filename
        try:
            doc.saveas(path); outcome.files.append(path)
            record,_=_audit_saved(path,expected,scale,font_path,required)
            if extra: record.update(extra)
            audit['sheets'].append(record)
            outcome.errors.extend(f'{filename}: {error}' for error in record['errors'])
            record['pdf_status']='disabled'
            if options.include_pdf:
                pdf=path.with_suffix('.pdf')
                try: _render_pdf(path,pdf,font_path); outcome.files.append(pdf); record['pdf_status']='verified'
                except Exception as exc:
                    pdf.unlink(missing_ok=True); record['pdf_status']='failed'; record['errors'].append('PDF: '+str(exc)); outcome.errors.append(f'{filename} PDF 失败: {exc}')
        except Exception as exc: outcome.errors.append(f'{filename} DXF 失败: {exc}')

    try:
        tiles=_frame_tiles(bundle)
        for group,title,assign in [('01','框架几何布置图',False),('02','构件编号与截面分配图',True)]:
            for index,(center,scale,tile) in enumerate(tiles,1):
                doc,layout=_new_doc(font_path); expected=[]
                _sheet_frame(layout,bundle,validation,title,f'{group}-{index:03}',f'1:{scale}')
                _frame_model(doc,bundle,scale,expected,assign)
                _viewport(layout,VIEW_RECT,center,scale)
                col,row,nx,ny=tile
                bounds=[center[0]-180*scale,center[1]-90*scale,center[0]+180*scale,center[1]+90*scale]
                if nx*ny>1: _text(layout,f'分幅 {col}/{nx}, {row}/{ny}  视窗 mm: '+','.join(f'{v:g}' for v in bounds),30,76,2.5)
                required=[n.id for n in bundle.model.nodes]+[m.id for m in bundle.model.members]
                if assign: required += [m.section_id for m in bundle.model.members]
                save(doc,f'{group}_{index:03}_{title}.dxf',expected,scale,required,{'logical_group':group,'tile':list(tile),'viewport_bounds_mm':bounds})
        rows=[(m.id,m.node_i+' → '+m.node_j,m.section_id+' / '+next(s.name for s in bundle.model.sections if s.id==m.section_id),
               m.material_id+' / '+next(a.name for a in bundle.model.materials if a.id==m.material_id),
               f'I:{int(m.release_i)} J:{int(m.release_j)}') for m in bundle.model.members]
        headers=['构件 ID','I → J 节点','截面 ID / 名称','材料 ID / 名称','转动释放 1=是']; widths=[42,55,105,105,53]
        for index,page in enumerate(_table_pages(rows,headers,widths),1):
            doc,layout=_new_doc(font_path); title='构件表与材料分配'
            _sheet_frame(layout,bundle,validation,title,f'02-T{index:03}')
            _draw_table(layout,headers,widths,page)
            save(doc,f'02_T{index:03}_构件表.dxf',[],None,extra={'logical_group':'02','table':'member_assignments'})
        for index,section in enumerate(bundle.model.sections,1):
            doc,layout=_new_doc(font_path); expected=[]
            needed=max(section.b_mm/120,section.h_mm/100)
            scale=next((s for s in (1,2,5,10,20,50,100,200,500,1000,2000,5000,10000,100000) if s>=needed),None)
            if scale is None: raise ValueError(f'截面 {section.id} 超出支持的比例范围')
            title='截面示意及构件表'
            _sheet_frame(layout,bundle,validation,title,f'03-{index:03}',f'1:{scale}')
            _section_model(doc,section,scale,expected)
            _viewport(layout,(30,90,215,251),(0,section.h_mm/2),scale)
            heading=section.id+' / '+section.name
            if len(_wrap(heading,160,3.0))>2: heading=section.id+' / 名称见项目资料页'
            _paragraph(layout,heading,235,246,160,3.0)
            y=236
            for field in ('shape','h_mm','b_mm','tw_mm','tf_mm','A_mm2','Ix_mm4','Iy_mm4','Wx_mm3','Wy_mm3','property_basis'):
                y=_paragraph(layout,f'{field}: {getattr(section,field)}',235,y,160,2.7)-2
            y=_paragraph(layout,'简化示意未表示轧制圆角',235,y,160,2.7)-2
            # All source strings are retained in the metadata table; bounded
            # outline view never forces the frame viewport to huge extents.
            _text(layout,'source 详见项目资料页；构件分配见构件表。',235,89,2.5)
            save(doc,f'03_{index:03}_截面示意.dxf',expected,scale,[section.id],{'logical_group':'03','section_id':section.id,'local_origin_mm':[0,0]})
        meta=[('项目',key,str(getattr(bundle.project,key))) for key in ('name','phase','designer','institution','student_id','date')]
        for s in bundle.model.sections: meta.extend([('截面 '+s.id,'name',s.name),('截面 '+s.id,'source',s.source),('截面 '+s.id,'property_basis',s.property_basis)])
        for m in bundle.model.materials: meta.extend([('材料 '+m.id,'name',m.name),('材料 '+m.id,'source',m.source),('材料 '+m.id,'E_MPa / fy_MPa',f'{m.E_MPa} / {m.fy_MPa}')])
        headers=['对象','字段','输入原文（留空字段保持空白）']; widths=[60,70,230]
        for index,page in enumerate(_table_pages(meta,headers,widths),1):
            doc,layout=_new_doc(font_path); _sheet_frame(layout,bundle,validation,'项目资料与来源',f'03-M{index:03}')
            _draw_table(layout,headers,widths,page)
            save(doc,f'03_M{index:03}_项目资料.dxf',[],None,extra={'logical_group':'03','table':'metadata'})
    except Exception as exc:
        outcome.errors.append('CAD 场景生成失败: '+str(exc))
    if options.include_dwg:
        try:
            exe=_find_oda(); audit['dwg']['executable']=exe; audit['dwg']['files']=[]
            for path in list(outcome.files):
                if path.suffix!='.dxf': continue
                try:
                    dwg=_convert_dwg(path,exe); outcome.files.append(dwg); audit['dwg']['files'].append(dwg.name)
                except Exception as exc: outcome.errors.append(f'{path.name} DWG 失败: {exc}')
            audit['dwg']['status']='failed' if any('DWG' in e for e in outcome.errors) else 'verified'
        except Exception as exc: outcome.errors.append('DWG 请求失败: '+str(exc)); audit['dwg']['status']='unavailable'
    audit['errors']=list(outcome.errors)
    path=out/'drawing_audit.json'; path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8'); outcome.files.append(path)
    return outcome


def export_design_files(bundle:DesignBundle,validation:ValidationReport,out:Path,options:GenerationOptions)->ExportOutcome:
    # ezdxf's glyph/dimension metrics and Matplotlib share font caches. Keep
    # metric initialization, native DIMENSION rendering and PDF rendering safe.
    with runtime.RENDER_LOCK:
        token=_TEXT_METRIC.set(None)
        try:
            return _export_design_files(bundle,validation,out,options)
        finally:
            _TEXT_METRIC.reset(token)
