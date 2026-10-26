from pathlib import Path
import subprocess
from unittest.mock import patch
from zipfile import ZipFile
from copy import deepcopy
import pytest

from steelmind_export import generate_calculation_book, validate_bundle
from steelmind_export.examples import minimal_bundle, analytic_bundle
from steelmind_export.coverage import required_checks
from steelmind_export.models import DesignBundle


def complete_records():
    bundle = analytic_bundle()
    bundle['provenance'].update(data_kind='upstream', source='Reviewed fixture snapshot', run_id='upstream-001', tool_versions={'solver':'1.0'})
    present = {(c['target_id'], c['combination_id'], c['item']) for c in bundle['checks']}
    for target, combo, item in required_checks(DesignBundle.model_validate(bundle)):
        if (target, combo, item) not in present:
            bundle['checks'].append(dict(id='NA_'+item, target_id=target,combination_id=combo,item=item,status='NA',
                unit='ratio',na_reason='Explicit fixture scope exclusion',formula_text='Not applicable',substitution='Not applicable',
                source='Reviewed scope',clause='Fixture scope1',trace_ids=['T_STRESS']))
    return bundle


def test_incomplete_analysis_cannot_lose_draft_warning():
    bundle = complete_records()
    assert not validate_bundle(bundle).draft
    bundle['analysis']['member_end_forces'] = bundle['analysis']['member_end_forces'][:1]
    bundle['analysis']['node_displacements'] = bundle['analysis']['node_displacements'][:1]
    report = validate_bundle(bundle)
    assert report.valid and report.draft
    assert any(i.code == 'analysis_coverage_missing' for i in report.warnings)


def test_blank_upstream_provenance_is_not_a_final_report():
    bundle = complete_records()
    bundle['provenance'].update(source='', run_id='', tool_versions={})
    report = validate_bundle(bundle)
    assert report.valid and report.draft
    assert any(i.code == 'provenance_missing' for i in report.warnings)


def test_benchmark_remains_draft_even_if_record_coverage_complete():
    bundle = complete_records()
    bundle['provenance']['data_kind'] = 'analytic_benchmark'
    assert validate_bundle(bundle).draft


@pytest.mark.parametrize('side', ['left', 'right'])
def test_single_and_one_sided_sample_at_same_station_are_rejected(side):
    bundle = analytic_bundle()
    extra = deepcopy(bundle['analysis']['member_samples'][0])
    extra.update(side=side, V_kN=999)
    bundle['analysis']['member_samples'].append(extra)
    report = validate_bundle(bundle)
    assert not report.valid
    assert any(i.code == 'sample_side_conflict' for i in report.errors)


def test_failed_converter_pdf_is_neither_published_nor_archived(tmp_path):
    def fail_after_partial_write(args, **kwargs):
        directory = Path(args[args.index('--outdir') + 1])
        (directory / '计算书.pdf').write_bytes(b'partial invalid PDF bytes')
        return subprocess.CompletedProcess(args, 1, b'', b'converter failed')
    with patch('steelmind_export.runtime.subprocess.run', side_effect=fail_after_partial_write):
        result = generate_calculation_book(minimal_bundle(), {}, tmp_path)
    assert result.generation_status == 'partial'
    assert not any(a.name.endswith('.pdf') for a in result.artifacts)
    run = tmp_path / result.run_id
    assert not (run / 'reports/计算书.pdf').exists()
    with ZipFile(run / '成果包.zip') as archive:
        assert not any(name.endswith('.pdf') for name in archive.namelist())


def test_unregistered_stage_files_are_not_published(tmp_path, monkeypatch):
    import steelmind_export.reports as reports
    original = reports.export_calculation_book
    def exporter(bundle, validation, out, options):
        result = original(bundle, validation, out, options)
        (out / 'unregistered.pdf').write_bytes(b'invalid unregistered PDF')
        return result
    monkeypatch.setattr(reports, 'export_calculation_book', exporter)
    result = generate_calculation_book(minimal_bundle(), {'include_pdf': False}, tmp_path)
    assert result.generation_status == 'success'
    assert not any(a.name == 'unregistered.pdf' for a in result.artifacts)
    with ZipFile(tmp_path / result.run_id / '成果包.zip') as archive:
        assert 'unregistered.pdf' not in archive.namelist()
