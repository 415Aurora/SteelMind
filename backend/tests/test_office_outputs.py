import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def test_office_outputs_refuses_unfinished_analysis_and_never_creates_fake_book(tmp_path):
 import pytest
 from office_outputs import write_office_outputs
 with pytest.raises(ValueError):write_office_outputs({'ok':False,'status':'analysis_failed'},tmp_path)
 assert not list(tmp_path.glob('*.docx'))


def test_sheet_values_are_text_not_executable_input_formulas():
 from office_outputs import sheet_value
 assert sheet_value('=HYPERLINK("evil")').startswith("'")
 assert sheet_value(1e-8)==1e-8


def test_only_actual_model_views_are_offered_for_planar_cad_preview():
 from office_outputs import artifact_preview
 assert artifact_preview('80_构件表_01.dxf',{'80_构件表_01.dxf':'schedule'})=='download_only'
 assert artifact_preview('90_原始XYZ空间杆系.dxf',{})=='download_only'
 assert artifact_preview('01_平面.dxf',{'01_平面.dxf':'plan'})=='planar'
