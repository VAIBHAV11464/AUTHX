# AUTHX volunteer permission and operator checklist — TEMPLATE

**This unsigned template is not obtained consent.** Store completed copies privately under `.runtime/` or another explicitly approved private location. Do not put names, signatures, contact details or raw recordings in source reports or the real AuthX database.

Study description: local college/demo evaluation of face enrollment, blink/flash checks, spoken server words, face/voice alignment and verification profiles. This is evaluation of a prototype. It does not establish real-world identity, security or spoof resistance.

Private participant identity: ____________________  Anonymous ID: __________

Operator: ____________________  Date/time in UTC: ____________________

I have been told which face images, three-second video frame sequences and audio clips will be recorded, which cameras/lighting will be used, and whether my image/voice will be used in wrong-person, photo or screen-replay testing. Recordings are preserved locally so both profiles can process the same inputs. Anonymous outcomes, metrics and provenance hashes may appear in the project report; original recordings, embeddings and signed permission stay private.

I can decline, stop a recording or ask the operator to withdraw my recordings before the evaluation report is finalized. The operator has explained how to contact them privately, who can access storage, the agreed deletion date, and what withdrawal can change if anonymous aggregates have already been finalized. No camera or microphone opens until an explicit participant/operator action. Bystanders must stay outside the capture area.

- [ ] I permit my face enrollment images, verification video frames and audio to be recorded and evaluated locally for this study.
- [ ] I separately permit my consented image/video/voice to be used as an attack source in the specifically explained photo/screen-replay/wrong-person conditions: ____________________.
- [ ] I understand that neither a certificate nor a SAFE label is a guarantee, and that the two profiles' results will be analyzed separately from faculty labels.
- [ ] I have had an opportunity to ask questions and voluntarily agree to the described study.

Participant signature/recorded permission reference: ____________________

Operator witness/review: ____________________

Private withdrawal contact/method: ____________________

Storage access list: ____________________  Agreed delete date: ____________________

Operator checks before declaring `consentReviewed: true`:

- Confirm this document actually covers the participant and the assigned recording/attack-source uses. Check permission before any collection action.
- Assign one anonymous ID and one persistent random private identity key per person across enrollment and all attack/source roles. Keep its name mapping separate. Reusing a person under another ID is not held-out separation.
- Hash the actual signed private document and record its UTC time. An example file or consent checkbox in software is not a signature/document review.
- Assign tuning/evaluation split before collection. Enrolled/source people for any case must belong to the same split. Evaluation people cannot be used for threshold tuning.
- Confirm the physically distinct camera, lighting, intended spoken word/source conditions and bystander-free view. Record truth independently from scoring output.
- Stop devices at End collection, honor withdrawal, and retain all failed/interrupted condition logs. Do not fabricate missing captures, consent or outcomes.
