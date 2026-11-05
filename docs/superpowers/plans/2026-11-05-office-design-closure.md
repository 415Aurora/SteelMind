# 龙岩办公楼完整荷载验算 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在用户确定的参考布置和课程设计条件下，形成可复现的上部钢框架恒活风震分析与完整验算链路，并保留失败与交接边界。

**Architecture:** 新增独立office-reference案例及办公楼设计管线，复用几何、截面、存储、CAD基础设施；不改变旧自重入口含义。规范化输入、荷载、响应和验算采用带工况/组合/来源的数据对象，生成报告、表格及三维视图。

**Tech Stack:** 项目现有Python3.11+、NumPy/OpenSeesPy、FastAPI、python-docx/openpyxl/ezdxf；只用项目虚拟环境，新增依赖先核对必要性并固定到项目依赖文件。

**Spec:** docs/superpowers/specs/2026-11-05-office-design-closure.md，必须先读用户确认条件及docs/办公楼完整设计输入核对.md。

## Global Constraints

- 旧248杆件自重案例、基线、授权朝向对照和未提交修改全部保留；不自动git提交/推送。
- 不采用楼板受压翼缘约束。面内刚性楼板已由用户确认。
- 新布置不凑参考统计数量；假定未确认不冒充输入事实。
- FAIL优先，关键MISSING不得成为PASS；文件成功与结构通过独立。
- 连接/楼板/楼梯本体/柱脚/基础的性能要求交接，不冒充其设计已完成。
- 所有产物绑定输入、配置、规范表及工具版本哈希；跨工况、跨组合的包络不是同时作用的内力向量。

## Review Focus

- 杆件被相交节点拆分后，无支撑长度仍取物理构件段，不取网格单元长度。
- 楼梯洞口扣除、承托线载与钢自重/楼板/墙质量不能重复；质量不直接复制历史汇总。
- CQC响应正负和相关性不能以各分量最大值拼接；组合追溯到实际工况与位置。
- 二阶P-Δ及假想水平力适用条件未满足时不得用μ=1；不能声称只改变换即完成直接分析设计法。
- 规范强度、抗震/重力分项系数及构造适用性按当前版本锁定；旧工具结果不作为可信通过输入。

## Task 1 输入契约与参考布置

**Files:** 新增backend/office_contracts.py、examples/office-reference/、scripts/prepare_office_case.py；修改backend/explicit_model.py的几何验证复用边界；新增backend/tests/test_office_contracts.py。
**Interfaces:** normalize_office_bundle(tables:dict)->OfficeBundle；prepare_reference_case(source:dict,assumptions:dict)->dict。

- [ ] 先写失败测试：参考柱位每层28、4个新增位置正确；X=4/34仅在Y=0/7有柱，禁止生成32柱；未确认假定保留来源状态；Project错列显式迁移；旧selfweight契约仍拒绝未支持外荷载。
- [ ] 实现节点、物理构件与相交拆分节点映射；每个计算段有physical_member_id，截面、释放、朝向与图示GL2/GL3分类可追溯。
- [ ] 将附录条件写入独立case配置，所有层/屋面/楼梯/墙线均可编辑；输出旧新几何差异及源图定位。
- [ ] 运行新契约测试和全部现有显式模型回归，检查没有修改旧fixture及expected。

## Task 2 荷载分配与质量源

**Files:** 新增backend/office_loads.py、backend/tests/test_office_loads.py；完善office-reference输入。
**Interfaces:** build_load_cases(bundle:OfficeBundle)->list[LoadCase]；build_mass_source(bundle,load_cases)->MassSource。

- [ ] 先写失败测试：矩形单向板荷载总力及力矩守恒；洞口不生成板荷载；两个楼梯区只施加承托线载；面域与梁无对应时返回MISSING而非零；重力与质量单位解析匹配。
- [ ] 实现楼面4.5/屋面5.5、办公3.5/屋面0.5及墙/楼梯采用值的分区荷载映射；每项标来源和支承边。真实节点与杆件荷载保留全局/局部方向，不静默丢失。
- [ ] 实现钢自重、墙、板、楼梯及适用活载质量的唯一分配，输出各层重心、转动惯量与总量；历史质量只列对照。
- [ ] 针对每层面域及全楼运行独立总力/力矩/质量核对，检查再细分网格不改变总量。

## Task 3 静力 模态及风震作用

**Files:** 新增backend/office_solver.py、backend/office_actions.py、backend/office_spectrum.py及对应3个测试文件。
**Interfaces:** solve_static(bundle,load_case,method)->CaseResult；solve_modal(bundle,mass_source,settings)->ModalResult；build_wind_cases(bundle)->list[LoadCase]；spectrum_response(modal,parameters)->SpectrumResult。

- [ ] 先写失败测试：简支均布梁与空间悬臂解析、载荷方向与释放、质量矩阵、单自由度谱、两模态CQC、正负方向及最低剪力调整、模式覆盖不足和刚体模态拒绝。
- [ ] 抽出受锁保护的OpenSees建模/求解公共部分；保留当前自重API与结果字段；完整入口独立接收多种荷载与面内刚性楼板条件。
- [ ] 实现节点/分布静力、模态与质量参与；风荷载按高度/体型/迎风面积生成±X/±Y；规范系数表记录版本与精确条文。
- [ ] 实现反应谱、CQC及适用方向/扭转处理；保存每模态贡献与各响应包络的语义，不制造一组虚假有符号同时端力。
- [ ] 用解析基准和8/16段或适用模态数比较验证，未收敛/质量覆盖不足不得继续生成通过。

## Task 4 组合 二阶分析与完整构件检查

**Files:** 新增backend/office_combinations.py、backend/office_stability.py、backend/office_checks.py、backend/code_tables.py及对应测试；保留explicit_checks旧入口。
**Interfaces:** build_combinations(bundle,rule_set)->list[Combination]；solve_design_cases(bundle,cases,combinations)->DesignResponses；check_office_design(bundle,responses)->DesignChecks。

- [ ] 先写失败测试：有利/不利永久作用及风震正负；SLS与ULS分开；二阶柱解析、假想水平力与μ适用性；整梁拆分不缩短侧扭段；箱形有效面积/惯性矩不覆盖毛截面；规范公式边界和FAIL/MISSING优先。
- [ ] 从现行官方/权威规范固定组合、材料、谱及控制表，交叉核对修订/勘误；不复用旧标量组合或未经核对的稳定函数。
- [ ] 实现二阶P-Δ与整体缺陷假想水平力，按5.4/8.3有效条件采用μ=1并进行柱双轴压弯/长细比检查；整体二阶系数不满足时进入改型或报告FAIL。
- [ ] 实现H梁完整无支撑段侧扭、板件应力梯度/局部稳定、箱柱有效截面及必要加劲肋；毛/有效截面、设计强度和屈服强度始终区分。
- [ ] 检查适用的层间位移、扭转、规则性、整体稳定与抗震构造条件；交接性能不标为已验证构造。
- [ ] 输出控制构件/组合/位置的详算；实际作用无法闭合的项目输出明确原因，不以NA或0代替。

## Task 5 方案迭代与工作流界面

**Files:** 新增backend/office_design.py；修改backend/app.py、backend/workflow.py、backend/explicit_viewer.py、backend/tool_sources/viewer_result_legend.js、dist/index.html；新增office集成及前端回归。
**Interfaces:** run_office_design(request,progress_callback)->OfficeDesignRun；POST /workflow/office-design/run-stream；成果入口接收office_run_id和输入哈希。

- [ ] 先写失败测试：完成但不通过、缺项、符合的三种状态；有FAIL不得被文件生成升级；长任务进度/取消/失败；两用户并发目录与求解隔离；旧selfweight和普通规则模型入口兼容。
- [ ] 先运行固定参考截面；在用户允许范围调整梁柱截面/加劲肋，保存每轮改变、控制原因与重算结果。最大迭代及停止原因显式可配置。
- [ ] 接通流式进度与当前模型/结果哈希；视图增加工况、组合、控制包络和稳定/位移控制信息；不同作用分量不伪装成同时内力。
- [ ] 运行真实HTTP链路，验证工作流2/3、模型预览和全部下载能使用相同最终方案。

## Task 6 同源成果与交接验收

**Files:** 新增backend/office_outputs.py、scripts/run_office_case.py及Mac/CLI入口；扩展CAD复用与docs/办公楼完整案例复现.md；新增报告/CAD/CLI集成测试。
**Interfaces:** publish_office_outputs(bundle,run,options)->ArtifactManifest；CLI输入为独立office-reference案例，仍只使用项目虚拟环境。

- [ ] 先写失败测试：报告、XLSX、JSON控制组合/位置/单位一致；稳定和有效截面公式数据可定位；下载路径/哈希/清单一致；缺依赖或PDF转换失败保留草稿；完整源码包独立解压复算。
- [ ] 生成完整计算书DOCX及同源PDF、模型/作用/组合/结果/验算XLSX、最终几何与截面DXF/PDF、源数据和规范表快照、新旧及迭代对照、交接性能清单。
- [ ] 完整回归与独立规范/数值审查；逐页渲染计算书和图纸，重读DXF检查尺寸/编号/截面/字高；修复后重验相关检查。
- [ ] 输出验收记录区分数值验证、规范覆盖和方案通过，明确模块边界；源码ZIP及成果ZIP均校验清单。不得宣称新机器首次安装已测，除非确实完成该验证。

## 当前进度

- [x] 用户已选完整恒活风震范围、参考图重建、面内刚性楼板。
- [x] 从WMF公式图片恢复荷载值，完成源数据与模型差异清单。
- [x] 草案经独立builder check，关键未决项已汇总为课程设计条件附录。
- [ ] 用户确认其余楼层/墙梯/支承与允许改型的条件后，按上述顺序实施。

## 最终验收状态（2026-11-05）

已按用户确认条件实施，完成参考方案及改型两轮计算、340项Python/36项Node测试、真实HTTP成果下载及源码解压复算。上方任务清单为实施前计划；最终完成项、环境未验项和工程外部边界以《办公楼模块验收记录》为准。用户已授权完成后git提交并上传GitHub；不合并主分支。
