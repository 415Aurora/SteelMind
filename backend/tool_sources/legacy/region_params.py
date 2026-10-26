"""从本地结构参数知识库查询地区设计参数；不访问互联网、不调用 Coze。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from langchain.tools import tool


DEFAULT_KB_PATH = Path(__file__).with_name("region_params_kb.json")
PARAMETERS: dict[str, dict[str, Any]] = {
    "basic_wind_pressure_kN_m2": {"label": "基本风压", "aliases": ("基本风压", "风压", "基本风压值")},
    "basic_snow_pressure_kN_m2": {"label": "基本雪压", "aliases": ("基本雪压", "雪压", "基本雪压值")},
    "seismic_intensity": {"label": "抗震设防烈度", "aliases": ("抗震设防烈度", "设防烈度", "地震烈度")},
    "design_basic_ground_acceleration_g": {"label": "设计基本地震加速度", "aliases": ("设计基本地震加速度", "基本地震加速度", "地震动峰值加速度", "峰值加速度")},
    "design_seismic_group": {"label": "设计地震分组", "aliases": ("设计地震分组", "地震分组")},
    "characteristic_period_s": {"label": "设计反应谱特征周期", "aliases": ("设计反应谱特征周期", "反应谱特征周期", "特征周期")},
    "ground_roughness": {"label": "地面粗糙度类别", "aliases": ("地面粗糙度", "地面粗糙度类别", "粗糙度类别")},
    "design_reference_period_years": {"label": "设计基准期", "aliases": ("设计基准期", "设计使用年限", "设计年限")},
}
NON_REGIONAL = {
    "structural_safety_class": "结构安全等级不是单纯的地区参数；需依据建筑用途、破坏后果、规模及适用规范，由设计人员确定。",
    "building_importance_category": "建筑抗震设防类别取决于建筑用途与震害后果，不能仅按地区推定。",
    "foundation_design_grade": "地基基础设计等级需结合工程规模、地基复杂程度及破坏后果确定，不能仅按地区推定。",
}
def _normal(value: Any) -> str:
    return re.sub(r"[\s，,。;；、\-—_（）()]+", "", str(value or "")).casefold()


ITEM_TO_FIELD = {_normal(alias): field for field, spec in PARAMETERS.items()
                 for alias in (field, spec["label"], *spec["aliases"])}
ITEM_TO_FIELD.update({_normal(alias): field for alias, field in {
    "安全等级": "structural_safety_class", "结构安全等级": "structural_safety_class",
    "抗震设防类别": "building_importance_category", "建筑重要性类别": "building_importance_category",
    "基础设计等级": "foundation_design_grade", "地基基础设计等级": "foundation_design_grade",
}.items()})


def _load_kb() -> dict[str, Any]:
    path = Path(os.getenv("STEEL_REGION_KB_PATH", str(DEFAULT_KB_PATH))).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"本地地区知识库不存在：{path}。请按 region_params_kb.template.json 建立知识库。")
    with path.open("r", encoding="utf-8-sig") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get("records", []), list):
        raise ValueError("知识库格式错误：顶层必须包含 records 数组。")
    return data


def _match_record(records: list[Any], region: str) -> tuple[dict[str, Any] | None, list[str]]:
    query = _normal(region)
    exact: list[dict[str, Any]] = []
    parent: list[dict[str, Any]] = []
    for entry in records:
        if not isinstance(entry, dict) or not entry.get("region"):
            continue
        names = [entry["region"], *(entry.get("aliases") or [])]
        if any(_normal(name) == query for name in names):
            exact.append(entry)
        elif entry.get("covers_descendants") is True and any(query.startswith(_normal(name)) for name in names if _normal(name)):
            parent.append(entry)
    candidates = exact or parent
    if not candidates:
        return None, []
    best_length = max(len(_normal(item.get("region"))) for item in candidates)
    best = [item for item in candidates if len(_normal(item.get("region"))) == best_length]
    if len(best) != 1:
        return None, sorted({str(item.get("region")) for item in best})
    return best[0], []


def _valid_source(source: Any) -> bool:
    return isinstance(source, dict) and bool(source.get("standard")) and bool(source.get("reference")) and bool(source.get("verified_on"))


@tool
def query_region_params(payload: str) -> str:
    """只查询本地 JSON 知识库中的地区参数，返回取值、单位、规范依据和来源。

    输入 JSON：{"region":"河北省石家庄市长安区","items":["基本风压","基本雪压","抗震设防烈度","结构安全等级"]}。
    若无地区匹配或某字段缺失，明确返回 not_found/pending，不进行网络检索或推测填值。
    """
    try:
        request = json.loads(payload) if isinstance(payload, str) else dict(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        request = {"region": str(payload)}
    if not isinstance(request, dict):
        return json.dumps({"ok": False, "status": "invalid_input", "error": "输入必须是包含 region 和 items 的 JSON 对象。"}, ensure_ascii=False)
    region = str(request.get("region", "")).strip()
    if not region:
        return json.dumps({"ok": False, "status": "needs_input", "error": "请提供省、市、区县或乡镇地区名称。"}, ensure_ascii=False)
    items = request.get("items") or [spec["label"] for spec in PARAMETERS.values()]
    if isinstance(items, str):
        items = [items]
    try:
        kb = _load_kb()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return json.dumps({"ok": False, "status": "knowledge_base_error", "error": str(exc)}, ensure_ascii=False)

    record, ambiguous = _match_record(kb["records"], region)
    if ambiguous:
        return json.dumps({"ok": False, "status": "ambiguous", "query_region": region,
                           "candidates": ambiguous, "message": "地区别名对应多条记录，请提供更完整的行政区划名称。"}, ensure_ascii=False)

    results: dict[str, Any] = {}
    missing: list[str] = []
    project_specific: dict[str, str] = {}
    withheld: list[str] = []
    values = (record or {}).get("values", {})
    for item in items:
        key = str(item)
        field = ITEM_TO_FIELD.get(_normal(key))
        if field in NON_REGIONAL:
            project_specific[field] = NON_REGIONAL[field]
            continue
        if field is None:
            missing.append(key)
            continue
        entry = values.get(field) if isinstance(values, dict) else None
        if not isinstance(entry, dict) or "value" not in entry or entry["value"] is None:
            missing.append(PARAMETERS[field]["label"])
            continue
        if not _valid_source(entry.get("source")):
            withheld.append(PARAMETERS[field]["label"])
            continue
        results[field] = {"label": PARAMETERS[field]["label"], "value": entry["value"],
                          "unit": entry.get("unit", ""), "source": entry["source"],
                          "notes": entry.get("notes", "")}

    status = "matched" if record and not missing and not withheld else "partial" if record and results else "not_found" if not record else "pending_review"
    output = {"ok": bool(results), "status": status, "source_type": "local_knowledge_base",
              "knowledge_base_version": kb.get("version", "unspecified"), "query_region": region,
              "matched_region": record.get("region") if record else None, "results": results,
              "missing_items": missing, "withheld_items_missing_citations": withheld,
              "project_specific_items": project_specific,
              "message": "只返回具有规范依据与核验日期的本地记录；缺失值不推定。"}
    if not record:
        output["message"] = "知识库中未找到该地区；请补充地区记录，不会联网搜索或猜测参数。"
    return json.dumps(output, ensure_ascii=False, indent=2)
