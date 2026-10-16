# What the transmission result establishes, and what needs fixing

**Campaign complete. ParaLimbo showed a limited numerical advantage. Overall
predictive superiority is not established. Biological validation: PENDING.**

The completed experiment qualified ParaLimbo in 9/9 conditions and BANC in 5/9.
ParaLimbo had 1.01–1.88% lower waveform error in the five jointly qualified
conditions. Only two of those five were evaluation motions; the other three
were calibration flashes. The four unavailable BANC comparisons leave all five
registered endpoint comparisons incomplete. This is an observed result under
the frozen protocol, not a finding of statistical significance or generalization.

[Full results and every case](paralimbo-transmission-v1/README.md) ·
[Primary score evidence](paralimbo-transmission-v1/evidence/scores.json) ·
[Alternate correspondence evidence](paralimbo-transmission-v1/evidence/scores-t4d.json)

## 1. Apply numerical qualification before selecting a candidate

The implemented calibration ran development trajectories at 0.1 ms and selected
the lowest successful balanced development error. Native receipts reported an
observation-refinement diagnostic for FIR quadrature, not neural timestep
convergence; calibration scoring did not apply its final 0.001 mV acceptance
threshold either. Pilots and default
sensitivity checks did include timestep comparisons, but the calibration
scoring path did not apply them to every candidate. The selected nondefault
candidates received their final 0.1 versus 0.05 ms timestep qualification,
against the 0.001 mV limit, after development selection.

BANC proposal 4 had the lowest development MSE, 62.68797855127387, and all five
calibration jobs passed their implemented checks. Final timestep qualification
then rejected two calibration conditions and two motion conditions. Their states
were finite and their clamp counts were zero; the failures were insufficient
agreement between timesteps. Numerical eligibility was checked too late to
prevent selection of this candidate.

**Concrete next-run change:** use one qualification function for shared-input
selection, candidate selection and final scoring. On development data, require
both arms to pass the same finite-state, zero-clamp, timestep, optical and
observation checks. Use a prespecified refinement ladder to determine a common
converged timestep before freezing the next experiment. Keep identical search
opportunities and cache physically identical runs.

This addresses an avoidable selection weakness; it cannot guarantee that all
future evaluation cases pass or that ParaLimbo wins. A final qualification
failure must still remain visible. The completed experiment's candidate,
tolerance, scores and missing results remain unchanged.

Source: [development selection and final qualification](paralimbo-transmission-v1/source/src/flybrain/transmission_campaign/execution.py#L524),
[candidate selection](paralimbo-transmission-v1/source/src/flybrain/transmission_campaign/calibration.py#L116).

## 2. Diagnose the weak response before changing the model

ParaLimbo's predicted peaks were 0.062–0.254 mV; recorded peaks were
3.756–23.404 mV. The five qualified BANC responses were zero. A small error
reduction over a silent baseline does not make ParaLimbo an accurate biological
model. No implementation defect has yet been demonstrated to explain this
amplitude gap.

**Concrete next diagnostic:** use development stimuli to record each relevant
stage: external drive, relay voltage and release, T4 incoming excitation and
inhibition, T4 voltage, then the observation output. Pair these with matched
background, targeted silencing and downstream rescue. Locate whether the loss
comes from insufficient input, thresholding, cancellation, attenuation or the
observation transform before proposing a correction.

Independently check the assumed sensory gain/sign/timing, holding drive,
cell correspondence, electrical assignments and observation units. The current
observation reads one candidate root with weight 1; there is no evidence that
population averaging accidentally reduced its amplitude. The shared multiplier
2 changes sensory drive, not the reported output scale.

Graded gain can become ineffective when its cap is saturated. Raising the 0.8
cap would be a new model hypothesis requiring separate stability checks, not a
demonstrated repair. Neither larger drive, another cell mapping, nor forcing
every neuron to respond is an established solution. Correct transmission must
also preserve appropriate inhibition, selectivity and timing.

Source: [input-drive scaling](paralimbo-transmission-v1/source/src/flybrain/transmission_campaign/data.py#L281),
[observation transform](paralimbo-transmission-v1/source/src/flybrain/paralimbo_upgrade/observation.py#L214),
[gain-cap sensitivity](paralimbo-transmission-v1/source/src/flybrain/transmission_campaign/dynamics.py#L53),
[retained transmission diagnosis](paralimbo-transmission-v1/evidence/transmission-diagnosis.json).

## 3. Close the engineering evidence gaps

Final T4 receipts do not establish serialized checkpoint replay for every
request; exact replay evidence covers four direct pilots. Final acceptance also
lacks fresh paired cold-start/cache equivalence and a hard-crash recovery
exercise. A new implementation needs focused fixtures and independent checks
for the shared qualification path, plus those execution checks at an explicit,
prespecified scope. This supports trustworthy computation, independently of
which model has lower prediction error.

Source: [independent engineering review](paralimbo-transmission-v1/reviews/engineering-review.md).

## 4. Test the corrected model on evidence it has not been tuned against

These nine conditions are now exposed. They can support diagnosis and
reproduction, but cannot become an untouched confirmatory test for a repair
chosen after seeing their results.

Before another evaluation, freeze a separately identified experiment with a
meaningful improvement criterion, all primary endpoints, failure handling and
subgroup regression limits. Keep BANC's calibration opportunities equal. Report
every result, including ties, losses and qualification failures.

For a complete numerical accuracy comparison, obtain qualified predictions
from both arms for all registered conditions. For biological generalization,
add independently supported cell/input correspondence, multiple independent
cells or animals, repeats and uncertainty estimates with intact held-out groups.
The descending population benchmark additionally needs validated stimulation
and measured-population mappings and an implemented observation contract.
Anonymous ROIs cannot be treated as identified modeled neurons.

**Removing the biological-validation limitation requires new evidence, not a
different label.** None of these proposed changes has been executed as a new
campaign, and none guarantees a win.
