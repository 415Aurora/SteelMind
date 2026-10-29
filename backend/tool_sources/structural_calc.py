"""钢结构框架结构计算工具。

依据中国现行规范实现：
- GB 50009-2012《建筑结构荷载规范》- 荷载组合
- GB 50017-2017《钢结构设计标准》- 构件验算
- GB 50011-2010《建筑抗震设计规范》- 地震作用组合
"""

from __future__ import annotations

import json
import math
from typing import Dict, Optional

from langchain.tools import tool
from section_catalog import catalog_info, search_sections, section_properties, section_record

# ------------------------- 材料强度设计值 (GB50017-2017 表4.4.1) -------------------------
# steel -> (fy 屈服强度, f 抗拉/压/弯强度设计值, fv 抗剪强度设计值) 单位 N/mm² (t<=16mm)
MATERIALS: Dict[str, tuple] = {
    "Q235": (235, 215, 125),
    "Q355": (355, 305, 175),
    "Q390": (390, 345, 195),
}


@tool
def validate_steel_frame_parameters(payload: str) -> str:
    """校验钢框架初选工作流的几何、荷载、材料和截面候选参数；不代替设计审查。"""
    try:
        data = json.loads(payload)
        geometry = data.get("geometry") or {}
        loads = data.get("loads") or {}
        material = data.get("material") or {}
        sections = data.get("model_sections") or {}
        candidates = data.get("candidate_sections") or {}
        errors = []
        for key in ("bays", "stories"):
            value = int(geometry.get(key, 0))
            if value < 1:
                errors.append(f"geometry.{key} 必须是正整数")
        bays, stories = int(geometry.get("bays", 0)), int(geometry.get("stories", 0))
        widths = geometry.get("bay_widths_m") or [geometry.get("bay_m")]
        heights = geometry.get("story_heights_m") or [geometry.get("height_m")]
        if len(widths) not in (1, bays) or any(v in (None, "") or float(v) <= 0 for v in widths):
            errors.append("各跨跨度必须为正数，数量为 1 或与跨数一致")
        if len(heights) not in (1, stories) or any(v in (None, "") or float(v) <= 0 for v in heights):
            errors.append("各层层高必须为正数，数量为 1 或与层数一致")
        if loads.get("dead") in (None, "") or loads.get("live") in (None, ""):
            errors.append("初选流程要求提供恒载 loads.dead 与活载 loads.live，才能执行荷载组合")
        for key in ("dead", "live", "wind", "seismic"):
            if loads.get(key) not in (None, "") and float(loads[key]) < 0:
                errors.append(f"loads.{key} 不能为负值")
        q = loads.get("q_by_story_kN_per_m", loads.get("q_kNm"))
        if q is None:
            errors.append("请提供用于 OpenSees 初算的 loads.q_by_story_kN_per_m")
        elif isinstance(q, list) and (len(q) not in (1, stories) or any(float(v) < 0 for v in q)):
            errors.append("逐层线荷载应为非负数，数量为 1 或与层数一致")
        if not material.get("steel_grade"):
            errors.append("请填写 material.steel_grade")
        for role in ("beam", "column"):
            initial = sections.get(f"{role}_section")
            names = candidates.get(role)
            initial_record = section_record(str(initial)) if initial else None
            candidate_ids = [section_record(str(name))["id"] for name in (names if isinstance(names, list) else [])
                             if section_record(str(name))]
            if not initial or not isinstance(names, list) or not initial_record or initial_record["id"] not in candidate_ids:
                errors.append(f"{role}初始截面需填写，且须包含在 candidate_sections.{role} 中")
            if initial and not initial_record:
                errors.append(f"{role}初始截面 {initial} 不在本地合并截面库中；请使用热轧截面 H-型号或焊接Q235截面 WH-型号")
            if isinstance(names, list):
                unknown = [str(name) for name in names if not section_record(str(name))]
                if unknown:
                    errors.append(f"{role}候选截面不在本地截面库中：{', '.join(unknown[:8])}")
        return json.dumps({"ok": not errors, "status": "valid" if not errors else "invalid",
                           "errors": errors, "geometry": geometry,
                           "message": "字段与基本取值检查通过；仍需确认单位、荷载工况及模型假定。" if not errors else "参数校验未通过。"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "status": "invalid", "errors": [f"参数无法解析或字段格式错误：{exc}"]}, ensure_ascii=False)

def _get_section(name: str) -> Optional[dict]:
    """Resolve only catalogued H-sections; all structural tools share this catalog."""
    return section_properties(name)


@tool
def query_steel_sections(payload: str) -> str:
    """按型号/尺寸筛选本地热轧H型钢与Q235焊接H型截面库。series可用H或WH，catalog_type可用hot_rolled_h或welded_q235。"""
    try:
        data = json.loads(payload) if isinstance(payload, str) else dict(payload)
        query = str(data.get("query") or data.get("q") or "")
        rows = search_sections(query, series=data.get("series"), catalog_type=data.get("catalog_type"),
                               min_height_mm=data.get("min_height_mm"),
                               max_height_mm=data.get("max_height_mm"),
                               min_area_cm2=data.get("min_area_cm2"),
                               max_area_cm2=data.get("max_area_cm2"),
                               top_k=data.get("top_k", data.get("limit", 30)))
        return json.dumps({"ok": True, "source": catalog_info(),
                           "count": len(rows), "sections": rows}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)


def _b_class_phi(lam, fy, E=206000.0):
    """GB50017-2017 附录 D，b 类截面轴心受压稳定系数"""
    lam_n = lam / math.pi * math.sqrt(fy / E)
    if lam_n <= 0.215:
        return 1.0 - 0.65 * lam_n * lam_n
    a2 = 0.965 + 0.300 * lam_n + lam_n * lam_n
    return (a2 - math.sqrt(a2 * a2 - 4 * lam_n * lam_n)) / (2 * lam_n * lam_n)


def _c_class_phi(lam, fy, E=206000.0):
    """c 类截面（焊接 H 型钢绕弱轴）轴心受压稳定系数"""
    lam_n = lam / math.pi * math.sqrt(fy / E)
    if lam_n <= 0.215:
        return 1.0 - 0.73 * lam_n * lam_n
    a2 = 0.906 + 0.595 * lam_n + lam_n * lam_n
    return (a2 - math.sqrt(a2 * a2 - 4 * lam_n * lam_n)) / (2 * lam_n * lam_n)


def _column_phi(lam, fy, curve, E=206000.0):
    curve = str(curve or "").lower()
    if curve == "b":
        return _b_class_phi(lam, fy, E)
    if curve == "c":
        return _c_class_phi(lam, fy, E)
    raise ValueError("当前实现仅支持 GB 50017 附录D的 b/c 曲线；请填写截面分类 b 或 c")


def _beam_phi_b(sec, ly, fy, beta_b=1.0, eta_b=0.0):
    """GB50017-2017 附录 C.0.1，受弯构件整体稳定系数（双轴对称/单轴对称焊接/轧制 H 型钢）"""
    A = sec["A"]
    h = sec["h"]
    t1 = sec["t1"]
    Wx = sec["Wx"]
    iy = sec["iy"]
    b = sec["b"]
    lam_y = ly / iy
    if ly <= 0 or fy <= 0 or beta_b <= 0:
        raise ValueError("梁整体稳定参数 ly、fy、beta_b 必须为正数")
    eps_k = math.sqrt(235.0 / fy)
    phi_b = beta_b * (4320 / (lam_y ** 2)) * (A * h / Wx) * (
        math.sqrt(1 + (lam_y * t1 / (4.4 * h)) ** 2) + eta_b
    ) * eps_k
    if phi_b > 0.6:
        phi_b = min(1.0, 1.07 - 0.282 / phi_b)
    return phi_b


# =========================================================
# Tool 1: 荷载组合计算
# =========================================================
@tool
def calculate_load_combination(payload: str) -> str:
    """依据 GB 50009-2012 与 GB 50011-2010 计算钢结构构件的荷载组合设计值。

    传入 JSON 字符串，字段：
    {
      "dead": 恒载标准值(kN/m 或 kN, 必填),
      "live": 活载标准值(kN/m 或 kN, 必填),
      "wind": 风载标准值(kN/m, 可选, 默认0),
      "seismic": 地震作用代表值(kN, 可选, 默认0),
      "unit": 单位说明
    }
    返回各极限状态组合下的设计值与最不利控制组合。
    """
    try:
        d = json.loads(payload)
    except Exception as e:
        return f"JSON 解析失败: {e}，请按规范格式传入。"

    dead = float(d.get("dead", 0))
    live = float(d.get("live", 0))
    wind = float(d.get("wind", 0))
    seismic = float(d.get("seismic", 0))
    unit = d.get("unit", "kN/m")

    lines = []
    lines.append("=== 荷载组合计算书（GB 50009-2012 / GB 50011-2010）===")
    lines.append(f"恒载 G_k={dead} {unit}，活载 Q_k={live} {unit}，风载 W_k={wind} {unit}，地震代表值 E={seismic} {unit}")
    lines.append("")

    # 承载能力极限状态
    lines.append("【一】承载能力极限状态组合（分项系数按 GB 50009-2012 表3.2.4，γG取1.3/1.5）")
    combos = {}
    # 由永久荷载控制：1.35G + 1.4ψcQ（ψc活0.7，风0.6）
    combos["由永久荷载控制 1.35G+1.4×0.7Q"] = 1.35 * dead + 1.4 * 0.7 * live
    combos["由永久荷载控制 1.35G+1.4×(0.7Q+0.6W)"] = 1.35 * dead + 1.4 * 0.7 * live + 1.4 * 0.6 * wind
    # 由可变荷载控制：1.2G + 1.4Q + 1.4ψW
    combos["由可变荷载控制 1.2G+1.4Q"] = 1.2 * dead + 1.4 * live
    combos["由可变荷载控制 1.2G+1.4Q+1.4×0.6W"] = 1.2 * dead + 1.4 * live + 1.4 * 0.6 * wind
    combos["由可变荷载控制 1.2G+1.4W+1.4×0.7Q"] = 1.2 * dead + 1.4 * wind + 1.4 * 0.7 * live
    for name, v in combos.items():
        lines.append(f"  {name:<40} = {v:.2f} {unit}")

    # 地震组合 (GB 50011 5.4.1)：S = γG G + γEh Eh + γEv Ev + ψw γw W
    if seismic > 0:
        quake = 1.2 * dead + 0.6 * 1.2 * live + 1.3 * seismic + 1.4 * 0.2 * wind
        lines.append(f"  地震作用组合(重力+水平地震+风0.2系数) = {quake:.2f} {unit}")
        combos["地震作用组合 1.2G+0.6×1.2Q+1.3E+1.4×0.2W"] = quake

    vals = sorted(combos.items(), key=lambda kv: kv[1], reverse=True)
    if vals:
        lines.append("")
        lines.append(f"★ 最不利控制组合：{vals[0][0]} = {vals[0][1]:.2f} {unit}")

    # 正常使用极限状态
    lines.append("")
    lines.append("【二】正常使用极限状态组合（用于挠度/变形容许验算）")
    lines.append(f"  标准组合 G+Q = {dead + live:.2f} {unit}")
    lines.append(f"  频遇组合 G+0.5Q = {dead + 0.5 * live:.2f} {unit}")
    lines.append(f"  准永久组合 G+0.4Q = {dead + 0.4 * live:.2f} {unit}")

    return "\n".join(lines)


# =========================================================
# Tool 2: 钢结构构件验算
# =========================================================
@tool
def check_steel_member(payload: str) -> str:
    """依据 GB 50017-2017 对钢框架梁/柱构件进行截面验算。

    传入 JSON 字符串，字段：
    {
      "member_type": "beam 或 column (必填)",
      "section": "截面名，如 HN400x200 / HM400x300 / HW250x250 / I36a / H400x300x10x16",
      "steel": "Q235/Q355/Q390 (默认Q355)",
      "span_m": 跨度或计算长度(米),
      "Mx_kNm": 强轴弯矩设计值 (kN·m, 默认0),
      "My_kNm": 弱轴弯矩设计值 (kN·m, 默认0),
      "V_kn": 剪力设计值 (kN, 默认0),
      "N_kn": 轴力设计值 (kN, 默认0，柱必填),
      "l0x_m": 绕x轴计算长度(米, 默认取 span_m),
      "l0y_m": 绕y轴计算长度(米, 默认取 span_m),
      "deflection_mm": 计算挠度(毫米, 可选),
      "deflection_ratio": "l/400" 允许挠度比(默认 l/400)
    }
    返回包含强度、稳定、局部稳定、长细比、挠度的验算结论。
    """
    try:
        d = json.loads(payload)
    except Exception as e:
        return f"JSON 解析失败: {e}，请按规范格式传入。"

    member_type = d.get("member_type", "beam")
    steel = d.get("steel", "Q355").upper()
    section_name = d.get("section", "HN400x200")
    if steel not in MATERIALS:
        return f"不支持的钢材牌号 {steel}，支持：{list(MATERIALS.keys())}"

    sec = _get_section(section_name)
    if sec is None:
        return (f"未找到截面 {section_name}。本工具只接受本地 GB/T 11263-2024 附录A表A.1"
                "中的 H 型钢型号；请从 /sections 查询截面库，不能用自定义尺寸替代。")
    section_name = sec["name"]

    fy, f, fv = MATERIALS[steel]
    span = float(d.get("span_m", 8))
    l0x = float(d.get("l0x_m", span))
    l0y = float(d.get("l0y_m", span))
    # The input is a design envelope. Treat signed end actions as magnitudes
    # here; cancellation between independently enveloped actions is unsafe.
    Mx = abs(float(d.get("Mx_kNm", 0))) * 1e6  # N·mm
    My = abs(float(d.get("My_kNm", 0))) * 1e6
    V = abs(float(d.get("V_kn", 0))) * 1e3    # N
    N = float(d.get("N_kn", 0)) * 1e3         # N
    defl_mm = float(d.get("deflection_mm", 0))
    defl_ratio = d.get("deflection_ratio", "l/400")
    if "/" in defl_ratio:
        defl_den = float(defl_ratio.split("/")[1])
    else:
        defl_den = 400.0

    A = sec["A"]
    Wx = sec["Wx"]
    Wy = sec["Wy"]
    Ix = sec["Ix"]
    ix = sec["ix"]
    iy = sec["iy"]
    tw = sec["tw"]
    h0 = sec["h0"]
    b = sec["b"]
    t1 = sec["t1"]

    res = []
    utilization_components = {}
    res.append(f"=== 钢结构构件验算书（GB 50017-2017）===")
    res.append(f"构件类型: {member_type} | 截面: {section_name} | 钢材: {steel} (f={f} N/mm², fv={fv} N/mm²)")
    res.append(f"截面特性: A={A:.0f} mm², Wx={Wx/1e3:.1f} cm³, Ix={Ix/1e6:.0f} cm⁴, ix={ix:.1f} mm, iy={iy:.1f} mm")
    res.append("")

    # 强度验算
    if member_type == "column":
        lam_x = l0x * 1000 / ix
        lam_y = l0y * 1000 / iy
        res.append(f"【强度】λx={l0x:.2f}m/ix → λ={lam_x:.1f}, λy={l0y:.2f}m/iy → λ={lam_y:.1f}")
        # 轴压 + 双向弯曲 (N/A + Mx/γx Wx + My/γy Wy)
        sigma_n = abs(N) / A
        sigma_bx = Mx / (1.05 * Wx)
        sigma_by = My / (1.2 * Wy)
        sigma = sigma_n + sigma_bx + sigma_by
        utilization_components["截面强度"] = sigma / f
        res.append(f"  σ = N/A + Mx/(γx·Wx) + My/(γy·Wy) = {sigma_n:.1f}+{sigma_bx:.1f}+{sigma_by:.1f} = {sigma:.1f} N/mm² {'✓ ≤ f='+str(f) if sigma<=f else '✗ > f='+str(f)}")

        # 整体稳定（绕强轴按 b 类，绕弱轴按 c 类）
        if N > 0:
            phi_x = _column_phi(lam_x, fy, d.get("section_class_x", "b"))
            phi_y = _column_phi(lam_y, fy, d.get("section_class_y", "c"))
            # 平面内稳定：弯矩等效系数 βmx=1.0，考虑弯矩放大效应简化（取规范简化式）
            beta_mx = float(d.get("beta_mx", 1.0))
            N_ex = math.pi ** 2 * 206000 * A / (1.1 * lam_x ** 2)
            denom = 1 - 0.8 * N / N_ex if N_ex > 0 else -1.0
            stress_in = (N / (phi_x * A) + beta_mx * Mx / (1.05 * Wx * denom)) if denom > 0 else math.inf
            utilization_components["平面内整体稳定筛查"] = stress_in / f if math.isfinite(stress_in) else 1.0e9
            res.append(f"  λx={lam_x:.1f}→φx({d.get('section_class_x', 'b')}类)={phi_x:.3f}，λy={lam_y:.1f}→φy({d.get('section_class_y', 'c')}类)={phi_y:.3f}")
            res.append(f"  平面内整体稳定筛查: σ=N/(φx·A)+βmx·Mx/[γx·Wx·(1-0.8N/N'ex)] = {stress_in:.1f} N/mm² {'✓' if stress_in<=f else '✗'}（βmx={beta_mx:g}）")
            stress_plan = N / (phi_y * A) + My / (1.2 * Wy)
            utilization_components["平面外整体稳定筛查"] = stress_plan / f
            res.append(f"  平面外整体稳定简化筛查: σ=N/(φy·A)+My/(1.2·Wy) ≈ {stress_plan:.1f} N/mm² {'✓' if stress_plan<=f else '✗'}；双向压弯/侧扭耦合仍需按GB 50017第6.2节复核")
        else:
            phi_x = phi_y = 1.0

        # 长细比限值
        lam_max = max(lam_x, lam_y)
        lam_lim = 180 if (N / A) < (0.4 * f) else 150
        utilization_components["长细比"] = lam_max / lam_lim
        res.append(f"  长细比验算: max(λx,λy)={lam_max:.1f} ≤ [{lam_lim}] {'✓' if lam_max<=lam_lim else '✗'}")
        if defl_mm > 0:
            allow = span * 1000 / defl_den
            utilization_components["构件变形"] = defl_mm / allow
            res.append(f"  构件横向变形验算: v={defl_mm:.1f}mm ≤ [{defl_ratio}]={allow:.1f}mm {'✓' if defl_mm<=allow else '✗'}（不替代整体层间位移角验算）")
    else:
        # 受弯构件
        lam_y = l0y * 1000 / iy
        sigma = abs(N) / A + Mx / (1.05 * Wx) + My / (1.2 * Wy)
        tau = V * sec["Sx"] / (Ix * tw) if V > 0 else 0
        utilization_components["截面强度"] = sigma / f
        utilization_components["抗剪"] = tau / fv
        res.append(f"【强度】σ=Mx/(γx·Wx)+My/(γy·Wy) = {Mx/(1.05*Wx):.1f}+{My/(1.2*Wy):.1f} = {sigma:.1f} N/mm² {'✓ ≤ f' if sigma<=f else '✗ > f'}")
        # 抗剪
        res.append(f"  抗剪: τ=V·S/(I·tw) = {tau:.1f} N/mm² {'✓ ≤ fv='+str(fv) if tau<=fv else '✗ > fv'}")
        # The Appendix-C coefficient transform is based on the calculated φb,
        # not on the member's current stress ratio. Always report the check
        # unless the caller has supplied a verified lateral restraint model.
        phi_b = _beam_phi_b(sec, l0y * 1000, fy,
                            float(d.get("beta_b", 1.0)), float(d.get("eta_b", 0.0)))
        sigma_stab = Mx / (phi_b * Wx) + My / (1.2 * Wy) if phi_b > 0 else math.inf
        utilization_components["整体稳定筛查"] = sigma_stab / f if math.isfinite(sigma_stab) else 1.0e9
        res.append(f"  整体稳定筛查: λy={lam_y:.1f}→φb={phi_b:.3f}, σ=Mx/(φb·Wx)+My/(1.2·Wy)={sigma_stab:.1f} N/mm² {'✓' if sigma_stab<=f else '✗'}；侧向支承及双向受弯条件须按附录C复核")
        # 挠度
        allow = span * 1000 / defl_den
        if defl_mm > 0:
            utilization_components["挠度"] = defl_mm / allow
            res.append(f"  挠度验算: v={defl_mm:.1f}mm ≤ [{defl_ratio}]={allow:.1f}mm {'✓' if defl_mm<=allow else '✗'}")

    # 局部稳定（板件宽厚比，GB50017 7.3/7.4）
    eps = math.sqrt(235.0 / fy)
    if member_type == "column":
        # 受压翼缘: b/t ≤ 10+0.1λ (轴压) ; 腹板 h0/tw ≤ (25+0.5λ)ε
        b_over_t = (b / 2) / t1
        h0_over_tw = h0 / tw
        lam_eff = min(100.0, max(30.0, lam_max)) if N > 0 else 40.0
        limit_flange = (10 + 0.1 * lam_eff) * eps
        limit_web = (25 + 0.5 * lam_eff) * eps
        flange_ok = b_over_t <= limit_flange
        web_ok = h0_over_tw <= limit_web
        utilization_components["翼缘局部稳定筛查"] = b_over_t / limit_flange
        utilization_components["腹板局部稳定筛查"] = h0_over_tw / limit_web
        res.append(f"  局部稳定: 翼缘 b/2t={b_over_t:.1f}≤{limit_flange:.1f} {'✓' if flange_ok else '✗'}；腹板 h0/tw={h0_over_tw:.1f}≤{limit_web:.1f} {'✓' if web_ok else '✗'}")
    else:
        flange_ratio = (b / 2) / t1
        flange_limit = 15 * eps  # S4级限值；用于不考虑S5有效截面的保守筛查
        web_limit = 124 * eps    # S4级限值
        web_ratio = h0 / tw
        flange_ok = flange_ratio <= flange_limit
        web_ok = web_ratio <= web_limit
        utilization_components["翼缘局部稳定筛查"] = flange_ratio / flange_limit
        utilization_components["腹板局部稳定筛查"] = web_ratio / web_limit
        res.append(f"  局部稳定筛查(S4): 翼缘外伸宽厚比={(flange_ratio):.1f}≤{flange_limit:.1f} {'✓' if flange_ok else '✗'}；腹板 h0/tw={web_ratio:.1f}≤{web_limit:.1f} {'✓' if web_ok else '✗'}（超过S4时须按有效截面/板件等级复核）")
    res.append(f"  ★ 经济性参考：通道σ/(φ·f，强度利用率) 建议 0.6~0.9，当前强度应力 {sigma:.1f}/{f}")

    report_text = "\n".join(res)
    if d.get("structured_output"):
        checks = [{"item": line.strip().split(":", 1)[0].strip("【】 "),
                   "passed": "✗" not in line, "text": line}
                  for line in res if "✓" in line or "✗" in line]
        return json.dumps({"ok": True, "member_id": d.get("member_id"),
            "member_type": member_type, "section": section_name, "steel": steel,
            "span_m": span, "demands": {"N_kn": N / 1e3, "Mx_kNm": Mx / 1e6,
            "My_kNm": My / 1e6, "V_kn": V / 1e3, "deflection_mm": defl_mm},
            "utilization": max(utilization_components.values(), default=0.0),
            "utilization_components": utilization_components,
            "passed": all(item["passed"] for item in checks), "checks": checks,
            "result_text": report_text}, ensure_ascii=False)
    return report_text


@tool
def optimize_steel_truss_members(payload: str) -> str:
    """逐根验算并从候选截面中选出满足条件的最小面积钢网架杆件截面。

    仅接受 ANSYS 后处理后整理的 JSON 结果，不读取 .rst/.db，也不修改/重算 ANSYS 模型。
    输入必须显式给 unit_system (N_mm 或 kN_m) 和 axial_sign
    (compression_positive 或 tension_positive)。members 每项包含 member_id、N、Mx、My、Vy、Vz、
    length、candidate_sections；截面候选为内置 H/I 型钢名或 H:hxbxtwxtf。
    力单位为 N/kN，弯矩为 N·mm/kN·m，长度与单位系统一致；deflection_mm 始终为 mm。
    当前稳定曲线仅支持 GB 50017 附录D b/c 类，H截面局部稳定按第7.3.1条；截面分类与
    beta_b需按真实截面、支承和荷载条件输入，否则报告中会标记采用的默认假设。
    """
    try:
        data = json.loads(payload) if isinstance(payload, str) else dict(payload)
        unit_system = str(data.get("unit_system", ""))
        axial_sign = str(data.get("axial_sign", ""))
        if unit_system not in {"N_mm", "kN_m"}:
            raise ValueError("unit_system 必须明确填写 N_mm 或 kN_m")
        if axial_sign not in {"compression_positive", "tension_positive"}:
            raise ValueError("axial_sign 必须明确填写 compression_positive 或 tension_positive")
        members = data.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("members 必须是非空构件数组")
        steel = str(data.get("steel", "Q355")).upper()
        if steel not in MATERIALS:
            raise ValueError(f"不支持钢材 {steel}；当前支持 {', '.join(MATERIALS)}")

        results, warnings = [], []
        if data.get("section_class_x") is None or data.get("section_class_y") is None:
            warnings.append("未同时提供 section_class_x/y；压杆稳定曲线默认按 b/c 类，请根据 GB 50017 表7.2.1核定截面分类。")
        if data.get("beta_b") is None:
            warnings.append("未提供 beta_b；梁整体稳定按 beta_b=1.0 计算，须按 GB 50017 附录C结合侧向支承和荷载核定。")
        if data.get("beta_mx") is None and any(member.get("beta_mx") is None for member in members if isinstance(member, dict)):
            warnings.append("未提供 beta_mx；压弯构件平面内稳定按 beta_mx=1.0 筛查，须依据弯矩图和端部约束复核。")

        def number(item, *keys, default=0.0):
            for key in keys:
                if key in item and item[key] is not None:
                    value = float(item[key])
                    if not math.isfinite(value):
                        raise ValueError(f"{key} 必须为有限数")
                    return value
            return float(default)

        for source in members:
            member_id = str(source.get("member_id", "")).strip()
            if not member_id:
                raise ValueError("每根构件都必须提供 member_id")
            candidates = source.get("candidate_sections") or ([source["section"]] if source.get("section") else [])
            if not isinstance(candidates, list) or not candidates:
                raise ValueError(f"构件 {member_id} 缺少 candidate_sections/section")
            N = number(source, "N", "N_force")
            Mx = number(source, "Mx", "My")
            My = number(source, "My_weak", "Mz")
            Vy = number(source, "Vy", "V_y")
            Vz = number(source, "Vz", "V_z")
            if axial_sign == "tension_positive":
                N = -N
            if unit_system == "N_mm":
                N_kn, Mx_kNm, My_kNm = N / 1000.0, Mx / 1e6, My / 1e6
                Vy_kn, Vz_kn = Vy / 1000.0, Vz / 1000.0
                span_m = number(source, "length_mm", "length") / 1000.0
                l0x_m = number(source, "l0x_mm", default=span_m * 1000.0) / 1000.0
                l0y_m = number(source, "l0y_mm", default=span_m * 1000.0) / 1000.0
            else:
                N_kn, Mx_kNm, My_kNm = N, Mx, My
                Vy_kn, Vz_kn = Vy, Vz
                span_m = number(source, "length_m", "length")
                l0x_m = number(source, "l0x_m", default=span_m)
                l0y_m = number(source, "l0y_m", default=span_m)
            if min(span_m, l0x_m, l0y_m) <= 0:
                raise ValueError(f"构件 {member_id} 的长度和计算长度必须为正数")
            member_type = source.get("member_type") or ("column" if N_kn > 0 else "beam")
            if member_type not in {"beam", "column"}:
                raise ValueError(f"构件 {member_id} 的 member_type 只支持 beam/column")

            candidate_results = []
            for candidate in candidates:
                section_name = str(candidate)
                sec = _get_section(section_name)
                if sec is None:
                    candidate_results.append({"section": section_name, "passed": False,
                                              "error": "未识别截面；当前仅支持内置型钢或 H:hxbxtwxtf 参数截面"})
                    continue
                if max(sec["tw"], sec["t1"]) > 16:
                    candidate_results.append({"section": section_name, "passed": False,
                                              "error": "当前材料设计强度表仅适用于板厚≤16 mm；须补充对应厚度的规范设计强度"})
                    continue
                check_payload = {
                    "member_id": member_id, "member_type": member_type, "section": section_name,
                    "steel": steel, "span_m": span_m, "l0x_m": l0x_m, "l0y_m": l0y_m,
                    "N_kn": N_kn, "Mx_kNm": Mx_kNm, "My_kNm": My_kNm,
                    "V_kn": Vy_kn, "deflection_mm": number(source, "deflection_mm"),
                    "deflection_ratio": source.get("deflection_ratio", "l/400"),
                    "beta_mx": float(source.get("beta_mx", data.get("beta_mx", 1.0))),
                    "beta_b": float(source.get("beta_b", data.get("beta_b", 1.0))),
                    "section_class_x": source.get("section_class_x", data.get("section_class_x", "b")),
                    "section_class_y": source.get("section_class_y", data.get("section_class_y", "c")),
                    "structured_output": True,
                }
                try:
                    raw = check_steel_member.invoke(json.dumps(check_payload, ensure_ascii=False))
                    checked = json.loads(raw) if isinstance(raw, str) else raw
                    if not isinstance(checked, dict) or not checked.get("ok"):
                        raise ValueError(str(checked))
                    extra_checks = []
                    if N_kn < 0:
                        f = MATERIALS[steel][1]
                        ratio = abs(N_kn) * 1000 / sec["A"] / f
                        extra_checks.append({"item": "轴心受拉强度", "passed": ratio <= 1.0,
                                             "text": f"|N|/A/f={ratio:.3f} {'≤' if ratio <= 1 else '>'} 1.0"})
                    if N_kn > 0 and abs(My_kNm) > 1e-9:
                        extra_checks.append({"item": "双向压弯整体稳定复核", "passed": False,
                                             "text": "存在弱轴弯矩 My；本初版未实现 GB 50017 第6.2.1条双向压弯与侧扭耦合完整验算，不能判为通过。"})
                    if Vz_kn:
                        sz = (sec["b"] / 2 - sec["tw"] / 2) * sec["t1"] * (sec["b"] / 2 - sec["tw"] / 2)
                        tau = abs(Vz_kn) * 1000 * sz / (sec["Iy"] * 2 * sec["t1"])
                        fv = MATERIALS[steel][2]
                        extra_checks.append({"item": "弱轴抗剪", "passed": tau <= fv,
                                             "text": f"τz={tau:.2f} N/mm² {'≤' if tau <= fv else '>'} fv={fv} N/mm²"})
                    all_checks = [*checked.get("checks", []), *extra_checks]
                    candidate_results.append({**checked, "checks": all_checks,
                                              "passed": all(c.get("passed", False) for c in all_checks),
                                              "area_mm2": sec["A"]})
                except Exception as exc:
                    candidate_results.append({"section": section_name, "passed": False,
                                              "error": f"截面验算执行失败：{type(exc).__name__}: {exc}"})
            valid = [result for result in candidate_results if result.get("passed")]
            selected = min(valid, key=lambda result: result.get("area_mm2", math.inf)) if valid else None
            results.append({"member_id": member_id, "passed": selected is not None,
                            "selected_section": selected.get("section") if selected else None,
                            "selected_area_mm2": selected.get("area_mm2") if selected else None,
                            "candidates": candidate_results,
                            "optimization": "在已提供的候选截面中选择满足检查且面积最小者；未通过则需增加候选截面后重新验算"})
        return json.dumps({"ok": True, "standard": "GB 50017-2017 (筛查型实现，须工程师复核)",
                           "unit_system": unit_system, "axial_sign": axial_sign,
                           "members": results, "all_passed": all(r["passed"] for r in results),
                           "warnings": warnings,
                           "notice": "此工具处理用户从 ANSYS 导出的内力与截面参数；不读取 ANSYS 结果文件、不执行有限元重分析。截面曲线、侧向支承、荷载系数、连接净截面及完整规范适用性需复核。"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
