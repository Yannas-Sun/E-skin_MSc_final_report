# 当前记录的原版样式图

`m1_large_area_repeats.png`（300 dpi）和同名 SVG 是 2026-09-07 M1 大面积 DELTA 三次连续记录的对照图。使用当前真实数据重新绘制，没有复制参考截图的旧数值。三段是同一设置下的时间重复，不是三个独立装配或独立加载实验。

- 源记录：040621_371357、040701_400114、040741_429011，均为 M1、N=1、目标 200 Hz、large_area、both。
- 全部三段都显示，不按结果挑选片段；完整时间轴约 40 s，前 10 s 用浅色标出。右侧均值取原主分析窗口（10 s 之后），分别为 284.7、269.2、262.8 B。
- 青线只表示普通 DELTA。任何含 DELTA_SYNC 的 MUL1 包不接入普通曲线，其事件用按槽位着色的细竖虚线表示；普通曲线连接其余真实观测点。所有 ESKF 字节仍计入均值与流量，不通过画图排除成本。
- FULL 为 1084 B；K=0 理论下界为 124 B。普通帧最大值分别 1084、1082、1082 B，未将 ESKF 峰值冒充普通 DELTA 最大值。
- 竖线标记日志可识别的全部 ESKF，触发原因未知。三段独立模块内序号审查均 CHECK，属于诊断资料；原 GUI 主 PASS/全程 CHECK 保留在数据和图注中，不进入正式主矩阵。

同名 JSON 保存源记录、哈希、主窗口统计、独立审查来源与输出哈希。完整发现见 `../../analysis/20260907_delta_large_area_review/raw_audit_CN.md`。

可从 `docs/Final` 重建：

```powershell
& 'D:\study\programming\Anaconda\python.exe' -B '.\data scalability\figures\source\generate_current_delta_repeats.py'
```

现有 48 条 DELTA 的逐段图片均在各自数据目录中：`mul1_length_over_time.png` 和 `usb_throughput_over_time.png`。上述三面板图与历史论文四条件图的实验条件不同，不自动替换论文原图。
