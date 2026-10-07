// Names describe anatomy, not validated functions or chemical release sites.
export const REGION_SOURCES = Object.freeze({
  nomenclature: 'https://pubmed.ncbi.nlm.nih.gov/24559671/',
  flywire: 'https://www.nature.com/articles/s41586-024-07558-y',
  annotation: 'https://www.nature.com/articles/s41586-024-07686-5',
  mushroomBody: 'https://elifesciences.org/articles/62576',
  olfactory: 'https://elifesciences.org/articles/57443',
  centralComplex: 'https://elifesciences.org/articles/66039',
  gall: 'https://www.virtualflybrain.org/term/ga_l-on-jrc2018unisex-vfb_00107dn7/',
});

export const SPECIES_NAMES = Object.freeze({
  DA: 'Dopamine', OA: 'Octopamine', '5HT': 'Serotonin', NO: 'Nitric oxide',
  sNPF: 'Short neuropeptide F', peptide_pool: 'Pooled peptide signal',
  TA: 'Tyramine', ACh: 'Acetylcholine',
});

const NEUROPIL_NAMES = Object.freeze({
  AL: 'Antennal lobe', AME: 'Accessory medulla', AMMC: 'Antennal mechanosensory and motor center',
  AOTU: 'Anterior optic tubercle', ATL: 'Antler', AVLP: 'Anterior ventrolateral protocerebrum',
  BU: 'Bulb', CAN: 'Cantle', CRE: 'Crepine', EB: 'Ellipsoid body', EPA: 'Epaulette',
  FB: 'Fan-shaped body', FLA: 'Flange', GA: 'Gall', GNG: 'Gnathal ganglion', GOR: 'Gorget',
  IB: 'Inferior bridge', ICL: 'Inferior clamp', IPS: 'Inferior posterior slope',
  LAL: 'Lateral accessory lobe', LA: 'Lamina', LH: 'Lateral horn', LO: 'Lobula', LOP: 'Lobula plate',
  MB_CA: 'Mushroom body calyx', MB_ML: 'Mushroom body medial lobe',
  MB_PED: 'Mushroom body pedunculus', MB_VL: 'Mushroom body vertical lobe',
  ME: 'Medulla', NO: 'Noduli', OCG: 'Ocellar ganglion', PB: 'Protocerebral bridge',
  PLP: 'Posterior lateral protocerebrum', PRW: 'Prow', PVLP: 'Posterior ventrolateral protocerebrum',
  SAD: 'Saddle', SCL: 'Superior clamp', SIP: 'Superior intermediate protocerebrum',
  SLP: 'Superior lateral protocerebrum', SMP: 'Superior medial protocerebrum',
  SPS: 'Superior posterior slope', VES: 'Vest', WED: 'Wedge',
});

const MB_KEYS = ['g1','g2','g3','g4','g5','bp1','bp2','b1','b2','a1','a2','a3','ap1','ap2','ap3'];
const GLOMERULI = ['D','DA1','DA2','DA3','DA4l','DA4m','DC1','DC2','DC3','DC4',
  'DL1','DL2d','DL2v','DL3','DL4','DL5','DM1','DM2','DM3','DM4','DM5','DM6','DP1l','DP1m',
  'V','VA1d','VA1v','VA2','VA3','VA4','VA5','VA6','VA7l','VA7m','VC1','VC2','VC3','VC4','VC5',
  'VL1','VL2a','VL2p','VM1','VM2','VM3','VM4','VM5d','VM5v','VM6','VM7d','VM7v',
  'VP1d','VP1l','VP1m','VP2','VP3','VP4','VP5'];

// Released model order, read from compartments.npz. No arrays are fabricated by this catalog.
export const COMPARTMENT_KEYS = Object.freeze([...MB_KEYS, ...GLOMERULI.map(x => `AL_${x}`),
  'AL_unresolved','CX_EB','CX_PB','CX_NO', ...Array.from({length:9},(_,i)=>`CX_FB${i+1}`),
  'CX_FB_unresolved','LA_L','LA_R','ME_L','ME_R','LO_L','LO_R','LOP_L','LOP_R','hemolymph']);

const mbNames = {g:'gamma', bp:'beta prime', b:'beta', a:'alpha', ap:'alpha prime'};
const labels = Object.create(null);
for (const key of MB_KEYS) {
  const [,lobe,index] = key.match(/^(g|bp|b|ap|a)(\d)$/);
  labels[key] = `Mushroom body ${mbNames[lobe]} ${index} (model cluster)`;
}
for (const name of GLOMERULI) labels[`AL_${name}`] = `Antennal lobe glomerulus ${name} (both sides)`;
labels.AL_unresolved = 'Antennal lobe (unresolved glomeruli, both sides)';
for (const key of ['EB','PB','NO']) labels[`CX_${key}`] = `Central complex: ${NEUROPIL_NAMES[key].toLowerCase()}`;
for (let i=1;i<=9;i++) labels[`CX_FB${i}`] = `Central complex: fan-shaped body layer ${i}`;
labels.CX_FB_unresolved = 'Central complex: fan-shaped body (unresolved layers)';
labels.hemolymph = 'Hemolymph (symbolic endocrine pool)';
labels.None = 'Unassigned brain region';
for (const [key,label] of Object.entries(NEUROPIL_NAMES)) {
  labels[key] = label;
  for (const [side,word] of [['L','Left'],['R','Right']]) {
    labels[`${key}_${side}`] = `${word} ${label[0].toLowerCase()}${label.slice(1)}`;
  }
}
export const REGION_NAMES = Object.freeze(labels);

/** Unknown identifiers stay visible; no anatomical expansion is guessed. */
export function regionLabel(key, {alias=false}={}) {
  const raw = key == null ? '' : String(key);
  const normalized = raw.replace(/\(([LR])\)$/, '_$1').replace(/^MB-/, 'MB_');
  const label = REGION_NAMES[normalized] ?? (raw ? `Unknown region: ${raw}` : 'Unassigned brain region');
  return alias && raw ? `${label} [${raw}]` : label;
}

export function speciesLabel(key, {alias=false}={}) {
  const raw = key == null ? '' : String(key);
  const label = Object.hasOwn(SPECIES_NAMES,raw) ? SPECIES_NAMES[raw] : (raw ? `Unknown chemical: ${raw}` : 'Unknown chemical');
  return alias && raw ? `${label} [${raw}]` : label;
}
