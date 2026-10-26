"""Teaching coverage profile, not a statement of engineering completeness."""
from .models import DesignBundle

COVERAGE_PROFILE = 'steel-frame-teaching-v1'
SUPPORTED_ITEMS = {'strength', 'stability', 'deflection', 'drift'}


def required_checks(bundle: DesignBundle) -> list[tuple[str, str, str]]:
    required = []
    for combo in bundle.combinations:
        for member in bundle.model.members:
            if combo.limit_state == 'ULS':
                required.extend((member.id, combo.id, item) for item in ('strength', 'stability'))
            elif member.kind == 'beam':
                required.append((member.id, combo.id, 'deflection'))
        if combo.limit_state == 'SLS':
            required.append(('FRAME', combo.id, 'drift'))
    return required


def missing_checks(bundle: DesignBundle) -> list[tuple[str, str, str]]:
    present = {(c.target_id, c.combination_id, c.item) for c in bundle.checks
               if c.status != 'NA' or c.na_reason.strip()}
    return [key for key in required_checks(bundle) if key not in present]
