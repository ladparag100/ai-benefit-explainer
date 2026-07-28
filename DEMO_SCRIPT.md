# Demo Script

## Why the existing data is enough

`app/data/members.json` isn't a generic dataset -- it's six hand-crafted
personas, each built around one specific specialist scenario:

| Member | Plan | Built-in scenario |
|---|---|---|
| Sara Kim (M001) | Signature | Has a dependent (Ethan) -> dependent ID card |
| Maria Lopez (M002) | Choice | Frame allowance used mid-2024, plan renewed -> "due for glasses" reasoning |
| James Ochoa (M003) | Advantage | New member, zero claims on file |
| David Chen (M004) | Enhanced Advantage | Self-purchased, autopay billing + an OON claim |
| Priya Patel (M005) | Signature | Used contacts already -> blocks frame eligibility this period |
| Robert Nguyen (M006) | Enhanced Advantage | Diabetes flag -> retinal imaging special coverage + a pending claim |

Every member already *is* a demo beat. More members/claims/providers
wouldn't add new capability to show -- judges care about seeing each
specialist reason correctly, not dataset size, and a bigger dataset just
means more live Gemini calls burned exploring it during judging (quota is
still tight).

Two things worth knowing going in:

- **All 6 members share the same zip (60601)**, and `app/tools/providers.py`
  filters find-a-doctor purely by plan network + a static `distance_mi`
  field -- zip isn't wired to any geolocation logic. Find-a-doctor already
  varies meaningfully by *plan* (Advantage members see fewer in-network
  results than Signature), just not by zip. Don't imply live geolocation.
- **`escalation_agent` has no member built around it**, but
  `app/rag/knowledge/escalation_and_tone.md` already defines exact trigger
  phrases ("I want to file a complaint," "let me talk to someone") -- it's
  demoable right now with the right prompt, not a data gap.

## The script

Ordered to hit all 6 specialists + ID card + frames, using member switches
themselves as a feature: the same question gets a different, correct answer
for a different member.

**1. Sara Kim -- ID card (tangible artifact, strong opener)**
- *"Can I get my ID card?"* -> PDF + download button appears
- *"Can I get my son's ID card too?"* -> pulls Ethan's card, proves it's
  reading real session state, not guessing

**2. Switch to Maria Lopez -- benefits reasoning, not lookup**
- *"Am I due for new glasses?"* -> reasons from last-used date + plan
  frequency, doesn't just recite a number

**3. Switch to Priya Patel -- the nuanced edge case**
- *"Can I get new frames this year?"* -> correctly explains
  contacts-or-frames-not-both, the trickiest rule in the dataset

**4. Switch to Robert Nguyen -- special coverage, then a claim**
- *"I have diabetes, is retinal imaging covered?"* -> special coverage lookup
- *"What's the status of my last claim?"* -> shows it Pending

**5. Switch to James Ochoa -- find a doctor + graceful "nothing here"**
- *"Find me an eye doctor nearby"* -> Advantage-network results
- *"Do you have any claims on file for me?"* -> correctly says none, doesn't
  error or hallucinate one

**6. Switch to David Chen -- billing**
- *"Why was my out-of-network exam so expensive?"* -> OON reimbursement math
  vs. in-network copay
- *"When's my next payment?"* -> autopay details

**7. Escalation (any member)**
- *"I want to file a complaint about my last visit"* -> hands off instead of
  guessing. This is the beat that proves the system knows its own limits.

**8. Frame finder (independent of member)**
- *"Can you suggest some frames for me?"* -> radio button, no LLM call
- Pick a face shape -> 3 picks with price
- *"Show me more options"* -> pagination

**9. Voice input -- do this live only if you've tested the room's mic/wifi;
otherwise describe it**
- Click the mic, ask a benefits question in Hindi or Spanish, show it
  transcribe + translate + answer correctly

**10. Close on the receipts**
- Open **"How this was answered"** on any earlier reply -> shows the routed
  agent, tool calls, and latency. Strongest credibility beat, costs nothing
  extra to show -- it's already computed.

## Practical notes

- ~12 live turns total -- rehearse it once end-to-end beforehand to confirm
  it fits the daily quota with room to spare.
- Do member switches via the sidebar picker, not "act as Maria" typed into
  chat -- cleaner and it's literally what the picker is for.
- If a call fails mid-demo (quota hiccup), the "How this was answered" panel
  on a *previous* successful turn is the recovery move -- talk through the
  architecture while a retry runs.
