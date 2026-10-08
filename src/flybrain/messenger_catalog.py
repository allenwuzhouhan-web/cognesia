"""Evidence catalogue for chemical tags, independent of simulation dynamics.

Catalogue membership never enables a field, assigns a neuron, changes a synapse
sign, or supplies kinetics. Literature on a cell class is not evidence that a
particular connectome entity expresses that ligand or its receptor.
"""
from __future__ import annotations

import copy
import re
from urllib.parse import urlsplit

CATALOG_VERSION = "2026-10-07.1"
FIELD_IDS = ("DA", "OA", "5HT", "NO", "sNPF", "peptide_pool", "TA", "ACh")
ENDOCRINE_IDS = ("insulin", "corazonin", "dh44", "itp", "dh31", "myosuppressin", "capa", "hugin")


def _paper(title, url, *, doi=None, stage="adult", tissue, finding):
    return {"title": title, "url": url, "doi": doi, "organism": "Drosophila melanogaster",
            "stage": stage, "tissue_or_circuit": tissue, "finding": finding,
            "evidence_kind": "primary_research"}


_SNPF = _paper(
    "Presynaptic facilitation by neuropeptide signaling mediates odor-driven food search",
    "https://pubmed.ncbi.nlm.nih.gov/21458672/", doi="10.1016/j.cell.2011.02.008",
    tissue="Or42b olfactory receptor neurons",
    finding="sNPF/sNPFR1 participates in starvation-dependent presynaptic facilitation; insulin regulates receptor expression.")
_ASTA = _paper(
    "Allatostatin A Signalling in Drosophila Regulates Feeding and Sleep and Is Modulated by PDF",
    "https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1006346",
    doi="10.1371/journal.pgen.1006346", tissue="PLP neurons and midgut enteroendocrine cells",
    finding="AstA cell activation reduces feeding and promotes sleep; PLP neurons have functional PDF receptors.")
_ITP = _paper(
    "Anti-diuretic hormone ITP signals via a guanylate cyclase receptor to modulate systemic homeostasis in Drosophila",
    "https://elifesciences.org/articles/97043", doi="10.7554/eLife.97043",
    tissue="ITP neurosecretory system and peripheral tissues including fat body",
    finding="Amidated ITP activates Gyc76C in a heterologous assay; in-vivo perturbations support a systemic signaling role.")


def _entry(identity, name, aliases, status, *, receptors=(), evidence=(), note=""):
    return {"id": identity, "name": name, "aliases": list(aliases),
            "implementation_status": status, "taggable": identity != "peptide_pool",
            "field_control_id": identity if status == "normalized_field" else None,
            "endocrine_proxy_id": identity if status == "endocrine_proxy" else None,
            "receptors_reported_in_literature": list(receptors),
            "receptor_assignment": "NOT_ASSIGNED_BY_CATALOG",
            "kinetic_parameters": None, "kinetics_provenance": "NOT_SUPPLIED",
            "automatic_neuron_assignment": False, "biologically_validated": False,
            "evidence": list(evidence), "limitations": note}


# Runtime support is a software inventory, not a claim of measured kinetics.
_ENTRIES = [
    _entry("DA", "Dopamine", ("dopamine",), "normalized_field",
           receptors=("Dop1R1", "Dop1R2", "Dop2R"),
           note="Existing receptor-table expressions and strengths are assumptions; plasticity scope is provider-dependent."),
    _entry("OA", "Octopamine", ("octopamine",), "normalized_field", receptors=("OAMB",),
           note="Existing OAMB/PAM and visual gain rows have separate provenance. A specific HS/VS receptor is not identified by this model."),
    _entry("5HT", "Serotonin", ("serotonin", "5-HT"), "normalized_field", receptors=("5-HT7",),
           note="The configured ALLN receptor row does not represent every serotonergic target."),
    _entry("NO", "Nitric oxide", ("nitric oxide",), "normalized_field",
           note="A modeled concentration field exists; no dedicated NO receptor-effect row is currently enabled."),
    _entry("sNPF", "Short neuropeptide F", ("short neuropeptide f",), "normalized_field",
           receptors=("sNPFR1",), evidence=(_SNPF,),
           note="The literature finding in ORNs does not validate the existing assumed adult KC-to-MBON release coupling. NPF is a different ligand."),
    _entry("peptide_pool", "Unresolved peptide pool", (), "normalized_field",
           note="Aggregate positive peptide-annotated endocrine drive; not a real molecule, specific peptide concentration, or universal receptor."),
    _entry("TA", "Tyramine", ("tyramine",), "normalized_field",
           note="Tyramine has a field and is an enzyme precursor; no dedicated tyramine receptor-effect row is currently enabled."),
    _entry("ACh", "Acetylcholine", ("acetylcholine",), "normalized_field", receptors=("mAChR-A",),
           note="The slow muscarinic field is separate from fast synaptic transmission. Optional ChAT/AChE kinetics use arbitrary units."),
    _entry("insulin", "DILP2/3/5 lumped insulin proxy", ("dilp2", "dilp3", "dilp5"), "endocrine_proxy",
           receptors=("InR",), evidence=(_SNPF,),
           note="Existing EndocrineState lumps these peptides. A DILP2 tag does not establish DILP3/5 expression. The provider adapter does not implement this full endocrine system."),
    _entry("corazonin", "Corazonin", ("crz",), "endocrine_proxy",
           note="Named normalized secretion/state proxy; receptor-resolved kinetics are absent."),
    _entry("dh44", "Diuretic hormone 44", ("diuretic hormone 44",), "endocrine_proxy",
           receptors=("Dh44-R1", "Dh44-R2"), evidence=(
               _paper("Nutrient Sensor in the Brain Directs the Action of the Brain-Gut Axis in Drosophila",
                      "https://pmc.ncbi.nlm.nih.gov/articles/PMC4697866/", doi="10.1016/j.neuron.2015.05.032",
                      tissue="Pars intercerebralis DH44 cells, receptor-expressing brain/VNC and gut cells",
                      finding="DH44 signaling participates in selection and consumption of nutritive sugars."),),
           note="The current generic stress driver is a model assumption, not a measured sugar-sensing mechanism."),
    _entry("itp", "Ion transport peptide", ("ion transport peptide",), "endocrine_proxy",
           receptors=("Gyc76C",), evidence=(_ITP,),
           note="The Gyc76C finding concerns amidated ITP. Do not collapse all splice products or import assay concentrations as brain kinetics."),
    _entry("dh31", "Diuretic hormone 31", ("diuretic hormone 31",), "endocrine_proxy",
           receptors=("Dh31-R", "PDFR (context-dependent cross-activation)"), evidence=(
               _paper("Drosophila DH31 Neuropeptide and PDF Receptor Regulate Night-Onset Temperature Preference",
                      "https://pmc.ncbi.nlm.nih.gov/articles/PMC5125228/",
                      tissue="Circadian clock neurons", finding="DH31/PDFR signaling contributes to night-onset temperature preference."),),
           note="Endocrine arousal drive does not implement a circadian clock or a receptor-specific temperature circuit."),
    _entry("myosuppressin", "Myosuppressin", ("ms", "myosupressin"), "endocrine_proxy",
           note="Normalized state proxy only; muscle and heart dose-response data are not neural kinetic parameters."),
    _entry("capa", "CAPA / capability", ("capability",), "endocrine_proxy",
           note="Precursor can yield different peptides. Current thirst proxy does not resolve processing or peripheral receptor distribution."),
    _entry("hugin", "Hugin", ("hug",), "endocrine_proxy",
           note="Named source/state proxy; no new pyrokinin receptor mapping or larval-to-adult transfer is supplied."),
    _entry("NPF", "Neuropeptide F", ("neuropeptide f",), "candidate_tag_only", receptors=("NPFR",), evidence=(
        _paper("A neural circuit mechanism integrating motivational state with memory expression in Drosophila",
               "https://pmc.ncbi.nlm.nih.gov/articles/PMC2780032/", doi="10.1016/j.cell.2009.08.035",
               tissue="Adult brain appetitive-memory circuitry",
               finding="NPF signaling connects motivational state with appetitive memory expression."),),
        note="Not sNPF; no receptor expression or effect is assigned to the current model by this evidence."),
    _entry("PDF", "Pigment-dispersing factor", ("pigment-dispersing factor", "pigment dispersing factor"),
           "candidate_tag_only", receptors=("PDFR",), evidence=(_ASTA,),
           note="A scalar circadian_phase variable is not a reconstructed PDF clock network."),
    _entry("AstA", "Allatostatin A", ("allatostatin a",), "candidate_tag_only",
           receptors=("AstA-R1 / DAR-1", "AstA-R2 / DAR-2"), evidence=(_ASTA,
               _paper("The Neuropeptide Allatostatin A Regulates Metabolism and Feeding Decisions in Drosophila",
                      "https://pmc.ncbi.nlm.nih.gov/articles/PMC4485031/", doi="10.1038/srep11680",
                      stage="adult and larval expression assays", tissue="Insulin- and AKH-producing cells",
                      finding="DAR-2 expression and perturbations link AstA with insulin/AKH signaling and feeding decisions.")),
           note="Do not infer a juvenile-hormone inhibitory effect in Drosophila from the allatostatin name or another insect species."),
    _entry("AstC", "Allatostatin C", ("allatostatin c",), "candidate_tag_only",
           receptors=("AstC-R1", "AstC-R2"), evidence=(
               _paper("Allatostatin-C/AstC-R2 Is a Novel Pathway to Modulate the Circadian Activity Pattern in Drosophila",
                      "https://pubmed.ncbi.nlm.nih.gov/30554904/", tissue="Dorsal clock neurons and LNd",
                      finding="AstC/AstC-R2 signaling contributes to photoperiod-dependent evening activity; AstC inhibits one LNd ex vivo."),
               _paper("The neuropeptide allatostatin C from clock-associated DN1p neurons generates the circadian rhythm for oogenesis",
                      "https://pmc.ncbi.nlm.nih.gov/articles/PMC7848730/", tissue="DN1p and insulin-producing cells",
                      finding="IPCs express AstC receptors; perturbations link clock-associated AstC to oogenesis.")),
           note="Keep AstC distinct from AstA and AstCC; sex and reproductive condition constrain the evidence."),
    _entry("MIP", "Myoinhibitory peptide / Allatostatin B", ("mip", "myoinhibitory peptide", "myoinhibiting peptide", "allatostatin b", "astb"),
           "candidate_tag_only", receptors=("SPR",), evidence=(
               _paper("A homeostatic sleep-stabilizing pathway in Drosophila composed of the sex peptide receptor and its ligand, the myoinhibitory peptide",
                      "https://pubmed.ncbi.nlm.nih.gov/25333796/", tissue="PDF arousal neurons",
                      finding="Central MIP/SPR signaling stabilizes sleep and contributes to sleep recovery."),),
           note="MIP and sex peptide share a receptor but differ in ligand source and physiological context."),
    _entry("LK", "Leucokinin", ("leucokinin", "lk"), "candidate_tag_only", receptors=("Lkr",), evidence=(
        _paper("A single pair of leucokinin neurons are modulated by feeding state and regulate sleep-metabolism interactions",
               "https://pubmed.ncbi.nlm.nih.gov/30759083/", doi="10.1371/journal.pbio.2006409",
               tissue="Lateral-horn leucokinin neurons and insulin-producing cells",
               finding="LHLK activity and IPC leucokinin receptors contribute to starvation-dependent sleep regulation."),),
        note="Some existing source annotations can enter peptide_pool; that is not LK-specific dynamics or receptor coverage."),
    _entry("TK", "Tachykinin", ("tachykinin", "tk"), "candidate_tag_only",
           receptors=("TkR86C", "TkR99D"), evidence=(
               _paper("Tachykinin-expressing neurons control male-specific aggressive arousal in Drosophila",
                      "https://pmc.ncbi.nlm.nih.gov/articles/PMC3978814/", doi="10.1016/j.cell.2013.11.045",
                      tissue="Male sexually dimorphic brain neurons",
                      finding="Tachykinin-expressing neurons and peptide/receptor manipulations regulate male aggressive arousal."),),
           note="Male aggression findings cannot be assigned directly to the adult female BANC/FlyWire model. Pooled peptide coverage is not a dedicated TK field."),
    _entry("SIFa", "SIFamide", ("sifamide", "sifa"), "candidate_tag_only", receptors=("SIFaR",), evidence=(
        _paper("SIFamide Translates Hunger Signals into Appetitive and Feeding Behavior in Drosophila",
               "https://www.sciencedirect.com/science/article/pii/S2211124717308574", doi="10.1016/j.celrep.2017.06.043",
               tissue="Four brain SIFamide neurons and feeding/sensory circuitry",
               finding="SIFamide neurons integrate nutritional signals and influence appetitive behavior and food intake."),),
        note="A behavioral effect does not provide a uniform neuronal gain or a receptor map."),
    _entry("CCHa2", "CCHamide-2", ("cchamide-2", "cchamide 2", "ccha2"), "candidate_tag_only",
           receptors=("CCHa2-R",), evidence=(
               _paper("The Nutrient-Responsive Hormone CCHamide-2 Controls Growth by Regulating Insulin-like Peptides in the Brain of Drosophila melanogaster",
                      "https://pmc.ncbi.nlm.nih.gov/articles/PMC4447355/", stage="larval",
                      tissue="Gut/fat body to brain insulin-producing cells",
                      finding="Peripheral CCHa2/CCHa2-R signaling regulates Dilps and nutrient-dependent growth."),),
           note="Larval growth evidence requires independent adult validation and a peripheral boundary model."),
    _entry("DSK", "Drosulfakinin", ("drosulfakinin", "dsk"), "candidate_tag_only",
           receptors=("CCKLR-17D1", "CCKLR-17D3"), evidence=(
               _paper("Cholecystokinin-like peptide mediates satiety by inhibiting sugar attraction",
                      "https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1009724",
                      doi="10.1371/journal.pgen.1009724", tissue="Feeding and sugar-sensing circuitry; study also includes a planthopper",
                      finding="The Drosophila experiments connect sulfakinin signaling with reduced sugar attraction."),),
           note="Keep species-specific results separate. Peptide processing/sulfation and receptor-specific effects remain unparameterized."),
]

_INDEX = {entry["id"]: entry for entry in _ENTRIES}
_ALIASES = {alias.casefold(): entry["id"] for entry in _ENTRIES
            for alias in (entry["id"], entry["name"], *entry["aliases"])}


def messenger_details(identity: str) -> dict:
    """Return a detached JSON-ready entry; reject fuzzy/substring matches."""
    if not isinstance(identity, str) or identity.strip().casefold() not in _ALIASES:
        raise ValueError("Unknown messenger identifier")
    return copy.deepcopy(_INDEX[_ALIASES[identity.strip().casefold()]])


def catalog_payload() -> dict:
    """Return machine-readable capabilities and evidence without runtime mutation."""
    return {"schema_version": 1, "catalog_version": CATALOG_VERSION,
            "reviewed_on": "2026-10-07", "species": "Drosophila melanogaster",
            "messengers": copy.deepcopy(_ENTRIES),
            "field_control_ids": list(FIELD_IDS), "endocrine_proxy_ids": list(ENDOCRINE_IDS),
            "status_definitions": {
                "normalized_field": "Existing optional a.u. field; biological kinetics and validation are not established.",
                "endocrine_proxy": "Existing original-core/wholebrain EndocrineState proxy; not a general provider capability or receptor-resolved field.",
                "candidate_tag_only": "Literature-backed candidate annotation; no dedicated simulation field or effect is implemented."},
            "model_sources": ["src/flybrain/neuromod/field.py", "src/flybrain/neuromod/state.py",
                              "config/receptors.csv", "config/endocrine_sources.csv"],
            "curated_annotation_resource": {
                "url": "https://github.com/flyconnectome/drosophila_neuropeptides",
                "table": "gt_np_data.csv", "imported": False,
                "requirements": "Pin commit and checksum; retain study, species, stage, sex, confidence, positive/negative evidence and specimen-specific mapping. Review source articles before assigning cells."},
            "validation": {"biologically_validated": False,
                           "status": "EXPERIMENTAL_UNVALIDATED", "report": "REPORT.md",
                           "note": "Catalogue is an annotation aid; inspect current model-specific validation artifacts before interpreting a run."},
            "promotion_requirements": [
                "Versioned positive expression evidence for identified source cells in the modeled specimen or explicit inferred cross-specimen mapping.",
                "Target receptor expression, ligand processing, compartment localization and source-release definition.",
                "Unit-consistent kinetics; declare absent values as assumptions with sensitivity sweeps, never measured defaults.",
                "Disabled-path parity, stationarity, timestep convergence, null/intervention controls and held-out physiological validation."]}


def source_annotation_tags(known_nt: str | None, *, evidence_url: str | None = None,
                           dataset: str | None = None, neuron_id: str | None = None) -> dict:
    """Parse exact declared annotation tokens without enabling a chemical source.

    Caller-supplied evidence is *not* verified by this function. Negative and
    unknown tokens remain visible. Explicit positive and negative reports for
    the same ligand are retained as a conflict, never silently reconciled.
    """
    if known_nt is not None and (not isinstance(known_nt, str) or len(known_nt) > 16_384):
        raise ValueError("known_nt must be a string of at most 16384 characters or null")
    for name, value in (("dataset", dataset), ("neuron_id", neuron_id)):
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 512):
            raise ValueError(f"{name} must be a nonempty string of at most 512 characters")
    if evidence_url is not None:
        if not isinstance(evidence_url, str) or len(evidence_url) > 2048:
            raise ValueError("evidence_url must be an HTTP(S) URL of at most 2048 characters")
        parsed = urlsplit(evidence_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("evidence_url must be an HTTP(S) URL without credentials")
    positives, negatives, unknown = {}, [], []
    negative_ids = set()
    for fragment in re.split(r"[;,]", known_nt or ""):
        token = fragment.strip()
        if not token:
            continue
        normalized = token.casefold()
        if normalized.endswith("-negative"):
            negatives.append(token)
            negative_id = _ALIASES.get(normalized[:-len("-negative")].strip())
            if negative_id:
                negative_ids.add(negative_id)
            continue
        identity = _ALIASES.get(normalized)
        if identity is None or not _INDEX[identity]["taggable"]:
            unknown.append(token)
            continue
        positives.setdefault(identity, set()).add(token)
    tags = [{"messenger_id": identity, "matched_tokens": sorted(tokens),
             "implementation_status": _INDEX[identity]["implementation_status"],
             "provenance": "DECLARED_ANNOTATION", "source_evidence_verified": False,
             "has_negative_report": identity in negative_ids, "enables_simulation": False}
            for identity, tokens in sorted(positives.items())]
    return {"catalog_version": CATALOG_VERSION, "dataset": dataset, "neuron_id": neuron_id,
            "evidence_url": evidence_url, "tags": tags, "negative_tokens": negatives,
            "unrecognized_tokens": unknown, "mutates_model": False,
            "note": "Tags preserve supplied claims; they do not establish expression, source membership, receptor coverage, or measured kinetics."}
