import zipfile, json
z = zipfile.ZipFile(r'..\pcb-full-routing-20261006\AI_figure_routed_DRC0_checkpoint_20261007.epro2')
L = z.read('AI_figure.epru').decode('utf-8', 'replace').splitlines()
metas = [i for i, l in enumerate(L) if l.startswith('{"type":"META"')]
for i, l in enumerate(L):
    if ('"layerId":12' in l and ('"FILL"' in l or '"POLY"' in l or '"REGION"' in l)) or ('"id":"e75"' in l[:60]):
        blk = max(m for m in metas if m <= i)
        print(i, L[blk][60:140], '|', l[:500])
