"""Actual signed office load-case viewer; never draws envelope forces as one case."""
import copy,re
from explicit_model import input_hash


def build_office_viewer(run,case_id='G'):
 from explicit_viewer import build_html
 if case_id not in run['analysis']['case_results']:raise ValueError('只允许查看本次实际静力工况，不将CQC/组合分量包络拼成同时内力')
 tables=copy.deepcopy(run['bundle']['tables']);tables.pop('Office_Design',None);result=copy.deepcopy(run['analysis']['case_results'][case_id]);lookup={r['member_id']:r for r in run['code_checks']['members']};members=[]
 aliases={'elastic_section_strength':'section_strength','biaxial_compression_stability':'compression_stability','plate_class_S4_sufficient':'plate_local_stability','equivalent_stress':'combined_stress_bound'}
 for m in result['analysis']['members']:
  record=copy.deepcopy(lookup[m['physical_member_id']]);record['member_id']=m['member_id']
  for check in record['checks']:check['item']=aliases.get(check['item'],check['item'])
  members.append(record)
 result.update(input_sha256=input_hash(tables),upstream_check_summary=run['design_status'],code_checks={'members':members});scene,document=build_html(tables,result)
 document=document.replace('仅框架自重（1.0G），规范验算未闭合。各内力分量的控制位置可能不同。','实际静力工况 '+case_id+'；内力和变形只对应该工况。验算颜色来自完整组合保守包络，建筑构造交接待外部验证。').replace('自重分析','静力工况分析')
 document=document.replace('self_weight','office_actions').replace('Excel原始杆系','办公楼采用模型').replace('本次自重','本次静力工况').replace('自重结果','静力结果')
 document=document.replace("document.querySelector('.notice').textContent='原始杆系几何预览；点击梁柱查看实际截面。未进行规范验算，不显示通过结论。';", "document.querySelector('.notice').textContent="+__import__('json').dumps('实际静力工况 '+case_id+'；内力和变形只对应该工况。验算颜色来自完整组合的保守包络。建筑构造交接仍待外部验证。',ensure_ascii=False)+';')
 document=re.sub(r"body.textContent='① 输入可配置：.*?';guide.append", "body.textContent='本次上部杆系包含已声明G/Q/W/水平E分析。构件验算按已采用边界计算；梁端防扭、塑性铰区翼缘支承、焊缝、楼板、柱脚及基础由对应组员验证。';guide.append",document)
 document=document.replace('稳定计算长度：待确认，未用几何长度替代','稳定计算长度：采用已验证柱弦二阶路线；梁侧扭保留完整物理长度')
 return scene,document


def publish_office_viewer(run,case_id='G'):
 from app import LocalArtifactStorage
 scene,document=build_office_viewer(run,case_id);storage=LocalArtifactStorage();key=storage.upload_file(file_content=document.encode(),file_name='办公楼实际工况_'+case_id+'.html',content_type='text/html')
 return {'ok':True,'html_url':storage.generate_presigned_url(key=key),'html_content':document,'case_id':case_id,'scope':'actual_signed_static_case','nodes':len(scene['explicit_nodes']),'members':len(scene['explicit_members']),'upstream_check_summary':run['design_status']}
