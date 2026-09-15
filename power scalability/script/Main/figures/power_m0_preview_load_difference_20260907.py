"""Paired recorded load differences for the third preview heatmap panel."""
from decimal import Decimal as D
import csv
import json
from power_m0_preview_data_20260907 import OUT, read, write, digest


def main():
    data=OUT/'data'
    branches=read(data/'branch_readings.csv')
    pairs={}
    for b in branches:
        k=(int(b['module_count']),b['combo'],b['module_id'])
        pair=pairs.setdefault(k,{})
        assert b['load'] not in pair
        pair[b['load']]=b
    rows=[]
    for (n,combo,module),pair in sorted(pairs.items()):
        assert set(pair)=={'ZERO','MAX'}
        zero,loaded=pair['ZERO'],pair['MAX']
        zd=D(zero['source_minus_module_main_mV'])
        ld=D(loaded['source_minus_module_main_mV'])
        delta=ld-zd
        # Each load's source reading is included, rather than assuming one fixed source.
        assert delta==1000*((D(loaded['V_source_main_V'])-D(loaded['V_module_main_V']))
                          -(D(zero['V_source_main_V'])-D(zero['V_module_main_V'])))
        label=f'+{delta:g}' if delta>0 else f'−{abs(delta):g}' if delta<0 else '0'
        # Main readings produce integer mV here; normalize trailing zeros in display only.
        label=('+' if delta>0 else '−' if delta<0 else '')+f'{abs(delta):.0f}'
        rows.append(dict(module_count=n,combo=combo,module_id=module,
            ZERO_source_main_V=zero['V_source_main_V'],ZERO_module_main_V=zero['V_module_main_V'],
            MAX_source_main_V=loaded['V_source_main_V'],MAX_module_main_V=loaded['V_module_main_V'],
            ZERO_drop_mV=str(zd),MAX_drop_mV=str(ld),MAX_minus_ZERO_drop_mV=str(delta),
            signed_display_mV=label,direction='increase' if delta>0 else 'decrease' if delta<0 else 'unchanged',
            includes_targeted_retest=any(b['selected_targeted_retest']=='True' for b in pair.values()),
            meaning='Difference between recorded load conditions for the same combination and module; not an added repeat or isolated causal load effect'))
    assert len(rows)==32
    write(data/'load_voltage_drop_changes.csv',rows)
    values=[D(r['MAX_minus_ZERO_drop_mV']) for r in rows]
    result=dict(paired_module_cells=len(rows),combination_count=len({r['combo'] for r in rows}),
        formula='(V_source_MAX - V_module_MAX) - (V_source_ZERO - V_module_ZERO), in mV',
        minimum_mV=str(min(values)),maximum_mV=str(max(values)),
        positive=sum(v>0 for v in values),negative=sum(v<0 for v in values),unchanged=sum(v==0 for v in values),
        source_sha256=digest(data/'branch_readings.csv'),output_sha256=digest(data/'load_voltage_drop_changes.csv'),script_sha256=digest(__file__))
    (data/'load_difference_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
