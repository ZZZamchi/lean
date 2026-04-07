#!/bin/bash
cd /home/ningmiao/Zam/lean
export CUDA_VISIBLE_DEVICES=0,1

python3 -c "
import sys, os, json, time
from pathlib import Path
sys.path.insert(0, '.')

from prover.config import ModelConfig, VerifierConfig
from prover.datasets import load_dataset
from prover.model import ProverModel
from prover.strategies.base import ProofStrategy
from prover.verifier import LeanVerifier

GOEDEL_PROMPT = '''Complete the following Lean 4 code:

\`\`\`lean4
{formal_statement}\`\`\`

Before producing the Lean 4 code to formally prove the given theorem, provide a detailed proof plan outlining the main proof steps and strategies.
The plan should highlight key ideas, intermediate lemmas, and proof structures that will guide the construction of the final formal proof.'''

SC_PROMPT = '''The following Lean 4 proof attempt failed:

\`\`\`lean4
{failed_code}
\`\`\`

Errors:
\`\`\`
{errors}
\`\`\`

Fix the proof. Analyze what went wrong then provide a complete corrected proof for:

\`\`\`lean4
{formal_statement}\`\`\`'''

def asm(hdr, ext, sf):
    if 'theorem' in ext and ':= by' in ext: return sf(ext)
    if ext.strip().startswith('by'): return f'{hdr.rstrip()}\n{ext}'
    return f'{hdr}\n  {ext}'

out = Path('results/experiments/phase1_official_16k')
mcfg = ModelConfig(model_path='Goedel-LM/Goedel-Prover-V2-8B', tensor_parallel_size=2, max_model_len=24576, max_tokens=16384, temperature=1.0, top_p=0.95, gpu_memory_utilization=0.92, use_chat_template=True)
model = ProverModel(mcfg, cuda_devices='0,1'); model.load()
ver = LeanVerifier(VerifierConfig(mathlib_path='mathlib4')); ver.start()
probs = load_dataset('minif2f_unsolved39')
res = []; sc = 0; BS = 8; N = 32

try:
    for i, p in enumerate(probs):
        t0 = time.time()
        print(f'\n[{i+1}/{len(probs)}] {p.problem_id}')
        hdr = ProofStrategy.strip_imports(p.theorem_header)
        pr = GOEDEL_PROMPT.format(formal_statement=p.lean4_code)
        a = {'problem_id': p.problem_id, 'complete': False, 'attempts': 0, 'strategy': 'phase1_16k', 'code': '', 'sc': 0}
        bec = None; bem = None
        for bs in range(0, N, BS):
            bn = min(BS, N - bs)
            outs = model.generate_single(pr, n=bn, temperature=1.0, max_tokens=16384, chat=True)
            for r in outs:
                ex = model.extract_lean_code(r)
                if not ex: continue
                c = asm(hdr, ex, ProofStrategy.strip_imports)
                a['attempts'] += 1
                v = ver.verify(c)
                if v.complete: a['complete'] = True; a['code'] = c; break
                if v.success and not v.complete and bec is None: bec = c; bem = '; '.join(s.get('goal','')[:80] for s in v.sorries[:3])
                elif v.errors and bec is None: bec = c; bem = '; '.join(e.get('data','')[:80] for e in v.errors[:3])
            if a['complete']: break
        if not a['complete'] and bec:
            for sr in range(1, 3):
                print(f'  SC round {sr}...')
                sp = SC_PROMPT.format(failed_code=bec, errors=bem or '?', formal_statement=p.lean4_code)
                so = model.generate_single(sp, n=8, temperature=0.8, max_tokens=16384, chat=True)
                for r in so:
                    ex = model.extract_lean_code(r)
                    if not ex: continue
                    c = asm(hdr, ex, ProofStrategy.strip_imports)
                    a['attempts'] += 1
                    v = ver.verify(c)
                    if v.complete: a['complete'] = True; a['code'] = c; a['sc'] = sr; break
                    if v.errors: bec = c; bem = '; '.join(e.get('data','')[:80] for e in v.errors[:3])
                if a['complete']: break
        el = time.time() - t0; a['elapsed'] = round(el, 1)
        if a['complete']:
            sc += 1; si = f' (SC r{a[\"sc\"]})' if a['sc'] else ''
            print(f'  [SOLVED] {el:.1f}s {a[\"attempts\"]} att{si}')
        else: print(f'  [FAIL] {el:.1f}s {a[\"attempts\"]} att')
        res.append(a)
        with open(out / 'proof_results.json', 'w') as f: json.dump(res, f, indent=2)
finally: ver.stop()
print(f'\nPhase1-16K: {sc}/{len(probs)} solved')
nt = 205 + sc; print(f'{nt}/244 = {100*nt/244:.1f}%')
" 2>&1
