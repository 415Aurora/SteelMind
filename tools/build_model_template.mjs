import fs from "node:fs/promises";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const outDir = "C:/Users/Administrator/Desktop/小论文/AIwork/steel-agent/dist";
await fs.mkdir(outDir, { recursive: true });
const wb = Workbook.create();
const navy = "#17324D", teal = "#0F766E", light = "#EAF3F5", input = "#FFF4CC", line = "#B8C9D4", text = "#1F2933";
const font = "Aptos";

function setupSheet(name, title, subtitle, headers, rows, widths) {
  const sh = wb.worksheets.add(name);
  sh.showGridLines = false;
  sh.getRange("A1:Z200").format.font = { name: font, size: 10, color: text };
  sh.getRange("A1").values = [[title]];
  sh.getRange(`A1:${String.fromCharCode(64 + Math.min(headers.length, 26))}1`).format.font = { name: font, size: 15, bold: true, color: navy };
  sh.getRange("A2").values = [[subtitle]];
  sh.getRange(`A2:${String.fromCharCode(64 + Math.min(headers.length, 26))}2`).format.font = { name: font, size: 10, italic: true, color: "#526D82" };
  const endCol = String.fromCharCode(64 + headers.length);
  sh.getRange(`A4:${endCol}4`).values = [headers];
  sh.getRange(`A4:${endCol}4`).format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, wrapText: true, horizontalAlignment: "center", verticalAlignment: "center", borders: { preset: "all", style: "thin", color: "#FFFFFF" } };
  if (rows.length) {
    sh.getRange(`A5:${endCol}${4 + rows.length}`).values = rows;
    sh.getRange(`A5:${endCol}${4 + rows.length}`).format = { fill: input, wrapText: true, verticalAlignment: "center", borders: { preset: "all", style: "thin", color: line } };
  }
  headers.forEach((_, i) => { const col = String.fromCharCode(65 + i); sh.getRange(`${col}:${col}`).format.columnWidth = widths?.[i] || 16; });
  sh.getRange("A4").getCurrentRegion().format.rowHeight = 23;
  sh.freezePanes.freezeRows(4);
  const tableEnd = Math.max(5, 4 + rows.length);
  sh.tables.add(`A4:${endCol}${tableEnd}`, true, `${name.replace(/[^A-Za-z0-9]/g, "")}_Table`);
  return sh;
}

const readme = wb.worksheets.add("ReadMe");
readme.showGridLines = false;
readme.getRange("A1:H30").format.font = { name: font, size: 10, color: text };
readme.getRange("A1").values = [["SteelMind 钢结构建模参数模板"]];
readme.getRange("A1:H1").format.font = { name: font, size: 16, bold: true, color: navy };
readme.getRange("A2").values = [["填写黄色单元格；不要修改 field_id、表头和工作表名称。后续智能体将按这些稳定字段读取模型。"]];
readme.getRange("A2:H2").format.font = { name: font, size: 10, italic: true, color: "#526D82" };
readme.getRange("A4:B4").values = [["工作表", "用途"]];
readme.getRange("A4:B4").format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
readme.getRange("A5:B13").values = [
  ["Project", "项目基本信息、单位制和设计目标"],
  ["Materials", "材料、牌号、弹性模量、屈服强度等"],
  ["Nodes", "节点坐标、约束和集中质量"],
  ["Sections", "截面几何参数或截面库名称"],
  ["Members", "杆件连接关系、截面、材料和端部释放"],
  ["Load_Cases", "荷载工况及动力/静力属性"],
  ["Nodal_Loads", "节点荷载"],
  ["Member_Loads", "杆件分布荷载或集中荷载"],
  ["Design_Controls", "抗震、组合、分析和验算控制参数"],
];
readme.getRange("A5:B13").format = { fill: light, wrapText: true, borders: { preset: "all", style: "thin", color: line } };
readme.getRange("D4:H4").values = [["填写规则", "说明", "示例", "是否必填", "读取方式"]];
readme.getRange("D4:H4").format = { fill: teal, font: { bold: true, color: "#FFFFFF" }, wrapText: true, horizontalAlignment: "center" };
readme.getRange("D5:H10").values = [
  ["数值", "直接填写数字，不要带单位", "30", "是", "按列名读取"],
  ["单位", "采用项目统一单位制", "kN, m, MPa", "是", "单位校验"],
  ["ID", "每个节点/杆件/工况唯一", "N01, M01, G", "是", "建立对象关系"],
  ["空白", "不会自动视为 0，缺失参数会提示", "", "视字段", "缺失检查"],
  ["坐标", "建议 X 为水平、Y 为水平、Z 为竖向", "0, 0, 3.6", "是", "建立几何模型"],
  ["版本", "填写采用的规范和资料版本", "GB 50017-2017", "是", "记录依据"],
];
readme.getRange("D5:H10").format = { fill: "#F4F8FA", wrapText: true, borders: { preset: "all", style: "thin", color: line } };
readme.getRange("A15:A18").values = [["使用流程"], ["上传后"], ["安全边界"], ["模板版本"]];
readme.getRange("B15:B18").values = [["1. 先填写 Project 和 Design_Controls。2. 再填写 Materials、Nodes、Sections、Members。3. 最后填写 Load_Cases、Nodal_Loads、Member_Loads。"], ["智能体会先做字段完整性检查，再生成建模摘要和待确认项。"], ["模板用于方案研究和计算准备；正式设计、规范判定和施工图仍需专业工程师复核。"], ["v0.1 · 结构化输入优先 · 后续可扩展荷载组合、楼层、连接和构件验算表。"]];
for (const row of [15,16,17,18]) { readme.mergeCells(`B${row}:H${row}`); }
readme.getRange("A15:H18").format = { fill: "#FFF9E8", wrapText: true, borders: { preset: "outside", style: "thin", color: "#D8B45A" } };
readme.getRange("A:A").format.columnWidth = 18; readme.getRange("B:B").format.columnWidth = 34; readme.getRange("D:D").format.columnWidth = 16; readme.getRange("E:E").format.columnWidth = 32; readme.getRange("F:F").format.columnWidth = 18; readme.getRange("G:H").format.columnWidth = 14;
readme.getRange("A1:H18").format.verticalAlignment = "center";

const project = setupSheet("Project", "项目基本信息", "只填写黄色区域；一个工作簿对应一个结构项目。", ["field_id", "字段名称", "value", "unit", "required", "description", "example"], [
  ["project_name", "项目名称", "", "", "Y", "项目或算例名称", "6层教学楼钢框架"],
  ["structure_system", "结构体系", "", "", "Y", "多层钢框架/门式刚架/桁架等", "多层钢框架"],
  ["design_stage", "设计阶段", "", "", "Y", "概念/初步/施工图/复核", "初步设计"],
  ["unit_system", "单位制", "", "", "Y", "统一采用的单位制", "kN-m-MPa"],
  ["code_version", "规范版本", "", "", "Y", "项目采用的主要规范及版本", "GB 50017-2017"],
  ["analysis_goal", "分析目标", "", "", "Y", "静力、模态、反应谱、时程等", "概念设计与模态分析"],
], [20, 18, 24, 12, 11, 35, 24]);

setupSheet("Materials", "材料参数", "每种材料一行；material_id 必须唯一。", ["material_id", "material_name", "grade", "E_MPa", "G_MPa", "fy_MPa", "fu_MPa", "density_t_m3", "poisson", "notes"], [
  ["MAT01", "结构钢", "Q355", "", "", "", "", "", "", "请按项目资料补充"],
], [16, 18, 14, 12, 12, 12, 12, 16, 12, 28]);

setupSheet("Nodes", "节点与边界", "每个节点一行；约束取 0/1，1 表示约束。坐标单位与 Project 一致。", ["node_id", "x", "y", "z", "ux", "uy", "uz", "rx", "ry", "rz", "mass_t", "notes"], [
  ["N01", "", "", "", "", "", "", "", "", "", "", ""],
], [14, 12, 12, 12, 10, 10, 10, 10, 10, 10, 14, 26]);

setupSheet("Sections", "截面参数", "可填截面库名称，也可填几何参数；section_id 必须唯一。", ["section_id", "section_name", "shape", "depth_mm", "width_mm", "tw_mm", "tf_mm", "area_mm2", "Ix_mm4", "Iy_mm4", "Zx_mm3", "Zy_mm3", "notes"], [
  ["SEC01", "", "H/箱形/圆管/角钢", "", "", "", "", "", "", "", "", "", ""],
], [14, 18, 18, 14, 14, 12, 12, 14, 16, 16, 16, 16, 24]);

setupSheet("Members", "杆件与连接关系", "每根杆件一行；i_node/j_node 必须引用 Nodes，section_id/material_id 必须引用对应表。", ["member_id", "member_type", "i_node", "j_node", "section_id", "material_id", "release_i", "release_j", "orientation_deg", "group", "notes"], [
  ["M01", "beam/column/bracing", "", "", "SEC01", "MAT01", "", "", "", "", ""],
], [14, 20, 12, 12, 14, 14, 14, 14, 18, 16, 26]);

setupSheet("Load_Cases", "荷载工况", "每种工况一行；case_id 将被节点荷载和杆件荷载引用。", ["case_id", "case_name", "case_type", "direction", "scale", "duration_s", "damping_ratio", "notes"], [
  ["G", "恒载", "static", "", "1", "", "", ""],
  ["Q", "活载", "static", "", "1", "", "", ""],
  ["E1", "地震X", "response_spectrum", "X", "1", "", "0.05", ""],
], [14, 18, 20, 14, 12, 14, 18, 26]);

setupSheet("Nodal_Loads", "节点荷载", "力单位与 Project 一致；没有的分量留空，不要填文字单位。", ["load_id", "node_id", "case_id", "Fx", "Fy", "Fz", "Mx", "My", "Mz", "notes"], [
  ["NL01", "", "G", "", "", "", "", "", "", ""],
], [14, 14, 14, 14, 14, 14, 14, 14, 14, 28]);

setupSheet("Member_Loads", "杆件荷载", "分布荷载示例；具体 type 由后续分析工具解释。", ["load_id", "member_id", "case_id", "load_type", "direction", "w1", "w2", "a_m", "b_m", "notes"], [
  ["ML01", "", "Q", "uniform", "local_y", "", "", "", "", ""],
], [14, 14, 14, 18, 14, 14, 14, 14, 14, 28]);

setupSheet("Design_Controls", "设计与分析控制参数", "参数名固定，value 为填写区；后续智能体将用它们控制分析流程。", ["parameter_id", "parameter_name", "value", "unit", "required", "description", "example"], [
  ["num_stories", "层数", "", "层", "Y", "结构层数", "6"],
  ["story_heights", "层高序列", "", "m", "Y", "从底层到顶层，用逗号分隔", "3.9,3.6,3.6,3.6,3.6,3.6"],
  ["span_x", "X向跨度序列", "", "m", "Y", "从左到右，用逗号分隔", "6,6,6"],
  ["span_y", "Y向跨度序列", "", "m", "Y", "从左到右，用逗号分隔", "6,6"],
  ["seismic_intensity", "抗震设防烈度", "", "度", "N", "如有则填写", "8"],
  ["site_class", "场地类别", "", "", "N", "如 II 类", "II"],
  ["damping_ratio", "阻尼比", "", "-", "N", "动力分析阻尼比", "0.05"],
  ["analysis_method", "分析方法", "", "", "Y", "linear_static/modal/response_spectrum/nonlinear_time_history", "modal"],
], [20, 22, 30, 12, 11, 38, 28]);

// Lightweight list validation on key categorical inputs.
project.getRange("C6").dataValidation = { rule: { type: "list", values: ["概念设计", "初步设计", "施工图设计", "复核与优化"] } };
project.getRange("C7").dataValidation = { rule: { type: "list", values: ["kN-m-MPa", "N-mm-MPa", "kN-mm-MPa"] } };
wb.recalculate();

const check = await wb.inspect({ kind: "table", sheetId: "Project", range: "A1:G12", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 8 });
console.log(check.ndjson);
const errors = await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "template formula error scan" });
console.log(errors.ndjson);
const preview = await wb.render({ sheetName: "ReadMe", range: "A1:H18", scale: 1, format: "png" });
await fs.writeFile(`${outDir}/steel_model_template_preview.png`, new Uint8Array(await preview.arrayBuffer()));
const file = await SpreadsheetFile.exportXlsx(wb);
await file.save(`${outDir}/steel_modeling_parameters_template.xlsx`);
console.log(`EXPORTED ${outDir}/steel_modeling_parameters_template.xlsx`);
