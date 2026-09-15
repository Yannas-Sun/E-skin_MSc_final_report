"""N=1–4 scatter preview; averaged heatmap retired at the user's request."""
from __future__ import annotations
import csv
import json
import statistics
from decimal import Decimal as D
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
from power_revision_figures import (ROOT, STYLE, PUBLICATION_STYLE, LOADS, MODULES, COLORS,
    MARKERS, DARK_CHARCOAL, canvas, panel_label, load_handles, legend, figure_47_drop_cmap, digest)
from power_m0_preview_heatmap_scale_20260907 import data_color_scale

PREVIEW=ROOT/'DATA/archive/m0_n1_n2_preview_20260907'
DATA=PREVIEW/'data'
OUT=PREVIEW/'figures'
COUNTS={1:1,2:3,3:3,4:1}

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def collect():
    branches=read(DATA/'branch_readings.csv')
    groups=[]
    for load in LOADS:
        for n in range(1,5):
            for m in MODULES:
                rows=sorted((b for b in branches if b['load']==load and int(b['module_count'])==n and b['module_id']==m),key=lambda b:b['combo'])
                assert len(rows)==COUNTS[n]
                values=[D(b['source_minus_module_main_mV']) for b in rows]
                for b,v in zip(rows,values):
                    assert v==1000*(D(b['V_source_main_V'])-D(b['V_module_main_V']))
                groups.append(dict(load=load,N=n,module_id=m,n_combinations=len(rows),
                    mean_mV=str(statistics.mean(values)),SD_mV=str(statistics.stdev(values)) if len(values)>1 else '',
                    min_mV=str(min(values)),max_mV=str(max(values)),
                    individual_values_mV=';'.join(str(v) for v in values),combos=';'.join(b['combo'] for b in rows),
                    includes_targeted_retest=any(b['selected_targeted_retest']=='True' for b in rows),
                    pending_voltage_assignment=any('PENDING' in b.get('preview_voltage_assignment_status','') for b in rows)))
    checks={(g['load'],g['N'],g['module_id']):g for g in groups}
    assert D(checks[('ZERO',2,'M0')]['mean_mV'])==D(29)
    assert D(checks[('ZERO',2,'M0')]['SD_mV'])==D(1)
    assert D(checks[('MAX',1,'M0')]['mean_mV'])==D(32)
    assert D(checks[('ZERO',1,'M0')]['mean_mV'])==D(28)
    assert not any(g['pending_voltage_assignment'] for g in groups)
    return branches,groups,checks

def export(fig,stem,description):
    fig.canvas.draw()
    files=[]
    for ext in ('png','svg'):
        p=OUT/f'{stem}.{ext}'
        fig.savefig(p,dpi=300,facecolor='white',bbox_inches=None)
        files.append(dict(name=p.name,sha256=digest(p)))
    plt.close(fig)
    return dict(stem=stem,description=description,files=files)

def heatmap(groups,checks):
    fig,axes=canvas(columns=2,height=123,top=.86,bottom=.33,left=.16,right=.97,wspace=.23)
    scale=data_color_scale(float(g['mean_mV']) for g in groups)
    for load,ax in zip(LOADS,axes.flat):
        matrix=np.array([[float(checks[(load,n,m)]['mean_mV']) for m in MODULES] for n in range(1,5)])
        mesh=ax.pcolormesh(np.arange(5)-.5,np.arange(5)-.5,matrix,vmin=scale['vmin'],vmax=scale['vmax'],
            cmap=figure_47_drop_cmap(),edgecolors='white',linewidth=.6)
        ax.set(xlim=(-.5,3.5),ylim=(3.5,-.5),xticks=range(4),xticklabels=MODULES,
            yticks=range(4),yticklabels=[f'N = {n} (n = {COUNTS[n]})' for n in range(1,5)])
        ax.tick_params(length=0,labelsize=8)
        ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(False)
        if load=='MAX':
            ax.set_yticklabels([])
        for y in range(4):
            for x,m in enumerate(MODULES):
                g=checks[(load,y+1,m)]
                suffix='*' if g['includes_targeted_retest'] else ''
                ax.text(x,y,f'{matrix[y,x]:.1f}{suffix}',ha='center',va='center',fontsize=9,color='#20252D')
        panel_label(ax,'(a) Zero load' if load=='ZERO' else '(b) Loaded (recorded)')
    cb=fig.colorbar(mesh,cax=fig.add_axes([.29,.245,.54,.023]),orientation='horizontal',ticks=scale['ticks'])
    cb.set_label('Mean source-to-module difference (mV)',fontsize=8)
    fig.text(.16,.15,'n = combinations containing each module; no additional full repeats.',fontsize=7.3)
    fig.text(.16,.112,'* Includes targeted retest(s); SOURCE readings retained.',fontsize=7.3)
    fig.text(.16,.074,'Color scale follows the data range; shared across both load panels.',fontsize=7.3)
    fig.text(.16,.030,'M0 retest preview | Not applied to report',fontsize=7.3,color=DARK_CHARCOAL)
    return export(fig,'module_drop_mean_by_N','Per-module arithmetic mean voltage difference by N; data-driven color scale shared by both load panels.')

def panel_points(ax,n,branches,checks):
    for load in LOADS:
        for i,m in enumerate(MODULES):
            x=i+(-.16 if load=='ZERO' else .16)
            rows=sorted((b for b in branches if b['load']==load and int(b['module_count'])==n and b['module_id']==m),key=lambda b:b['combo'])
            yy=[float(b['source_minus_module_main_mV']) for b in rows]
            jitter=np.linspace(-.075,.075,len(rows)) if len(rows)>1 else [0]
            for b,y,j in zip(rows,yy,jitter):
                ax.scatter(x+j,y,s=25,marker=MARKERS[load],facecolors=COLORS[load],
                    edgecolors=DARK_CHARCOAL,linewidth=.65,zorder=4)
            g=checks[(load,n,m)]
            mean=float(g['mean_mV'])
            kw=dict(mfc='none',mec=DARK_CHARCOAL,ms=6.3,mew=.9,zorder=5)
            if g['SD_mV']:
                ax.errorbar(x,mean,yerr=float(g['SD_mV']),fmt='D',ecolor=DARK_CHARCOAL,
                    elinewidth=.8,capsize=3,**kw)
            else:
                ax.plot(x,mean,'D',**kw)
            if g['includes_targeted_retest']:
                ax.annotate('*',(x,mean),xytext=(5,7),textcoords='offset points',ha='left',fontsize=9)
    ax.set(xlim=(-.5,3.6),ylim=(0,56),xticks=range(4),xticklabels=MODULES,
        yticks=[0,10,20,30,40,50],xlabel='Module ID',ylabel='Voltage difference (mV)')
    ax.tick_params(labelsize=8)
    panel_label(ax,f'N = {n}  |  n = {COUNTS[n]} per module')

def four(branches,checks):
    fig,axes=canvas(rows=2,columns=2,height=181,top=.85,bottom=.19,left=.105,right=.965,wspace=.40,hspace=.52)
    for n,ax in enumerate(axes.flat,1):
        panel_points(ax,n,branches,checks)
    handles=load_handles()+[Line2D([],[],color=DARK_CHARCOAL,ls='none',marker='D',mfc='none',ms=6,label='Mean ± combination SD')]
    legend(fig,handles,y=.985)
    notes=[('Points = combinations; diamonds = means. SD at N=2,3 is not repeat SD.',.115),
           ('* Includes targeted retest(s); SOURCE readings retained.',.088),
           ('All voltage assignments confirmed; no added measurement from that confirmation.',.061),
           ('M0 retest preview | Not applied to report',.028)]
    for text,y in notes:
        fig.text(.105,y,text,fontsize=7.4,color=DARK_CHARCOAL)
    return export(fig,'module_drop_N1_N4','Individual combination values, means and combination SD for each module, N=1–4.')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    branches,groups,checks=collect()
    with (DATA/'module_drop_by_N_summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(groups[0])); w.writeheader(); w.writerows(groups)
    with plt.style.context(STYLE),matplotlib.rc_context(PUBLICATION_STYLE):
        matplotlib.rcParams.update({'svg.fonttype':'none','svg.hashsalt':'power-latest-M0-preview-20260907',
            'font.size':8.5,'axes.labelsize':8.5,'xtick.labelsize':8,'ytick.labelsize':8,'legend.fontsize':7.5})
        outputs=[four(branches,checks)]
    manifest=dict(figures=outputs,source_hashes={p.name:digest(p) for p in DATA.glob('*.csv')},
        script_sha256=digest(__file__),groups=32,branches=64,
        group_counts_by_N=[1,3,3,1],spread='Sample SD across combinations only; no additional full repeats',
        confirmed='N1 M0 ZERO voltage3.252V/drop28mV and M0-M1 ZERO3.251V user confirmed',
        retired_figure='module_drop_mean_by_N: removed from active preview; original exported files archived',
        scale_helper_sha256=digest(Path(__file__).with_name('power_m0_preview_heatmap_scale_20260907.py')))
    (PREVIEW/'drop_figure_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'figures':len(outputs),'output':str(OUT)},indent=2))

if __name__=='__main__':
    main()
