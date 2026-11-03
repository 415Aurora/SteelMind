"""Shape preflight for legacy XY and current X/Z frame inputs; no padding."""
import math

def analysis_shape_errors(request):
    g=request.get('geometry') or {};loads=request.get('loads') or {};errors=[];counts={}
    x_key='bays_x' if 'bays_x' in g else 'bays'
    for key,default in [(x_key,None),('bays_z',1),('stories',None)]:
        value=g.get(key,default)
        try:
            number=float(value)
            if isinstance(value,bool) or not math.isfinite(number) or not number.is_integer() or not 1<=number<=30:raise ValueError()
            counts[key]=int(number)
        except (ValueError,TypeError,OverflowError):errors.append(f'geometry.{key} 必须是1至30的整数；当前值={value!r}')
    def active(block,*keys):
        return next((key for key in keys if block.get(key) not in (None,[])),keys[-1])
    fields=[(g,active(g,'bay_widths_x_m','bay_widths_m'),x_key,'geometry',True),(g,'bay_widths_z_m','bays_z','geometry',True),(g,'story_heights_m','stories','geometry',True)]
    for key in ['q_by_story_kN_per_m',active(loads,'q_z_by_story_kN_per_m','q_by_story_z_kN_per_m'),active(loads,'lateral_x_by_story_kN','lateral_by_story_kN'),'lateral_z_by_story_kN']:
        fields.append((loads,key,'stories','loads',False))
    for block,key,count_key,prefix,empty_fallback in fields:
        value=block.get(key);count=counts.get(count_key)
        if not count or value is None or (empty_fallback and value==[]):continue
        if isinstance(value,list) and len(value)!=count:
            errors.append(f'{prefix}.{key} 当前有{len(value)}项，但geometry.{count_key}={count}，需要{count}项。请逐跨/逐层填写；不会自动复制或补零。')
    return errors
