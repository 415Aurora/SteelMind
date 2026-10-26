from steelmind_export.examples import minimal_bundle
from steelmind_export.validation import validate_bundle


def test_empty_structural_model_is_not_exportable():
    bundle = minimal_bundle()
    bundle["model"] = {"nodes": [], "members": [], "materials": [], "sections": [], "supports": []}
    assert not validate_bundle(bundle).valid


def test_finite_extreme_section_values_return_validation_error_not_exception():
    bundle = minimal_bundle()
    bundle["model"]["sections"][0]["h_mm"] = 1e308
    report = validate_bundle(bundle)
    assert not report.valid


def test_overflowing_coordinate_difference_is_not_a_valid_length():
    bundle = minimal_bundle()
    bundle["model"]["nodes"][0]["x_m"] = -1e308
    bundle["model"]["nodes"][1]["x_m"] = 1e308
    assert not validate_bundle(bundle).valid
