"""Index and verify the isolated Power preview without touching the report."""
import json
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image
from power_m0_preview_data_20260907 import ROOT, FINAL, OUT, digest

FIGURES=[
    ('current_power_scaling','电流与估计输出功率随 N 变化','采用最新 M0 电流；功率为保留的 SOURCE 电压乘以各支路电流之和，不含 Teensy USB 和稳压器损耗。'),
    ('voltage_scaling','源端与模块端电压','采用最新模块端电压，SOURCE 沿用已确认未变的记录；MIN–MAX 为仪表记录范围。'),
    ('module_voltage_drop','空载压降、满载压降及对应差值','第三幅热力图逐组合、逐模块显示满载压降减去空载压降：增加用正号，减少用负号，不变为0，未连接模块为空位。u 表示用户确认的 3.251 V，错误照片已排除。'),
    ('module_drop_N1_N4','N=1～4 的压降散点与均值','每个散点为一个组合；菱形为均值。仅 N=2、3 可计算组合间样本 SD。'),
    ('single_module_screening','单模块不同状态的电流比较','连续传输状态下 M0 空载和满载采用最新电流；阻塞状态沿用原记录。'),
    ('branch_current_balance','各模块支路电流随 N 变化','M0 最新五组电流和此前两组逐点复测已纳入；其他支路读数保留。'),
    ('temperature_scaling','温度随 N 变化','温度测量未更新，本图沿用原数据；图形重新导出，不代表新增温度实验。'),
    ('independent_current_prediction','由 N=1 参考电流预测多模块电流','M0 的 N=1 参考值已更新，并重算所有组合的预测差值。')
]

def main():
    source=json.loads((OUT/'data/source_manifest.json').read_text(encoding='utf-8'))
    for name,expected in source['generated_csv_sha256'].items():
        assert digest(OUT/'data'/name)==expected,name
    manifests=[json.loads((OUT/name).read_text(encoding='utf-8')) for name in ('figures/base_figure_manifest.json','drop_figure_manifest.json')]
    indexed={entry['stem']:entry for manifest in manifests for entry in manifest['figures']}
    assert len(indexed)==8 and 'module_drop_mean_by_N' not in indexed
    for item in manifests[0]['inputs']:
        assert digest(item['path'])==item['sha256'],item['path']
    for name,expected in manifests[1]['source_hashes'].items():
        assert digest(OUT/'data'/name)==expected,name
    difference=json.loads((OUT/'data/load_difference_manifest.json').read_text(encoding='utf-8'))
    assert digest(OUT/'data/load_voltage_drop_changes.csv')==difference['output_sha256']
    assert digest(OUT/'data/branch_readings.csv')==difference['source_sha256']
    delta_semantics=indexed['module_voltage_drop']['semantics']
    assert delta_semantics['change_comparisons']==difference['paired_module_cells']==32
    assert delta_semantics['change_color_scale']['data_min']==float(difference['minimum_mV'])
    assert delta_semantics['change_color_scale']['data_max']==float(difference['maximum_mV'])
    checks=[]
    for stem,title,description in FIGURES:
        entry=indexed[stem]
        for item in entry['files']:
            assert digest(OUT/'figures'/item['name'])==item['sha256']
        p=OUT/'figures'/f'{stem}.png'
        with Image.open(p) as img:
            assert img.width>1500 and img.height>1000
            dimensions=list(img.size)
            img.verify()
        svg=(OUT/'figures'/f'{stem}.svg').read_text(encoding='utf-8')
        assert 'Not applied to report' in svg
        if stem in ('voltage_scaling','module_voltage_drop','module_drop_N1_N4'):
            assert 'pending' not in svg.lower() and 'provisional' not in svg.lower()
        checks.append(dict(stem=stem,title=title,dimensions_px=dimensions,files=entry['files']))
    changed=[]
    for rel,h in source['protected_files_before'].items():
        p=FINAL/rel
        current=digest(p) if p.is_file() else None
        if current!=h:
            changed.append(dict(path=rel,before=h,after=current))
    # Other agents may be updating unrelated sections; never overwrite their work.
    protected_power=[p for p in source['protected_files_before'] if
        '/figures/power/' in p.replace('\\','/') or p.endswith('power.tex') or
        p.startswith('power scalability') or (p.startswith('main') and p.endswith('.pdf'))]
    for p in protected_power:
        assert digest(FINAL/p)==source['protected_files_before'][p],p
    markdown='''# Latest M0 retest: Power figure preview

This page is an isolated preview. It has not been copied into the manuscript or used to overwrite report artwork. Inputs are the report v2.4 compiled view plus five pointwise M0 retests.

**Confirmed:** the N=1 M0 ZERO voltage photo assignment and 3.252 V value were user-confirmed, giving a 28 mV drop. An asterisk marks a pointwise retest. For N=2 M0+M1 ZERO, the user-confirmed M0 voltage is 3.251 V for the representative, MIN and MAX fields; the wrongly assigned photo is excluded.

The mean voltage-drop heatmap was removed from this preview. The combination figure has three panels: ZERO, MAX, and MAX minus ZERO. The first two panels share a data-derived drop scale; the third is a separate diverging scale centred at zero. The third panel is a difference between two recorded conditions, not a new measurement or repeat.

SOURCE, other modules and temperature values follow the retained records. The view still contains 30 combination/load entries and 64 module readings; pointwise retests do not add complete-configuration repeats. SD denotes between-combination sample spread, not repeat-experiment error.

| M0 condition | Latest current / mA | Latest module voltage / V | Retained SOURCE / V | Drop / mV |
|---|---:|---:|---:|---:|
| N=1 ZERO | 18.018 | 3.252 (user-confirmed) | 3.280 | 28 |
| N=1 MAX | 19.675 | 3.249 | 3.281 | 32 |
| N=2 M0+M1 ZERO | 17.941 | 3.251 (user-confirmed) | 3.281 | 30 |
| N=2 M0+M2 ZERO | 17.969 | 3.251 | 3.279 | 28 |
| N=2 M0+M3 ZERO | 17.956 | 3.250 | 3.279 | 29 |

'''
    for i,(stem,title,desc) in enumerate(FIGURES,1):
        if stem=='module_voltage_drop':
            scale=indexed[stem]['semantics']['color_scale']
            desc+=f" 色标自动范围为 {scale['vmin']:g}–{scale['vmax']:g} mV，两负载面板共用。"
            ds=indexed[stem]['semantics']['change_color_scale']
            desc+=f" 差值面板独立采用 {ds['vmin']:g} 至 +{ds['vmax']:g} mV、以0为中心的色标。"
        path=(OUT/'figures'/f'{stem}.png').as_posix()
        svg=(OUT/'figures'/f'{stem}.svg').as_posix()
        markdown+=f'## {i}. {title}\n\n{desc}\n\n![{title}](<{path}>)\n\n[PNG](<{path}>) · [SVG](<{svg}>)\n\n'
    markdown+='''## Data and reproduction

Preview data are in data/ and figures are in figures/. Provenance and hashes are recorded in data/source_manifest.json, figures/base_figure_manifest.json, drop_figure_manifest.json and preview_manifest.json.

Paired differences are in data/load_voltage_drop_changes.csv, with 32 module pairs and both SOURCE/module voltages and drops. The retired mean-drop artwork is preserved in the central archive.

Run from the power folder: power_m0_preview_data_20260907.py, power_m0_preview_load_difference_20260907.py, power_m0_preview_figures_20260907.py, power_m0_preview_drop_20260907.py, then power_m0_preview_gallery_20260907.py. Every output remains inside this isolated preview directory.
'''
    (OUT/'preview_gallery.md').write_text(markdown,encoding='utf-8')
    manifest=dict(created_at_utc=datetime.now(timezone.utc).isoformat(),figures=checks,
        load_difference_summary=difference,
        protected_power_and_published_pdf_files_unchanged=len(protected_power),
        other_report_changes_observed_during_parallel_work=changed,
        change_attribution='Snapshot differences alone do not identify the writer. Preview scripts only write this preview directory; concurrent main.tex/data_scalability.tex changes were not overwritten.',
        interpretation='Not applied to report by this task; no global assertion about concurrent report edits.',
        data_hashes={p.name:digest(p) for p in (OUT/'data').glob('*.csv')},
        script_hashes={p.name:digest(p) for p in Path(__file__).parent.glob('power_m0_preview*_20260907.py')},
        gallery_sha256=digest(OUT/'preview_gallery.md'))
    (OUT/'preview_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(figures=len(FIGURES),gallery=str(OUT/'preview_gallery.md'),protected_power_files_unchanged=len(protected_power),concurrent_other_changes=[x['path'] for x in changed]),ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()

