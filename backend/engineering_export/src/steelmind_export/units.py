"""Explicit conversions used at drawing and calculation boundaries."""
def mm_to_m(value: float) -> float:
    return value / 1000


def m_to_mm(value: float) -> float:
    return value * 1000


def N_to_kN(value: float) -> float:
    return value / 1000


def Nmm_to_kNm(value: float) -> float:
    return value / 1_000_000
