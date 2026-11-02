# GB 50009-2012 附录 E 表 E.5 地区参数数据

## 文件

- `gb50009_table_e5_region_parameters.csv`：Excel 可直接打开的 UTF-8 BOM 长表。
- `gb50009_table_e5_region_parameters.json`：与 CSV 同记录的 UTF-8 JSON 数组。
- `gb50009_table_e5_review_queue.csv`：需要人工看原扫描页核对的记录子集。
- `gb50009_table_e5_qa_summary.json`：记录数量与状态统计。

## 范围与来源

从本地规范 PDF《GB50009-2012 建筑结构荷载规范》附录 E 表 E.5 提取全国城市/气象站参数。表格扫描页为 PDF 第 111–158 页，对应规范印刷页第 103–150 页。每条记录保留城市、省级行政区、参数名、值、单位、重现期、规范版本、条款、PDF 页码、印刷页码和来源文件。

参数包括：基本风压（10/50/100 年）、基本雪压（10/50/100 年）、基本气温最低/最高值（按 9.2.1 的 50 年口径）、雪荷载准永久值系数分区、站点海拔。雪荷载分区和海拔本身没有重现期，字段留空。

## 字段与口径

- `province`、`city`：表 E.5 的行政区/站点名称；部分历史站名按规范原表保留。
- `parameter`：机器可读参数标识；单位见 `unit`。
- `return_period_years`：风压/雪压列中的 R=10、50、100；基本气温为 50。
- `standard_version`、`standard_clause`：来源规范版本及对应条文（7.1.3、8.1.3、9.2.1 或 E.5）。
- `pdf_page`、`printed_page`：分别是 PDF 物理页码和规范印刷页码。
- `source_cell_text`、`ocr_confidence`、`review_status`：保留 OCR 依据和复核状态。
- `altitude_m`：该站点的海拔，作为同一站点各参数记录的附带元数据；另有 `station_altitude` 参数行。

## 校对状态与使用限制

已按表格行对齐 667 个站点，共生成 6,670 条记录；检查了页码映射、行数和省份分组，并对城市名漏识的记录依据扫描页补录。扫描页 111、120、121、124、142、147、152、154 做了目视抽查。其余数字主要经 OCR 提取，不能视作已逐格人工认证的规范数据。

`review_status` 中：

- `ocr_value` / `ocr_high_confidence`：OCR 识别值；仍应结合来源页复核后用于工程设计。
- `low_confidence_review`：OCR 置信度偏低。
- `null_unread_or_dash_review`：未识别到数值；可能是原表横线（无统计值），也可能是 OCR 漏识，不能直接当作零。
- `out_of_range_review`：识别结果超出参数合理范围，已将 `value` 置空。
- `decimal_normalized_review`：OCR 只识别到两位数字，按 `0.xx` 格式暂存并标为待核。
- `city_row_review`：城市行名识别置信度低，该行数值需核对对应城市。
- `manually_read_from_scan` / `manually_corrected_from_scan`：城市名已对照扫描页人工补录或订正。

对缺失值不插值、不补零、不猜测。应优先从 `review_queue` 逐项对照 PDF 页面校正后，再将通过复核的记录导入 RAG/计算流程。此表只包含气象荷载与气温参数，不包含抗震设防烈度、基本地震加速度、安全等级、场地类别或地面粗糙度；这些需要独立的现行规范/项目资料来源。
