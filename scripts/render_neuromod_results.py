"""Render measured neuromodulation evidence; missing results are never fabricated."""
from pathlib import Path
import argparse
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def render(root):
    root=Path(root); build=root/'build'; output=build/'neuromod_figures'; output.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':150})
    artifacts=[]
    def save(fig,name):
        fig.tight_layout(); fig.savefig(output/name,bbox_inches='tight');plt.close(fig);artifacts.append(name)
    reference=build/'plasticity_reference_curve.csv'
    if reference.exists():
        data=pd.read_csv(reference)
        fig,ax=plt.subplots(figsize=(7.4,4.4))
        ax.plot(data.delay_ms,data.reference_delta_w,'o',mfc='none',mec='#8055ab',label='Supplied reference')
        ax.plot(data.delay_ms,data.production_float32_delta_w,'-',color='#16776d',label='Normalized production float32')
        ax.axhline(0,color='.7',lw=.8);ax.axvline(0,color='.7',lw=.8,ls='--')
        ax.set(xlabel='DA onset − odour onset (ms)',ylabel='Weight change (a.u.)',title='Isolated plasticity reference — software fixture')
        ax.legend(frameon=False);save(fig,'plasticity_reference.png')
    network=build/'neuromod_network_pairing_curve.csv'
    if network.exists():
        data=pd.read_csv(network);fig,ax=plt.subplots(figsize=(7.4,4.4))
        ax.plot(data.delay_ms,100*data.paired_mean_relative_delta,'o-',color='#8055ab')
        ax.axhline(0,color='.7',lw=.8);ax.axvline(0,color='.7',lw=.8,ls='--')
        ax.set(xlabel='DA onset − odour onset (ms)',ylabel='Mean relative weight change (%)',
               title='Actual network pairing: PPL101 / empirical g4')
        fig.text(.12,.005,'Published assignment g1 differs from empirical g4. No parameter fitting.',fontsize=8,color='.4')
        save(fig,'network_pairing.png')
    variant=build/'validation_hybrid_variant.json'
    if variant.exists():
        evidence=json.loads(variant.read_text());fig,ax=plt.subplots(figsize=(7.4,4.4))
        for case,color in zip(evidence.get('defaults',[]),['#16776d','#8055ab']):
            folder=build/'stability_variant'/case['label']
            files=[folder/'growth_coarse.npz']
            files=[p for p in files if p.exists()]
            if files:
                # Schema discovery below is constrained to actual saved arrays.
                with np.load(files[0]) as arrays:
                    times=next((arrays[k] for k in ('diagnostic_times_ms','times_ms','times') if k in arrays),None)
                    values=next((arrays[k] for k in ('max_abs_dvdt','max_abs_dvdt_mV_per_ms') if k in arrays),None)
                    if times is not None and values is not None:
                        ax.semilogy(times,np.maximum(values,1e-16),color=color,label=case['syn_model'])
        if ax.lines:
            ax.set(xlabel='Simulation time (ms)',ylabel='Maximum |dV/dt| (mV/ms)',title='Separate whole-brain perturbation recovery')
            ax.legend(frameon=False);save(fig,'wholebrain_stability.png')
        else: plt.close(fig)
    capacity=build/'validation_neuromod_capacity.json'
    if capacity.exists():
        evidence=json.loads(capacity.read_text())
        if evidence.get('capacity_curve'):
            data=pd.DataFrame(evidence['capacity_curve']);fig,ax=plt.subplots(figsize=(7.4,4.4))
            ax.plot(data.handles_used,data.mutual_information_bits,color='#16776d',label='Post-training task MI')
            ax.plot(data.handles_used,data.baseline_information_bits,'--',color='#8055ab',label='Pre-training MI')
            ax.set(xlabel='Number of measured handles (fixed inventory order)',ylabel='Mutual information (bits / observation)',
                   title='Measured two-odour / two-action task')
            ax.legend(frameon=False);ax.set_ylim(bottom=-.02)
            fig.text(.12,.005,'Inferred MBON readout. Saturation and physical interface bandwidth are not established.',fontsize=8,color='.4')
            save(fig,'capacity_curve.png')
        if evidence.get('per_handle'):
            data=pd.DataFrame(evidence['per_handle']);fig,ax=plt.subplots(figsize=(12,4.4))
            x=np.arange(len(data));values=data.mutual_information_bits.to_numpy()
            low=np.array([v[0] for v in data.bootstrap_ci95_bits]);high=np.array([v[1] for v in data.bootstrap_ci95_bits])
            # Percentile bootstrap intervals need not contain the point estimate.
            ax.vlines(x,low,high,color='#a4beb8',lw=1);ax.scatter(x,values,s=12,color='#16776d')
            ax.set_xticks(x,data.handle,rotation=90,fontsize=6)
            ax.set(ylabel='Task MI (bits / observation)',title='Per-handle MI and 95% protocol-bootstrap interval')
            save(fig,'capacity_per_handle.png')
    (output/'index.json').write_text(json.dumps({'measured_artifacts':artifacts},indent=2))
    print('\n'.join(str(output/name) for name in artifacts))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path.cwd())
    render(parser.parse_args().root)
