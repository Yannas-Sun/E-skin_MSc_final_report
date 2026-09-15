# Data Scalability 文档修改日志

## 2026-09-07 - M012 补测与 N=4 通过，FULL 零载主矩阵完成

- 核验6条新记录：M0_M1_M2完整补测批次三条和N=4三条，全部主窗口PASS。独立解析48,070个有效MUL1、168,243个有效ESKF并核对192,280行module_log；主窗口36,017包/126,058ESKF，CRC、内外序号、模块更新、偏移及摘要计数均无新增异常。全窗口3 PASS/3仅1 B尾片段CHECK。
- 补测M012主包率200.084479±0.057550 Hz、USB完整包5.077344±0.001460 Mbit/s，N4为200.066062±0.034040 Hz、6.747828±0.001148 Mbit/s，均n=3、段间样本SD。有效包长分别3172/4216 B。补测R3的278.7935 ms PC完成间隔对应桥端5 ms，序号连续，保留在统计中。
- 新M012保存在原组合下 `Batch_20260907_004948_668301/Repeat_1..3/`；原三条Repeat目录不搬迁、不覆盖。N4整理为 `data/FULL/N=4/200Hz/M0_M1_M2_M3/Repeat_1..3/`。36个原文件208,073,646 B搬迁前后SHA256一致。
- FULL零载主矩阵选取15种组合各一个完整三次批次，45条全部主窗口PASS：M012整批使用补测batch，其余使用原批次，包括原M013低率PASS。选择不按帧率筛选单条。原M012失败和两条合格记录仍保留，旧两条PASS作为补充；不能以补测通过改写历史失败。
- 总索引48条/47主窗口PASS/1 CHECK，288原文件、16实际批次。新增primary_matrix.csv与primary_matrix_selected/selection_reason/replacement_batch_id；group_statistics明确改为45条主矩阵，另存全部47 PASS辅助统计、48条诊断统计及逐批统计。M012分别为主n3/batch1、全部PASS n5/batch2、全部记录n6/batch2。选择清单位于 `analysis/20260907_full_completion_review/primary_selection.json`。
- 更新data总览、FULL主矩阵总表、N3补测与N4说明，并保存修改前派生文档。独立审计、时间检查、路径映射和搬迁验证均位于 `analysis/20260907_full_completion_review/`。原数据、旧审计、GUI、设备固件、论文和图表未修改；此完成状态只覆盖FULL零载。

## 2026-09-07 - N=3 四种 FULL 零载组合已整理，保留一条主窗口失败

- 固定核验N=3四种组合共12条，每组一个batch、Repeat 1/2/3，FULL、zero_load、目标200 Hz，每次40 s保留前10 s。主窗口11 PASS/1 CHECK；全窗口4 PASS/8 CHECK，不能照抄此前全部主窗口通过的结论。
- 原日志口径：96,120个候选、96,119个外CRC有效包，288,357个有效ESKF；主窗口72,029候选/72,028有效包。逐行核对384,476行module_log，独立结果与原日志/summary一致。标准包长为3172 B。
- M0_M1_M2第一次（20260907_000133_670681）在19.4723392 s有真实完整性异常：seq1675977头到1675978头相隔2148 B，比声明长度短1024 B；1675978完整有效包仍在raw中，但被实时解析器越过。Session缺号2不能写成两个原始包都丢失。独立raw扫描额外恢复一个有效包作为证据，不回填日志/summary，不据此改为PASS；故障来源仍未定位。
- M0_M1_M3第三次为PASS但帧率199.123828 Hz，末段存在123 ms桥端入队间隔，另有301.3735 ms PC完成时间间隔及1020 B截止半包。保留在性能统计，不因较低帧率剔除；时钟字段不能直接证明物理扫描丢失或SPI饱和。
- 将12条全部保留并整理至 `data/FULL/N=3/200Hz/<组合>/Repeat_1..3/`，包括异常Repeat_1。72个原文件共364,788,907 B，搬迁前后SHA256一致，原数据/状态/元数据/嵌入旧路径不修改。证据、路径映射、raw和时间审计位于 `analysis/20260907_n3_full_review/`。
- 性能汇总按主窗口完整性过滤，M0_M1_M2有效n=2，其他组n=3；全部三条另列all_runs_diagnostic_statistics，异常仍进入可靠性评估。总索引现有42条、14个配置、252原文件，增加main_eligible与错误/时间备注；无错误性能窗口41条。还需补齐M0_M1_M2一条合格窗口及N=4三条，不能将N=3记成全部合格。
- 未更新设备固件、GUI或论文图表；保留N=1/N=2及历史审计。批次内时间重复不作为三个独立装配Block。

## 2026-09-06 - 完成 N=2 六种 FULL 零载组合的核验与整理

- 固定核验23:22:05–23:48:31（英国当地 +01:00）的18条完成记录：四槽位任取两个的六种组合，每组一个batch、Repeat 1/2/3；FULL、zero_load、目标200 Hz，每次40 s保留前10 s。18个主窗口全部PASS。
- 独立解析144,212个完整MUL1、288,424个有效ESKF，逐行核对576,848行module_log；主窗口108,109个MUL1和216,218个ESKF。包长统一2128 B，内外CRC、序号、模块模式、日志偏移/数量和会话错误增量均无异常。
- 全窗口2条PASS、16条CHECK；后者仅由截止时1 B尾片段导致。17个起点跨界包中11个有真实前尾/后首字节验证，六个批次首段的缺失magic前缀仍明确作为推断；原始检查状态保留。
- 将18个时间戳目录整理至 `data/FULL/N=2/200Hz/M0_M1..M2_M3/Repeat_1..3/`。108个原文件共393,046,829 B，搬迁前后SHA256一致；run_id、batch_id、Repeat、嵌入的旧路径及所有原始内容不修改。
- 新增N=2组/组合说明、均值±样本SD与n、逐次索引、路径映射和独立审计；证据位于 `analysis/20260906_n2_full_review/`。更新data总README，并合并N=1/N=2为30条记录、10个配置、180个原文件的CSV索引。历史数据与N=1审计原样保留。
- FULL零载按每组合三段的当前主矩阵完成30/45段，剩余N=3四种组合和N=4一种组合。n=3仍是同一setup的连续时间重复，不写成三个独立Block；本次不替换论文或旧图。

## 2026-09-06 - 核验并分类新采集的 12 条 FULL 单槽位零载记录

- 审计本次固定快照：22:59:34–23:11:09（英国当地 +01:00），FULL、zero_load、N=1、目标200 Hz，M0–M3各三次。全部主窗口PASS；独立核验96,193完整MUL1/ESKF、主窗口72,096包，内外CRC、模块模式、序号与日志offset均一致。全窗口CHECK唯一原因是每段末尾1 B片段，不要求因此重录。
- 按原FULL层级将12个时间戳目录整理为 `data/FULL/N=1/200Hz/M0..M3/Repeat_1..3/`。保留全部原始文件、run_id、batch_id、Repeat和summary中的采集时路径；72个文件共159,181,044 B，搬迁前后SHA256全部一致。
- 新增data总README、组/槽位目录说明、逐次run_index、段间均值/样本SD/n的group_statistics、逐文件path_map及搬迁验证。完整证据、可复现只读审计脚本和整理计划位于 `analysis/20260906_current_data_review/`。
- 每槽位n=3表示同一setup连续时间窗口，batch_n=1；不充当三个独立装配Block。后续批次不得覆盖Repeat目录。未修改原始测量或历史归档，未更新报告和旧图；schema2新分析必须使用main窗口。

## 2026-09-06 - 修复录制启动时清空半包导致的假跳号

- 原 GUI 在每次开始录制时重置 PacketFramer，丢弃已收到的半包前缀，下一完整包触发会话 seq gaps/lost 增加；DELTA 还可能产生连带缓存链错误。改为会话解析缓冲、序号与 DELTA 缓存连续运行，录制文件使用相对于本段的 raw_offset。
- 跨起点包仍正常参与实时解析，但只保存本窗口实际收到的原始后缀。用 capture_start_boundary 事件、计数和 known_start_boundary_bytes 单列，不回填录制前字节，不计入本文件完整包率、K/q，也不伪造文件内 DELTA 基线。真实跳号、CRC、模块和解析错误保留。
- GUI 的 lost 标签改为 missing MUL1，说明它是按 MUL1 序号估算的缺包数量，不能直接解释为 STM32 物理扫描丢失。
- 只读审计当前三段 FULL/M0：前两段启动各增加一次会话跳号，第三段没有增加。R1 尾部与 R2 开头可拼出序号801025的完整包，内外CRC通过；三段主窗口均PASS。详细证据见 analysis/20260906_record_boundary/ANALYSIS_CN.md；原始数据、packet_log和summary均未修改。
- 验证：20项记录后端、26项GUI/串口集成、7项检测及解析器自测通过，包含FULL/DELTA三连录半包边界和真实缺包保留。修改前备份、测试暂存和部署哈希位于 docs/Final/tmp/gui_stream_boundary_20260906。重启GUI生效，设备固件不变。

## 2026-09-06 - 每次 Record 自动连续录制三次

- GUI 按钮改为 Record x3，每次点击冻结同一配置并由串口线程自动完成三次独立录制。默认每次40 s、每次前缀10 s，共约120 s；三份原始数据和逐段统计分别保存。
- Repeat 不再手选，自动编号1/2/3；三段共享batch_id、模块清单和Block。保存每段开始时的检测快照，但不因模块未更新而缩小预期N。这是同一设置下的连续时间窗口，不是自动完成三个独立装配区组或动态重新加载。
- Stop 保存当段并取消余下；断线、启动或写入/收尾失败取消后续。普通完整性CHECK保留并继续，不自动重试覆盖。暂停热力图不暂停批次；批次内禁止从GUI改变模式和扫描率。
- 原单次计划repeat保留为planned_repeat；CSV仍为原单次/区组设计，不将三个自动窗口写作完成三个计划行。当前FULL零载15种组合各点击一次即可产生45段。
- 验证：22项GUI/串口集成、13项记录器、7项模块检测及解析器自测通过；包括Stop边界、断线、写入失败、双击和设置窗口打开时三连录。主界面/设置截图检查通过。已部署到原GUI目录，修改前备份与部署哈希位于 `docs/Final/tmp/gui_repeat3_20260906`；无实机采集或固件变动。

## 2026-09-06 - 自动模块识别与简化设置

- 手动录制从近期有效协议帧自动确定通信槽位和模式，并在 Record 时锁定预期清单；录制期间缺失更新不会通过缩小 N 被隐藏。开始前再次核对新鲜度；计划录制保留 CSV 预期清单。
- Settings 移除模块、模式、扫描率、路径等重复输入，改为人工条件的单选项及可选备注。目标扫描率、SPI 和阈值注明控制/本地配置来源，实际包率单独测量；不声称从设备读回。
- Settings 打开时暂停热力图定时刷新，串口接收、解析、原始数据录制继续。Save/Cancel/窗口关闭后恢复并显示最新帧。
- Record 不再额外发送 MODE/SCAN_HZ 命令，直接记录当前数据流。模块编号仍为 CS/IRQ 槽位，无唯一板卡身份字段；相关说明已加入当前 report 2.0 正文与协议附录，并更新 PDF。
- 验证：14 项 GUI/串口集成、7 项检测、13 项记录后端测试及解析器自测通过；检查设置窗口暂停期间原始数据完整、关闭恢复绘制、录制期模块清单固定，界面截图无重叠。只做离线验证，没有新增实机实验数据。
- 已更新原 four-module-variable-spi GUI 路径；修改前备份及部署哈希位于 `docs/Final/tmp/gui_auto_settings_20260906`。重启 GUI 后生效，STM32/Teensy 固件不变。

## 2026-09-06 - 新版 GUI 实验记录与历史归档

- 更新 four-module-variable-spi 的 PC GUI：支持半天实验计划逐行选择、条件与模块映射编辑、可配置录制/前缀时长、停止录制和事件标记。
- 新记录保存所有接收到的原始字节，并分别统计全程与主分析窗口；增加逐模块 K、ESKF 比例、模块缺失更新、CRC/缓存链与本次计数差。未改变 STM32/Teensy 固件和 USB 帧格式。
- 将活动 data 中的 88 次实验、470 个文件（503,037,879 B）整体移至 `history/pre_variable_spi_20260906/data`。移动前后全部文件 SHA-256 一致；保留原始内容，通过 archive_manifest.json 和 path_map.csv 追踪路径。
- 重新创建空的活动 data 目录，供新版 GUI 采集。Power 和 Calibration 不在本轮重测或归档范围内。
- 绘图脚本支持显式 --data-root，历史分析默认使用归档路径；不自动将历史记录混入新版实验。新版图表的 run 选择和主窗口统计适配仍需在采集后完成，现有报告与图表未重生成。
- 旧格式绘图/审计入口遇到 schema_version>=2 会明确停止，提示使用 scopes.main 和显式 run 选择，避免缺少旧字段时静默生成零值或混用全程与主窗口统计。
- 验证通过：13 项录制后端测试、8 项 GUI/串口集成测试、GUI 布局检查，以及含 212 个 STM32 编码帧的原生协议回归。历史异常记录回放识别出 6 次模块未更新。尚未连接设备执行新实验。

## 2026-09-03 - Separated the enlarged Figure 4.3 legends

- Moved the enlarged legends lower in the USB and Host SPI source panels so
  they remain separate from the enlarged x-axis titles.
- Data, calculations, axes ranges and plotted meanings were unchanged.

## 2026-09-03 - Enlarged Figure 4.3 panel typography

- Increased the legends, axis titles, tick labels and numeric annotations in
  all four Figure 4.3 source panels.
- Data, calculations, axes ranges and plotted meanings were unchanged.

## 2026-09-03 - Enlarged legends in Figures 4.1--4.3

- Increased legend text in the combined DELTA record figure, the DELTA
  demand overview and the four-panel USB/HOST SPI overview.
- Data, calculations, axes, colours and plotted meanings were unchanged.

## 2026-09-03 - Restored per-panel DELTA y-axis ranges

- Restored independent y-axis limits for the four-panel DELTA composite so
  panels (a) and (b) retain the original single-module scale rather than the
  larger four-module range.
- The plotted records, x-axis, colours and calculations are unchanged.

## 2026-09-03 - 合并 Figure 4.1 的四个 DELTA 面板

- 将原 Figure 4.1 和 Figure 4.2 合并为一个四面板竖向图
  `08_delta_combined_results.png/.pdf`。
- 面板标记为 (a)--(d)，依次表示单模块无负载、单模块大面积动态负载、
  四模块无负载和四模块全覆盖同时负载。
- 报告仅引用合并后的 Figure 4.1；原两张两面板图保留为历史导出，原始数据和计算未修改。

## 2026-09-03 - Host SPI 统一采用无填充 DELTA

- 将 Host SPI 统一建模为只传输有效 DELTA 字节，不发送固定槽位填充，
  不叠加 USB 侧的 MUL1 外层封装。
- 更新 Host SPI 理论图、交点表、figure manifest、README 与独立
  Data Scalability 文档；Host SPI 曲线现在对应 K=0、240、480 三种
  DELTA 活动量。
- 更新理论测试，使其验证无填充 DELTA 公式及各活动量下的带宽交点。

## 2026-09-03

- Figures 4.1 and 4.2 use `#7BB6BA` for the main DELTA trace and `#B8442D`
  for all three horizontal reference/mean lines.
- The horizontal axes in Figures 4.1 and 4.2 use Dark Charcoal `#3D3539`.
- The three horizontal references are differentiated as zero-load `#596073`,
  recorded mean `#9D725F`, and FULL `#B8442D`.
- Figure 4.3's `K=240` curves now use `#8B84A3` in the USB and Host SPI
  panels.
- Figure 4.4's four-dimensional overview now uses `#8CD1B2` for the
  `N=50` curve previously shown in `#45728F`.
- Figure 4.4's `N=50` curve is restored to `#45728F`; its 3D surface now
  uses a `#45728F` to `#8CD1B2` gradient.
- Removed the surface mesh from Figure 4.4 while retaining the 3D coordinate
  grid and the right 2D reference grid for readability.
- Restyled the Figure 4.4 coordinate grid as a clearer three-dimensional
  framework with lightly tinted panes; the sloped surface remains ungridded.
- Replaced the pane-only reference grid with an explicit three-plane X/Y/Z
  coordinate lattice (XY, XZ and YZ); the data surface remains ungridded.
- Reverted the latest three-plane coordinate-lattice restyling in Figure 4.4;
  the prior default 3D coordinate grid is restored while the data surface
  remains ungridded.
- Restored Figure 4.4 to the screenshot-matched rendering: semi-transparent
  `#45728F` to `#8CD1B2` surface gradient with its original fine surface mesh.
- Removed the integrity/transfer-status chart that occupied Figure 4.5 from
  the final report body. Replaced it with a text statement that all recorded
  experiments completed data acquisition; existing `CHECK REQUIRED` integrity
  records remain explicit and are not relabelled as full validation passes.
- Rebuilt Figure 4.3 so each of its four source panels keeps its own aspect
  ratio and vertical geometry; the composite is now placed at `\textwidth`
  in LaTeX so it stays within the document limits without distorting panels.
- Updated Figure 4.7's voltage-drop matrix to a sequential gradient from
  `#0F9EA8` to `#45728F`; data, normalization range and annotations are unchanged.
- Reduced the opacity of Figure 4.4's sloped surface from `0.78` to `0.58`
  so the underlying 3D coordinate structure is easier to see; surface colours,
  mesh, axes and data are unchanged.
- Changed Figure 4.6's compliance-band fill to translucent `#7BB6BA` and
  changed the `Source mean` curve and labels to `#D7BBA5`; thresholds, data and
  axes are unchanged.
- Removed the mesh lines drawn on Figure 4.4's sloped surface while retaining
  the 3D coordinate grid, surface transparency, colours and all data.
- Updated Figure 4.7 so its minimum-value colour is `#DBD4CC`, with a
  continuous gradient to the maximum-value colour `#45728F`; data and scale are unchanged.
- Updated Figure 4.8 so per-cell traces use `#0F9EA8`, measured points use
  `#9D725F`, and the connected mean/model lines use `#3D3539`; data and axes are unchanged.
- Reduced the height of Figure 4.4 panel (b) to 80% of its previous height
  while preserving its width, axes, ranges and plotted data.
- Reduced each Figure 4.3 overview panel to the same 80% height proportion
  while preserving each panel's width, order, source artwork and data.
- Recoloured Figure 4.4 for clearer comparisons: N=1 uses `#8B84A3`, N=25
  uses `#7BB6BA`, N=50 uses `#B8442D`, and N=100 uses `#9D725F`; the surface
  gradient remains `#45728F` to `#8CD1B2`, with `#D7BBA5` surface edges and
  `#DBD4CC` coordinate reference grids.
- Restored Figure 4.3 panels to 100% height and matched its left/right column
  widths and spacing to Figure 4.4 (`width_ratios=[1.16, 0.84]`).
- Trimmed unused white margins from the four source panels before composing
  Figure 4.3 so the plotted content is larger without changing panel data.
- Recoloured the six Figure 4.5 load-condition bars in order with
  `#8B84A3`, `#7BB6BA`, `#B8442D`, `#9D725F`, `#D7BBA5` and `#DBD4CC`.
- Removed Figure 4.5 from the final report body; its source data and generated
  auxiliary artwork remain available outside the report flow.
- Restored Figure 4.4's original curve mapping: N=1 `#7BB6BA`, N=25
  `#B8442D`, N=50 `#45728F`, and N=100 `#596073`; its original surface-edge
  and coordinate-grid styling is also restored.
- Figure 4.3 now explicitly uses equal 1:1 row heights, preserving 100% height
  for all four panels while retaining the Figure 4.4 left/right width ratio.
- 将统一图表配色更新为 `#596073`、`#7BB6BA`、`#DBD4CC`、`#D7BBA5`、
  `#9D725F` 和 `#B8442D`。
- 需要直接比较的序列使用青蓝—砖红或青蓝—深灰高对比组合，并保留
  线型、标记和图案等冗余编码。
- 未修改原始数据、计算逻辑、坐标范围、文字内容或科学含义。

## 2026-09-03

- 将数据可拓展性图表、DELTA 帧图和数据流图统一为低饱和度青绿—蓝灰
  科研配色，并集中引用 `docs/Final/figure_style.py`。
- 统一坐标轴、文字、网格、图例、透明度和静态导出背景；连续图表改用
  由青绿色派生的连续色图。
- 未修改原始数据、计算逻辑、坐标范围、文字内容或科学含义。
- 对多条件柱状对比图增加颜色区分度，并保留原有条件顺序与数值标注。

## 2026-09-02

- 调整 02E 和 USB/HOST SPI 总览的面板标记位置，并扩大总览的标题遮罩区，确保图内仅保留 (a)–(d) 面板标记；所有面板说明继续放在报告题记中。

## 2026-09-02

- 按最新排版要求移除 02E 左侧三维图中的 FULL boundary at K=480 曲线及其图例、标题说明；右侧 FULL 参考虚线保留用于曲线比较。

## 2026-09-02

- 移除 02E 左侧三维 DELTA 图中的 FULL 参考斜面，保留 K=480 处的 FULL 边界线及右侧各模块数的 FULL 参考线，避免参考平面遮挡主体曲面。

## 2026-09-02

- 将 08A/08B 中水平参考线和均值线的数值移到绘图区右侧独立标注区，并用引线连接，避免与折线数据重叠。

## 2026-09-02

- 优化 02E 三维图：降低 FULL 参考斜面的透明度和网格干扰，并加粗 DELTA 与 FULL 在 `K=480` 处的交界线，使主体 DELTA 曲面保持清晰。

## 2026-09-02

- 新增 `02e_delta_usb_k_overview_200hz.png/.pdf` 及配套 CSV：固定 200 Hz，左侧为 N–K–USB 传输量三维模型并叠加当前 FULL 参考斜面，右侧为选定模块数的 DELTA 曲线及对应 FULL 传输量标记。
- 更新生成脚本、README 和 `figure_manifest.json`；新图保留为独立导出，不改变原有 02A–D 和四图总览。

## 2026-09-02

- 更新 `08a_delta_single_module_results` 和 `08b_delta_four_module_results`：去除动态阶段背景色，在所有水平参考线最右侧标注数值，并在下方动态面板标记最高普通 DELTA 帧。
- Figure 4.3 改用既有的 USB/HOST SPI 四图总览；报告图题同步精简，不再列出具体实验数值。
- 生成脚本现在会自动同步两张 PDF 到报告的 `figures/data` 目录，避免报告继续引用旧副本。

## 2026-09-02

- 新增 `figures/source/generate_delta_composite.py`，从四个指定实验目录的原始 `packet_log.csv` 和 `summary.json` 重新生成两张上下排列的 DELTA 结果图：`08a_delta_single_module_results.png/.pdf` 和 `08b_delta_four_module_results.png/.pdf`。
- 两张图分别比较 N=1/M1 的无负载与大面积动态负载，以及 N=4/M0–M3 的无负载与全覆盖同时负载；图内仅保留必要的坐标、图例和数据编码，实验条件及数值说明移至报告图题。
- 原始实验文件和各实验目录中的独立图未修改；报告使用矢量 PDF 版本。

## 2026-09-02

- Rewrote `docs/Data_Scalability.md` as a concise English, report-oriented chapter with the structure: Introduction, Methodology, Results, Discussion, and Conclusion.
- Kept the main argument focused on data scalability: FULL versus DELTA, USB payload growth, module scaling, activity dependence, and reconstruction integrity.
- Positioned the current DELTA implementation accurately as event-inspired synchronous transport, not a fully asynchronous AER/event-driven sensor.
- Added verified references on AER, asynchronous event sensing, and event-driven tactile encoding at the relevant background and discussion points.
- Added `bibs/data_scalability.bib` for later LaTeX report integration.
- No firmware, GUI, raw experiment data, or figure files were changed.

## 2026-09-02

- 按最新排版要求更新图 02：02C 的模块范围改为 N=1–10；移除 02D 局部放大图，将 10 MHz 与 41 MHz 交点直接标记在主图；删除 02A–02D 图下方的解释性备注并重新生成四张独立图及 2×2 总览。未修改固件、GUI 或原始实验数据。
- 微调 02D 横轴刻度：移除与 41 MHz 交点 N≈24.55 重叠的 N=25 普通刻度，保留交点标签以避免视觉重叠。
- 图 02 链路拆分（取代下方早期混合图）：生成 02A USB 三维图、02B USB 200 Hz 曲线、02C HOST SPI 三维图、02D HOST SPI 200 Hz 曲线四张独立图。02A 为 N=1–100、f=0–700 Hz；02B 为 N=1–700、200 Hz；02C 为 N=1–10、f=0–700 Hz；02D 为 N=1–30、200 Hz。原 `02_usb_theoretical_3d` PNG/PDF 原位更新为 02A，保留已有链接。
- USB 两图及其 CSV 移除所有 SPI 参考，保留 USB 480 Mbit/s 原始信号速率参考；FULL 的 200 Hz 交点 N≈286.24 投影至横轴，K=240、K=0 的图外交点写入说明。明确这是应用数据需求与原始速率参考的比较，不是已实现的模块容量。
- HOST SPI 重新按当前代码每模块固定 1044 B（含填充）建模：`R=8×1044×N×f/10^6 Mbit/s`；FULL 与 DELTA 重合，不叠加 USB 封装或并行 MOSI 命令。分别标注当前 10 MHz 与假设 41 MHz 原始带宽；200 Hz 放大图显示 N≈5.99、24.55 的理想时钟预算交点，未声称实际容量或去填充已实现。
- 新增三份独立理论 CSV，更新原 USB CSV 和交点 CSV；交点表按 `link` 明确区分 USB/HOST SPI。同步更新 README、生成清单和可复现脚本；增加 `test_theoretical_links.py`，12 项公式、边界、交点、表格及输出检查全部通过。四图逐一检查排版，PNG 均为 3780×2700、300 dpi，并配套 PDF。
- 本次仅更新图 02 系列及配套说明；图 01、04、05、06、07 的 PNG 哈希均保持不变。原始实验数据、GUI、STM32 与 Teensy 固件未修改。
- 追加输出质量修正：图 02A–D 的 PNG 显式转换为不透明 RGB 白底，并保留 300 dpi；公式、数据表、PDF 与实验数据不变。
- 增加 `02_four_panel_overview.png/.pdf` 总览图，将四张独立图按 2×2 排列；独立图、理论表格和原始实验数据均保留。
- 在 HOST SPI 的 02C、02D 中增加去除固定槽位填充后的 DELTA 理论值：`R=8N(84+2K)f/10^6`，用 K=0、K=240 展示；K=480 与当前 1044 B 固定槽位重合。该曲线明确标记为假设模型，未修改当前固件。

- 图 02 后续调整：右侧截面从 700 Hz 改为 200 Hz，纵轴调整为 0–200 Mbit/s；41 Mbit/s 参考线的交点增加垂直虚线、点标记和横轴模块数 N≈24.43、45.07。USB 480 Mbit/s 位于右图范围外，明确注明 N≤100 无 USB 交点；左侧 N=1–100、f=0–700 Hz 与两个带宽平面保持不变。新增交点 CSV，同步更新 PNG、PDF、README 和生成清单；未修改其他图、原始实验记录或固件。
- 按用户要求使用 `scientific-visualization` 和 `matplotlib` 技能更新图 02、05、07；增加可复用 `figures/source/report.mplstyle`，统一字体、配色、线型、图例、留白及 300 dpi PNG/PDF 输出。
- 图 02 的理论范围扩展为 N=1–100、f=0–700 Hz，添加单方向 SPI 41 MHz（41 Mbit/s）和 USB 2.0 HS 原始信号速率（480 Mbit/s）参考平面，并添加 700 Hz 截面。说明其为原始速率参考，而非实测应用吞吐量。
- 修正理论图的模块 header 计数：1–4 模块保留四个 header，超过四个模块按每模块 4 B 元数据外推；统一 `H(N)=24+4max(4,N)`。DELTA K=480 与 FULL 等长，合并重叠曲面。
- 图 05 扩展至 100 模块，FULL 使用理论模型，DELTA 使用 N=4 实测平均每模块载荷（含同步帧）的条件外推；单独保留 N=1–4 实测面板、逐次记录和组平均，并保留 CHECK REQUIRED 数据。没有把外推值标成实测结果。
- 图 07 扩展为 N=1–100、K=0–480 的完整热图和代表性曲线；采用等效逻辑 round 长度 kB，说明 100 模块需要扩展当前协议与硬件，未计新分包开销。
- 按要求将图 03 `03_full_theory_vs_measured.png` 移至 Windows 回收站（可恢复），删除生成函数并更新 README 索引；不再自动重新生成该图。
- 新增 `figures/tables/` 保存理论网格、外推值和观测数据引用，新增 `figure_manifest.json` 记录软件版本、来源和假设。原始实验数据、GUI 和固件未改动。
- 已逐图检查最终排版，并核对 PNG 的 300 dpi 元数据、41 条实测引用、48,100 个 DELTA 理论网格点、N=100/f=700 的峰值和单模块 K=0 的 124 B 下界。

## 2026-09-01

- 明确当前研究范围：以 `FULL` 为基准，仅研究 `DELTA`。
- 将 `SPATIAL` 标记为暂缓、废弃方案，不纳入当前实验与结论；原有内容保留作为历史设计记录。
- 明确本章只研究数据传输量、USB 带宽和数据可拓展性；元件功耗归入下一章 `Power Scalability`，暂不通过软件优化。
- 精简范围备注，明确暂不通过软件算法减少功耗。
- 从 `Data_Scalability.md` 正文中移除 `SPATIAL` 全部章节、公式、流程和图片引用。
- 收缩实验范围：合并 `FULL` 与 `DELTA` 的活动量对比，重点验证 `DELTA` 对模块扩展和带宽限制的改善；协议、阈值和缓存等内容仅保留为基本检查。
- 整理新增的 12 次 DELTA 无负载实验：M0–M3 各重复 3 次，统一归档到 `data/DELTA/N=1/200Hz/`，并记录逐 MUL 长度、同步帧数量、USB 数据率及完整性检查结果。
- 在 `script/plot_delta_mul_length.py` 新增 DELTA MUL 长度可视化脚本：自动读取每次实验的 `packet_log.csv`，以记录经过时间为横轴、当前 MUL1 长度为纵轴，并为每次记录生成独立 PNG 折线图。
- 将同步帧改为橙色虚线标记，并将默认输出位置改为每次实验自己的数据目录；复制当前 GUI 到 `script/four-module-fsr-monitor.py`，启动命令已切换到该副本，DELTA 记录完成后会自动启动当前实验的绘图。
- 调整绘图含义：`DELTA_SYNC` 不再作为 MUL 长度数据点绘制，只在其发生时间显示竖向虚线；蓝色折线仅表示普通 DELTA MUL 长度。
- 在 MUL 长度图中增加理论无负载参考线：当前单模块协议的最小完整 `MUL1` 长度为 `124 B`，使用红色水平线表示。
- 将 DELTA 无负载数据目录从 `.../N=1/200Hz/...` 简化为 `.../N=1/...`，因为当前全部 DELTA 测试统一使用 `200 Hz`。
- 更新 `script/plot_delta_mul_length.py`：纵轴固定从 0 开始并按记录中的最高同步帧自适应上限；根据 `updated_mask` 和各模块算法自动识别实际模块数；零负载理论线按活动模块数自动计算；不同模块的 `DELTA_SYNC` 使用不同颜色的虚线标记。
- 为现有 39 次实验补充活动模块、模块数量 `N`、目标扫描频率；为现有 Delta 记录手动补充 `Zero load` 负载条件，并修正归档后 `summary.json` 中失效的旧文件路径。
- 更新 `script/four-module-fsr-monitor.py`：后续 GUI 记录自动将活动模块、模块数量 `N`、目标扫描频率、实际观测算法和请求算法写入 `summary.json` 与 `experiment_log.md`；负载情况仍不由 GUI 自动推断。
- 修正 GUI 自动绘图触发条件：Delta 记录现在根据当前选择模式或实际观测到的 Delta 算法，并确认 `packet_log.csv` 已生成后启动 MUL 长度绘图。
- 整理最新 6 次 Delta 无负载记录：根据 `updated_mask` 检查后确认它们实际是 6 种 `N=2` 双模块组合，而不是单模块记录；已归档到 `data/DELTA/Zero_load/N=2/` 并生成 6 张 MUL 长度图。
- 更新 `data/DELTA/Zero_load/README.md`，合并 N=1 与 N=2 的实验条件、目录结构和结果汇总。
- 发现并整理 1 次额外完成的三模块 Delta 无负载记录：`M0_M1_M2`，归档到 `data/DELTA/Zero_load/N=3/`，并生成对应 MUL 长度图；Delta 汇总更新为 19 次记录。
- 更新 `script/plot_delta_mul_length.py`：为每张 DELTA MUL 长度图增加实际平均 MUL1 长度水平线，并在图例中标注具体平均值；已重新生成现有全部 19 张图。
- 调整平均 MUL1 长度线：改为蓝色实线并置于数据曲线最上层；已重新生成现有全部 19 张图。
- 整理新增的三模块 DELTA 无负载记录：将 `20260901_204308` 归档为 `N=3/M0_M1_M3`，将 `20260901_205014` 归档为 `N=3/M0_M2_M3`，将 `20260901_204633` 归档为 `N=3/M1_M2_M3`，补充条件、结果和文件路径，并为全部 22 次 DELTA 记录重新生成长度图。
- 更新 `data/DELTA/Zero_load/README.md`：总记录更新为 22 次，并补充 MUL 长度图中蓝色平均线、红色理论线和同步帧虚线的含义；记录三次新实验各存在 1 次 Delta 基础序号失配。
- 整理新增的四模块 DELTA 无负载记录：将 `20260901_205141` 归档为 `N=4/M0_M1_M2_M3`，补充条件、结果和文件路径，并为全部 23 次 DELTA 记录重新生成长度图；该记录存在 1 次 Delta 基础序号失配。
- 更新 `data/DELTA/Zero_load/README.md`：加入 N=4 结果并将汇总更新为 23 次记录。
- 根据无负载 DELTA 的三次单模块平均结果，记录 M1 为后续动态负载测试的优先模块：平均刷新率 `200.450 Hz`，用于建立稳定的动态测试基准；同时注明该选择不等同于传感器精度优于其他模块。
- 整理 M1 大面积动态负载实验的 3 次记录：归档到 `data/DELTA/Dynamic_load/M1/Large_area/Repeat_1..3/`，补充负载流程、阶段数据率、结果摘要和完整性状态，并新增该组实验的 `README.md`。
- 更新 `Data_Scalability.md`：记录 M1 动态测试已完成，三次平均数据率为 `0.5520 Mbit/s`、平均刷新率为 `199.765 Hz`；三次记录各有 1 次 Delta 基础序号失配。
- 整理 M1 小面积动态负载实验的 3 次记录：归档到 `data/DELTA/Dynamic_load/M1/Small_area_3x1.6cm/Repeat_1..3/`，记录 `3 × 1.6 cm` 负载流程、阶段数据率、结果摘要和完整性状态，并新增该组实验的 `README.md`。
- 更新 `Data_Scalability.md`：记录小面积测试平均数据率 `0.4517 Mbit/s`、平均刷新率 `200.301 Hz`，并与大面积测试进行对比。
- 整理新增 M1 高频滚动动态负载记录：使用棍子在两个 FSR 上来回滚动，30 s 记录得到 6008 个完整 MUL1，平均 USB 数据率 `0.887710 Mbit/s`，平均 MUL1 长度 `554.09 B`，所有 CRC、序号、丢帧和 Delta 基线检查均为 `0`；归档到 `data/DELTA/Dynamic_load/M1/High_frequency_rolling/Repeat_1/`。
- 更新 `plot_delta_mul_length.py`：为每张 DELTA MUL 长度图增加按活动模块数自适应的 FULL 理论 MUL1 帧长水平实线，使用当前四模块 MUL1 外壳公式 `40 + 1044N B/frame`；蓝色平均线继续保持在最上层。
- 重新生成全部 DELTA MUL 长度图，并将同步帧、理论零负载线、FULL 理论线和平均线统一写入各图例；同时在 `Data_Scalability.md` 中明确部分模块运行时固定的四个 module block header 不携带 ESKF 数据。
- 调整 `plot_delta_mul_length.py` 的图例位置：移到绘图区右侧的独立区域，避免遮挡 MUL1 曲线和水平参考线；全部 30 张 DELTA 图已重新生成。
- 再次调整 `plot_delta_mul_length.py` 的图例位置：将图例移到图形最下方并分两列排列，避免占用绘图区右侧；全部 30 张 DELTA 图已重新生成。
- 调整图表纵横比例：将绘图画布高度从 `5.5` 增加到 `7.0`，保留底部图例布局；全部 30 张 DELTA 图已重新生成。
- 降低所有 DELTA_SYNC 竖向虚线的透明度（alpha=`0.35`），减少其对数据曲线的干扰；新增 N=2 和 N=4 全部 FSR 同时全覆盖动态记录并按模块数归档。
- 更新 `Data_Scalability.md`：补充 N=2（4 个 FSR）和 N=4（8 个 FSR）同时全覆盖动态负载的实际 USB 数据率、MUL1 长度、刷新率、FULL 理论对比及完整性检查结果。
- Updated Figure 4.9 panel (a) so the dashed Identity reference line uses #7BB6BA; data, axes and all other series are unchanged.
