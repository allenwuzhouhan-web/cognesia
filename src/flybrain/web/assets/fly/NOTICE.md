# NeuroMechFly whole-animal anatomy

These are the original full-resolution NeuroMechFly v2 surfaces, produced by the
Neuroengineering Laboratory, EPFL (NeLy-EPFL), and distributed by the official
[FlyGym project](https://github.com/NeLy-EPFL/flygym) under Apache-2.0. See
[LICENSE-APACHE-2.0.txt](LICENSE-APACHE-2.0.txt). The body model is based on a
micro-CT scan of an adult female *Drosophila melanogaster*; its provenance is
described in [Wang-Chen et al., 2024](https://doi.org/10.1038/s41592-024-02497-y)
and [Lobato-Rios et al., 2022](https://doi.org/10.1038/s41592-022-01466-7).

The versioned source is `neuromechfly_fullsize_meshes_20260623a` in the official
[EPFL public dataset bucket](https://datasets.epfl.ch/nely-public-share/?list-type=2&prefix=flygym_assets%2Fneuromechfly_fullsize_meshes_20260623a%2F).
Its accompanying `source/metadata.yaml` identifies the license and publication.
The official [FlyGym asset loader](https://github.com/NeLy-EPFL/flygym/blob/38c8ec61034cd59bc5ba0de20688d4a3c0000d60/src/flygym/utils/assets_lazy_loading.py)
identifies that bucket/version. Rig transforms, neutral joint values, segment
colors and mesh mirrors are from the official
[fly-svg-maker model data](https://github.com/NeLy-EPFL/fly-svg-maker/blob/152506d3471646f009480c81f34aefbaec29a6e5/assets/model.json),
whose [asset notice](https://github.com/NeLy-EPFL/fly-svg-maker/blob/152506d3471646f009480c81f34aefbaec29a6e5/assets/NOTICE)
identifies the NeuroMechFly/FlyGym Apache-2.0 origin. Its unchanged text is retained in `SOURCE-NOTICE.txt`.

## Packaging changes

Cognesia retains every source STL triangle without decimation. Identical vertices
are indexed, normals are recomputed by area-weighted averaging, and the original
neutral-pose transforms are applied in the renderer. Right-side pieces use the
official mirrored geometry. This produces 447,417 rendered triangles across 69
segments from a 6,687,192-byte browser geometry buffer. The original 14,027,406-byte
source collection remains in `source/`. No synthetic hairs, eye facets, textures,
or anatomical surfaces have been added. Surface colors, opacity and lighting are
illustrative rendering choices, not measured pigmentation or optical properties.

`manifest.json` includes each original file URL, size, ETag and SHA-256; pinned
repository commits; packed geometry offsets/hash; segment transforms; and bounds.
The neutral joint positions agree with the official rig reference to
4.86e-10 mm. The binary loader checks its SHA-256 where Web Crypto is available.
Rebuild with `python build_assets.py` in a NumPy-enabled environment. Network
sources are fetched from pinned commits/version paths and downloaded STL bytes
are checked against the dataset's ETags before packaging.

## Coordinates and recording limits

Mesh coordinates are millimetres: +X anterior, +Y left, +Z dorsal. The fly is
displayed in the source neutral pose. It has no locomotor simulation or inferred
body movement. The view does not launch a network simulation or advance time.

FlyWire brain positions retain their original relative geometry, point identity
and neuron array index. A uniform scale and axis rotation fit the brain inside
the head bounding box: original brain +X maps to fly −Y, +Y maps to fly +X, and
+Z maps to fly +Z. This is an explicit display assumption across different
animals, **not anatomical co-registration**. No spatial claims beyond the
original brain anatomy and compartment memberships follow from this placement.

Only supplied recorded frames color brain points. Voltage is in mV and chemical
exposure is the recorded, membership-weighted model compartment field in a.u.
Unassigned chemical exposure remains unknown, not zero. The body itself has no
measured chemical field. In the absence of a recording, the brain remains a
static anatomical point cloud with no activity or animated current streams.

## Integration

Import `createFlyBodyPanel` from `fly-body.js` and include `fly-body.css`. Construct
with `{THREE, OrbitControls, host}` using the application's existing Three.js
version. The module injects its own display controls and provenance. Await
`.ready`; calls before readiness are retained. Pass the unmodified original
`positions` and optional `visibleIndices` through `.setBrain(...)`. Use
`.setFrame({values, mode, range, timeMs, hasRecording, label})` with values in
exact full neuron order; modes are `absolute`, `baseline`, `delta`, `chemical`,
or `anatomy`. `hasRecording:false` always clears activity display. The parent
owns shared playback/seek controls; this module never changes playback.

`.resize()`, `.focusBrain()`, `.resetCamera()` and `.dispose()` are available.
Resize, orbit interaction and changed frames trigger redraws; there is no
perpetual animation or automatic rotation. Disposal releases its GPU buffers,
materials, renderer and context.
