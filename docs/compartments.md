# Compartment construction and evidence

The compartment stage constructs a reproducible **coarse model membership map**. Passing `V-NM-COMP` means that the source gate, construction checks, required endpoint ROIs, exact plastic-edge census, and saved evidence are valid. It does **not** mean that KC-partner clustering recovered the 15 anatomical mushroom-body compartments. The measured disagreement is retained as a result.

## Empirical mushroom-body clusters

`build_compartments(root)` first requires the source census gate to pass. It uses the released `Connectivity_783.parquet` and the exact row order of `build/neurons.parquet`. Rows in the base connectivity are postsynaptic and columns are presynaptic; the parquet's explicitly named pre/post index columns determine partner direction here.

For each of the 30 DAN and 35 MBON types, the implementation builds one binary vector over all 5,177 KCs. A KC is a DAN partner when a released **DAN → KC** edge has at least one synapse, or an MBON partner when a released **KC → MBON** edge has at least one synapse. Partners are unioned across cells of a type and both hemispheres. Reverse-direction edges are not included. These choices are assumptions of the requested coarse clustering procedure, not a reconstruction of synaptic coordinates.

Types are sorted lexicographically. Nonempty vectors are clustered jointly using Jaccard distance, average linkage, and SciPy `cut_tree` with an exact count of 15. Empty vectors remain present in the audit and receive assignment `-1`; they do not acquire a biological location by clustering identical empty sets. Software versions and all relevant hashes are saved.

The reference table is used **only after** the empirical clusters are fixed. An optimal one-to-one Hungarian label alignment maximizes fractional type votes: a published single-compartment type contributes one vote; a type spanning `k` compartments contributes `1/k` to each. Ambiguous labels, unknown types, and the calyx MBON do not vote. Changing the reference can rename a cluster but cannot change its membership or linkage tree. An aligned label with zero supporting votes is marked `canonical_identity_supported=false`; it is an arbitrary remaining label, not anatomical evidence.

KCs can belong to several model compartments because they share partners from several clusters. DANs and MBONs with nonempty vectors receive one empirical cluster. The separate `mb_assignment` array is defined for these DANs/MBONs and is `-1` for KCs and other cells. Every released KC → MBON plastic edge is assigned according to its postsynaptic MBON's empirical cluster. This preserves 62,261 edge identities and 256,719 synapses without generating edges, moving edges to fit anatomy, or conflating counts with edge weights.

### Independent anatomical reference

`config/mb_compartment_reference.csv` has one row for every exact FlyWire DAN/MBON label, including explicit unknowns. The reference was transcribed from the primary figures in [Li et al., DOI:10.7554/eLife.62576](https://pmc.ncbi.nlm.nih.gov/articles/PMC7909955/): [DAN Figure 6](https://pmc.ncbi.nlm.nih.gov/articles/PMC7909955/#fig6), [compartment Figure 6 supplement 1](https://pmc.ncbi.nlm.nih.gov/articles/PMC7909955/#fig6s1), [typical MBON Figure 7](https://pmc.ncbi.nlm.nih.gov/articles/PMC7909955/#fig7), and [atypical MBON Figure 8](https://pmc.ncbi.nlm.nih.gov/articles/PMC7909955/#fig8). Correspondence between identically named hemibrain and FlyWire types remains a cross-dataset assumption.

The reference preserves direction and scope:

- DAN labels describe presynaptic MB territory; PAM07's gamma1/gamma2 dendritic territories are not extra release compartments.
- MBON labels describe MB input territory; output territory following `>` is excluded. `MBON15-like` and `MBON17-like` use the separately published multi-compartment territories rather than inheriting the numbered type's map.
- `MBON22` is a calyx MBON, explicitly outside the 15 lobe compartments. Its empirical assignment does not turn its calyx inputs into an anatomical lobe claim.
- `MBON25,MBON34` is an ambiguous annotation. Its candidate union is recorded, with no claim that every cell occupies both territories and no vote in label alignment.
- PAL01–03, PPL107–108, and PPL201–204 remain anatomically unmapped by the inspected primary MB reference. A broad DAN category does not establish MB innervation.

Exact matches, disagreements, multi-compartment containment/disagreement, ambiguous references, unmapped references, outside-15 references, unsupported alignments, and empty vectors are separate comparison categories. Multi-compartment containment is not an exact anatomical match.

### Observed result on release 783

The initial verified build produced 61 nonempty type vectors and 15 clusters. PAL01, PAL02, PAL03, and PPL108 had no eligible KC partners and remained unassigned. The comparison contained 14 single-compartment matches, 23 disagreements, 5 multi-compartment containments, 11 multi-compartment disagreements, 5 unmapped references, 4 empty vectors, 1 outside-15 reference, 1 ambiguous reference, and 1 published type with an unsupported cluster label. Seven assigned canonical cluster labels had zero support: `g3`, `bp1`, `a1`, `a3`, `ap1`, `ap2`, and `ap3`.

In particular, PPL101 joins the empirical cluster aligned to `g4`, although the independent published reference places it in `g1`. No override moves it to `g1`. An experiment called “gamma1/PPL101” therefore needs to state which empirical or published interpretation it uses. The original gamma1 learning example is not automatically anatomically satisfied by this map.

These differences are scientifically plausible limitations of the procedure: binary KC identity discards position along a KC axon, and a single KC can traverse multiple anatomical compartments. Consequently, neurons operating at different longitudinal positions may share many of the same KCs. Anatomical recovery would need additional synapse-position evidence and a separately reviewed procedure, rather than relabeling these results to pass.

## Antennal lobe

Named olfactory ORN and ALPN types supply glomerular names. For ORNs the `ORN_` suffix is parsed; for ALPNs the prefix before `_` is parsed, including explicit comma alternatives and `+` combinations. Names are pooled across hemispheres. The documented naming conventions distinguish `M`/`MZ` multiglomerular labels and `Z` subesophageal territory from named glomeruli; a trailing `+` indicates additional unspecified territory. These labels do not generate invented glomerular memberships. [Scheffer et al., DOI:10.7554/eLife.57443](https://elifesciences.org/articles/57443/figures)

VM6l, VM6m, and VM6v retain their neuron type identity but share the VM6 model volume, following their description as subglomeruli of VM6. [Schlegel et al., DOI:10.7554/eLife.66018](https://elifesciences.org/articles/66018), [Task et al., DOI:10.7554/eLife.72599](https://pmc.ncbi.nlm.nih.gov/articles/PMC9020824/)

The released labels produce 58 named glomerular volumes. Of 2,964 ORN/ALPN cells, 2,601 have at least one parsed named territory and 363 have unresolved names. The separate `AL_unresolved` volume includes remaining cells with measured AL endpoints or an AL class, including local neurons whose glomerular distribution cannot be recovered from their names. No all-to-all AL mixing is assumed. `al_glomerulus_membership.csv` records each ORN/ALPN decision and additional unspecified territory.

## Central complex, optic lobes, and hemolymph

The existing `visual_neuropils` pipeline supplies actual pre/post synaptic endpoint ROI memberships, bound to source files and hashes. A positive endpoint weight yields coarse membership. These data locate synaptic endpoints; they do **not** directly measure release sites for a modulator or receptor expression.

- `CX_EB`, `CX_PB`, and `CX_NO` use their actual endpoint ROIs. `CX_FB1` through `CX_FB9` require an explicit named tangential FB layer and an actual FB endpoint. Other FB arbors remain in `CX_FB_unresolved`; no layer is inferred from a columnar neuron prefix. [Hulse et al., DOI:10.7554/eLife.66039](https://pmc.ncbi.nlm.nih.gov/articles/PMC9477501/)
- `LA`, `ME`, `LO`, and `LOP` are separate coarse volumes per side. Membership comes from actual endpoint ROIs, including bilateral membership where observed. Soma side is not used as a substitute.
- `hemolymph` is a symbolic global pool. Its membership identifies the endocrine source interface; later layers must define receptor targets and state effects explicitly.

The initial build had 96 total volumes and 25,969 neurons with no membership in these selected volumes. Their root IDs are saved, so downstream code can distinguish unassigned neurons from negative evidence. The map is not claimed to cover every brain neuropil.

## Assumed adjacency

Adjacency is dimensionless, symmetric, nonnegative, and has a zero diagonal. Consecutive MB slices within each named lobe and consecutive FB layers are neighbors. Each optic side has LA–ME, ME–LO, and ME–LOP neighbors. AL volumes, unresolved volumes, and hemolymph have no assumed neighbors. These are explicit spatial modeling assumptions, not measured diffusion constants or a transformation of connectome edges. In particular, spatial diffusion using canonical MB names inherits the empirical alignment limitations above.

## API, artifacts, and validation

```python
from flybrain.neuromod.compartments import build_compartments, load_compartments

validation = build_compartments(root)  # writes V-NM-COMP evidence
mapping = load_compartments(root)     # verifies source/artifact/config/code hashes
# mapping.names: tuple[str, ...]
# mapping.membership: bool[n_compartments, n_model_neurons]
# mapping.adjacency: float32[n_compartments, n_compartments]
# mapping.mb_assignment: int16[n_model_neurons], -1 where not assigned
# mapping.model_root_ids: int64[n_model_neurons], exact base model order
# mapping.metadata: assumptions, source links, coverage, comparisons and warnings
```

The build writes `compartments.npz`, `compartments_metadata.json`, `mb_compartments.csv`, `mb_compartment_comparison.csv`, `al_glomerulus_membership.csv`, and `validation_neuromod_compartments.json`. The archive also contains raw type clusters, aligned assignments, KC partner vectors, Jaccard distances, the linkage tree, and exact plastic pre/post/count/compartment arrays. It contains primitive arrays and loads with `allow_pickle=False`.

The stage fails closed when its source prerequisite fails, a required ROI is missing, construction/census checks fail, or an input changes during construction. Load verification rejects changed source evidence, config, implementation, endpoint cache or sources, and compartment artifacts, even if an old JSON status still reads `PASS`. Rebuild the source stage before compartments when the shared neuromod config changes. The report's `V-NM-COMP` status is a reproducibility and software gate; anatomical disagreement remains visible and cannot be converted into a validation pass by a threshold or fitted reassignment.
