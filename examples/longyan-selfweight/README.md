# 龙岩四层钢框架自重案例

这是原Excel的120节点、248构件XYZ杆系，Z竖向。只施加钢框架自重，系数1；不计楼板和附加楼面荷载，不执行风震或完整组合。主梁HN600×200×11×17由用户确认；次梁H550×200×6×10、箱柱□400×400×10×10及原编号/释放/截面性质按原表保留。

input.json包含完整可执行节点、杆件、材料、截面、自重和控制字段，不依赖原用户Downloads路径。新增的1.3、1.0、400明确标记为沿用模块默认假定，未冒充用户新确认的设计条件。expected.json用于防止后续单位、几何或映射回退。

## 运行

Mac可双击项目根目录的`run_longyan_case.command`。更推荐从终端执行以下入口：

```bash
bash scripts/run_longyan_case.sh
```

该入口只选项目`.venv`或本机已有的相邻`runtime/venv`，不会修改Conda/base、安装全局依赖或启动模型API。外部虚拟环境可通过`STEELMIND_CASE_PYTHON`指定。缺少环境时会打印项目内安装命令，不自动安装。

也可用已激活的项目虚拟环境直接执行：

```bash
python scripts/run_longyan_case.py --output ./backend/artifacts/case-runs
```

本机现有隔离环境可用：

```bash
source ../runtime-env.sh
../runtime/venv/bin/python scripts/run_longyan_case.py --output ../runtime/artifacts/longyan-case
```

其他电脑首次准备环境（仅写入项目`.venv`）：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r backend/requirements.txt
./.venv/bin/python -m pip install ./backend/engineering_export
bash scripts/run_longyan_case.sh
```

不要直接执行requirements.txt文件，也不要使用全局pip。依赖下载失败时请检查网络后重试，保留证书校验。已安装依赖的环境可离线执行案例。

PDF需要本机LibreOffice；缺失时保留DOCX并将文件状态标为partial。

只做计算/复核，不生成文档可加`--verify-only`。每次生成独立子目录，runtime-info.json记录Python/库版本及实际源码位置；保留8段/16段分析、网格对照、数值审计、截面数量/长度/质量汇总、输入快照、文件哈希和summary.json。完整模式另有三维结果HTML及runs/下的计算书、结果表、DXF和ZIP；这些本地文件可离线查看，artifacts.json的HTTP地址仅供网关运行时使用。

## 判读

- numerical_audit_status：整体六分量、分段端力平衡及弯矩释放的数值一致性；不能视为结构规范通过。
- mesh_comparison_status：同一求解器8/16段的位移、应力和挠度比较；不能替代独立求解器或工程复核。
- upstream_check_summary：仍为INCOMPLETE，稳定、板件局部稳定/有效截面和整体二阶等尚未闭合。
- file_generation_status：文件是否生成，与规范结论独立。

原3D3S风震、周期和质量参考数值不用于填充本次自重结果。完整缺项处理见docs/待补充信息处理说明.md。

均布单元荷载与局部方向依据：[OpenSees官方eleLoad说明](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/pattern/PlainPatternloadcommands/eleLoad.html)。本通道使用Linear变换，未使用官方提示不支持该荷载的三维Corotational组合。


## 方案图纸

CLI完整模式和网页工作流3现生成25页图册（4层平面、10立面、8页构件表、3截面图），对应25张A3 DXF及合并PDF。CLI位于runs/explicit-编号/cad/；网页工作流3中下载钢框架方案图册.pdf，或点击二维DXF旁的预览按钮。工作流2只做分析/计算书，图纸由工作流3生成；勾选自动生成成果时会自动衔接。

原XYZ三维杆系.dxf供CAD三维打开；网页不压扁它，而是加载配套XY/XZ/YZ切片。含完整文字/标注的图纸在网页按只读LINE预览，完整图面以配套PDF/CAD为准。纸空间构件表DXF仅下载。出图质量记录.json记录覆盖构件、实际尺寸、比例、文字高度和错误；出现图纸生成缺项.json时文件状态为partial，不能视为出图全部完成。

## 2026-11-05 用户确认修正

默认输入现为72根BY次梁腹板竖直（转角0°）；原90°输入和原基线另存input-before-orientation.json、expected-before-orientation.json。orientation-comparison.json记录逐杆前后对照及参考文件哈希。未采用楼板约束。最大梁相对挠度由6.28679 mm降至0.229146 mm。验算NA按实际受力判定；翼缘和腹板筛查分别列项，仍有稳定、有效截面待补，不能将已验项通过视为构件或完整结构通过。详见docs/龙岩验算适用性与朝向修正.md。
