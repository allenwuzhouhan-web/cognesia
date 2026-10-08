# ParaLimbo implementation and release plan

ParaLimbo is the name of the Cognesia model integrating BANC anatomy and
FlyWire evidence. This plan authorizes the implementation sequence for the
requested GitHub releases and keeps the website additions as a separate plan.

## Release scope

| Deliverable | Scope and completion evidence |
| --- | --- |
| ParaLimbo 0.1 preview | Executable, versioned correspondence and annotation merge; source fidelity audit; tests and runtime verification; model documentation and GitHub prerelease |
| Cognesia 0.0.2 preview | Current source application with personal access key protection, installation instructions and tested release assets on GitHub |
| Website additions plan | Signup, individual access key issuance, account recovery, per-user usage and administrator dashboard architecture, milestones and acceptance checks |

Original Cognesia code remains all rights reserved, as requested. Third-party
data and components retain their own terms. Public source availability does
not itself grant modification or redistribution rights.

The preview must distinguish recovered source information from demonstrated
biological prediction improvements. The requirements in the
[release specification](README.md) continue to govern accuracy claims. There
is no verified independent biological benchmark in the current project that
establishes superiority of the proposed merged model.

## Phase one freeze and document

1. Preserve the current BANC and historical fused model artifacts and hashes.
2. Introduce internal provider `paralimbo-v0-1-0` and public release tag
   `paralimbo-v0.1.0-alpha.1`, keeping model and app versions distinct.
3. Pin BANC materialization, donor table checksums, compiler policy and all
   executable output hashes. Record source terms and acquisition instructions.
4. Keep private credentials, datasets, local run records and old local Git
   history outside the public source export.

## Phase two implement the merge

1. Build a correspondence record for every BANC neuron. Classify unique
   curator-supported homologs, type-level matches, ambiguous candidates,
   missing donors and unresolved neurons. Preserve rejection reasons.
2. Retain separate native transmitter and peptide annotations. Recover the
   omitted peptide field and normalize chemical and cell-class aliases in the
   new provider only.
3. Transfer supported properties through eligible correspondences, checking
   negative evidence and conflicts per property. Do not require the entire
   destination annotation field to be empty. Keep inferred and native evidence
   distinguishable in both the neuron table and transfer ledger.
4. Preserve BANC node identity, ordering and connectivity. Keep the existing
   electrical-mode and fast-sign policy explicit. A peptide transfer does not
   alter fast synaptic signs. Do not copy FlyWire's assumed modes as measured
   physiology.
5. Freeze the output and integrate ParaLimbo into the CLI, model catalogue,
   actual chemistry runtime and user-facing model selection.
6. Eliminate unrelated FlyWire runtime-file requirements for the new provider.
   Pin or declare optional optical inputs that affect runs.

Circuit replacement remains conditional on checked individual endpoint maps,
comparable donor quality, complete boundary accounting and validation. The
preview must report zero replacements if no circuit meets those conditions.
Cell-type matching alone cannot justify specific donor connections.

## Phase three verify and report

1. Test exact large IDs, duplicate and absent donors, negative annotations,
   conflicting properties, ambiguous matches and reproducible compilation.
2. Verify unchanged BANC topology and electrical partitions against frozen
   baseline artifacts. Verify that old model hashes still load unchanged.
3. Independently reconcile compiled annotations with the pinned source fields.
   Report both the baseline omissions and the recovered records. Label this
   source fidelity and coverage evidence.
4. Exercise real ParaLimbo loading, chemical source projection, receptor
   targeting and a bounded numerical run. Record run conditions, finite-state
   checks and diagnostics without treating them as biological validation.
5. Run relevant Python and browser regression checks, public-export audits,
   clean-checkout verification and package builds.
6. Publish exact observed results, failures and pending biological gates. Do
   not promote the preview as globally more accurate or world-first.

## Phase four protect the current app

The user confirmed that passkey means a personal bearer access key issued by
the website, not WebAuthn or biometric sign-in.

1. Verify keys against a configured trusted HTTPS Cognesia access service;
   allow HTTP only for explicitly local development endpoints.
2. Gate the official viewer and research interface, including raw APIs,
   downloads and WebSocket handshakes. Use short-lived local sessions and keep
   keys out of URLs, public files, browser storage and logs.
3. Fail closed for missing configuration, invalid/revoked keys or unavailable
   verification. Document any bounded session revalidation interval.
4. Preserve private authenticated service-to-service operation without adding
   an unauthenticated bypass to the browser interface.
5. Test unauthorized, valid, expired/revoked, cross-origin and malformed
   requests. Verify native-window compatibility and release installation.

Website self-service signup and the administrator panel are planned separately.
The existing administrative key-issuance command provides the initial
provisioning route. Publishing static website files does not create a live
account service. Source availability means an independently modified local
client cannot be used as a trusted enforcement or usage-metering boundary;
hosted authorization and usage accounting must remain server-side.

## Phase five package and publish

1. Complete model card, provenance, validation results, reproducibility guide
   and release notes. Add the website implementation plan.
2. Prepare reviewed, clean source exports and wheel/install assets. Include
   checksum manifests; avoid redistributing model data with unresolved terms.
3. Synchronize the clean export into a fresh checkout of the existing GitHub
   repository, preserving remote history and checking for concurrent changes.
4. Publish the authorized Cognesia app release and ParaLimbo prerelease with
   distinct tags and accurate release descriptions. Verify remote tags,
   downloadable assets and applicable CI results.
5. Report the release URLs, completed checks, current access provisioning and
   remaining biological and website deployment work.
