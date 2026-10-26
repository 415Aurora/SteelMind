"""Version 1.0 exchange contract. Numbers carry fixed units in field names.

End actions are forces ON the member. Local x runs I→J and local y is the
left normal. On the positive-x section face N is +x tension, V is -y, M is
counterclockwise (positive sagging). Interior section values are
I: (-Ni, Vi, -Mi), J: (Nj, -Vj, Mj). Releases are rotational only.
"""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Identifier = Annotated[str, Field(min_length=1)]
Scalar = str | Number


class ContractModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class Project(ContractModel):
    name: Identifier
    phase: str = '方案设计'
    designer: str = ''
    institution: str = ''
    student_id: str = ''
    date: str = ''
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class Provenance(ContractModel):
    data_kind: Literal['demonstration', 'analytic_benchmark', 'upstream']
    tool_versions: dict[str, str] = Field(default_factory=dict)
    source: str = ''
    run_id: str = ''


class Node(ContractModel):
    id: Identifier
    x_m: Number
    y_m: Number


class Material(ContractModel):
    id: Identifier
    name: str
    E_MPa: Number
    fy_MPa: Number
    source: str


class Section(ContractModel):
    id: Identifier
    name: str
    shape: Literal['H', 'I']
    h_mm: Number
    b_mm: Number
    tw_mm: Number
    tf_mm: Number
    A_mm2: Number
    Ix_mm4: Number
    Iy_mm4: Number
    Wx_mm3: Number
    Wy_mm3: Number
    property_basis: Literal['idealized', 'catalog']
    source: str


class Member(ContractModel):
    id: Identifier
    node_i: Identifier
    node_j: Identifier
    section_id: Identifier
    material_id: Identifier
    kind: Literal['beam', 'column']
    release_i: bool = False
    release_j: bool = False


class Support(ContractModel):
    node_id: Identifier
    ux: bool
    uy: bool
    rz: bool


class Model(ContractModel):
    nodes: list[Node] = Field(min_length=2)
    members: list[Member] = Field(min_length=1)
    materials: list[Material] = Field(min_length=1)
    sections: list[Section] = Field(min_length=1)
    supports: list[Support] = Field(default_factory=list)


class NodalLoad(ContractModel):
    kind: Literal['nodal']
    target_id: Identifier
    fx_kN: Number | None = None
    fy_kN: Number | None = None
    mz_kNm: Number | None = None


class UniformMemberLoad(ContractModel):
    """Uniform loading in member LOCAL axes, force per actual member length."""
    kind: Literal['uniform_member']
    target_id: Identifier
    qx_kN_m: Number | None = None
    qy_kN_m: Number | None = None


Load = Annotated[NodalLoad | UniformMemberLoad, Field(discriminator='kind')]


class LoadCase(ContractModel):
    id: Identifier
    name: str
    kind: Literal['permanent', 'variable', 'other']
    source: str
    loads: list[Load] = Field(default_factory=list)


class Combination(ContractModel):
    id: Identifier
    name: str
    factors: dict[Identifier, Number]
    limit_state: Literal['ULS', 'SLS', 'ANALYSIS']
    source: str


class NodeDisplacement(ContractModel):
    node_id: Identifier
    combination_id: Identifier
    ux_mm: Number
    uy_mm: Number
    rz_rad: Number


class Reaction(ContractModel):
    node_id: Identifier
    combination_id: Identifier
    fx_kN: Number
    fy_kN: Number
    mz_kNm: Number


class MemberEndForces(ContractModel):
    member_id: Identifier
    combination_id: Identifier
    Ni_kN: Number
    Vi_kN: Number
    Mi_kNm: Number
    Nj_kN: Number
    Vj_kN: Number
    Mj_kNm: Number


class MemberSample(ContractModel):
    member_id: Identifier
    combination_id: Identifier
    x_m: Number
    side: Literal['left', 'right', 'single']
    N_kN: Number
    V_kN: Number
    M_kNm: Number


class Analysis(ContractModel):
    node_displacements: list[NodeDisplacement] = Field(default_factory=list)
    reactions: list[Reaction] = Field(default_factory=list)
    member_end_forces: list[MemberEndForces] = Field(default_factory=list)
    member_samples: list[MemberSample] = Field(default_factory=list)


class Check(ContractModel):
    id: Identifier
    target_id: Identifier
    combination_id: Identifier
    item: Identifier
    status: Literal['PASS', 'FAIL', 'NA']
    demand: Number | None = None
    limit: Number | None = None
    comparator: Literal['<=', '>=', 'abs<='] = '<='
    unit: Literal['MPa', 'kN', 'kN*m', 'mm', 'rad', 'ratio']
    utilization: Number | None = None
    formula_text: str = ''
    substitution: str = ''
    source: str = ''
    clause: str = ''
    trace_ids: list[Identifier] = Field(default_factory=list)
    na_reason: str = ''


class Trace(ContractModel):
    id: Identifier
    name: str
    formula_text: str
    inputs: dict[str, Scalar] = Field(default_factory=dict)
    intermediate: list[str] = Field(default_factory=list)
    result: Scalar
    unit: str
    source: str
    result_path: str


class DesignBundle(ContractModel):
    schema_version: Literal['1.0']
    project: Project
    model: Model
    load_cases: list[LoadCase] = Field(default_factory=list)
    combinations: list[Combination] = Field(default_factory=list)
    analysis: Analysis = Field(default_factory=Analysis)
    checks: list[Check] = Field(default_factory=list)
    traces: list[Trace] = Field(default_factory=list)
    provenance: Provenance
