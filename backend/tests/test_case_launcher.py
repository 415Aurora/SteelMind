import os,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class CaseLauncher(unittest.TestCase):
 def fixture(self,folder,python_ok=True):
  root=Path(folder)/'space project';(root/'scripts').mkdir(parents=True);shutil.copy2(ROOT/'scripts/run_longyan_case.sh',root/'scripts/run_longyan_case.sh');(root/'scripts/run_longyan_case.py').write_text('')
  py=root/'.venv/bin/python';py.parent.mkdir(parents=True);py.write_text('#!/bin/bash\nif [[ "$2" == "-c" ]]; then exit '+('0' if python_ok else '1')+'; fi\nprintf "%s\\n" "$@" > "$CASE_TEST_TRACE"\nprintf "%s" "${PYTHONPATH-unset}" >> "$CASE_TEST_TRACE"\n');py.chmod(0o755);return root
 def test_uses_project_environment_and_preserves_quoted_arguments(self):
  with tempfile.TemporaryDirectory() as d:
   root=self.fixture(d);env=dict(os.environ,CASE_TEST_TRACE=str(Path(d)/'trace'),PYTHONPATH='/unwanted');env.pop('STEELMIND_CASE_PYTHON',None)
   p=subprocess.run(['bash',str(root/'scripts/run_longyan_case.sh'),'--verify-only','--output',str(Path(d)/'output with space')],env=env,capture_output=True,text=True)
   self.assertEqual(p.returncode,0,p.stderr);trace=(Path(d)/'trace').read_text();self.assertIn('-I\n',trace);self.assertIn('output with space',trace);self.assertNotIn('/unwanted',trace)
 def test_missing_environment_never_installs_or_uses_global_python(self):
  with tempfile.TemporaryDirectory() as d:
   root=self.fixture(d);shutil.rmtree(root/'.venv');env=dict(os.environ);env.pop('STEELMIND_CASE_PYTHON',None)
   p=subprocess.run(['bash',str(root/'scripts/run_longyan_case.sh')],env=env,capture_output=True,text=True);self.assertEqual(p.returncode,2);self.assertIn('虚拟环境',p.stderr);self.assertFalse((root/'backend').exists())
 def test_non_virtual_interpreter_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=self.fixture(d,False);env=dict(os.environ);env.pop('STEELMIND_CASE_PYTHON',None)
   p=subprocess.run(['bash',str(root/'scripts/run_longyan_case.sh')],env=env,capture_output=True,text=True);self.assertEqual(p.returncode,2);self.assertIn('虚拟环境',p.stderr)
