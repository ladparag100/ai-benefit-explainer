# 3-Minute Hackathon Pitch

Timed script, demo included. Rehearse it once end-to-end with a stopwatch --
live Gemini latency (1-3s per turn) is the part that eats your buffer, not
the talking.

## Timing overview

| Time | Segment |
|---|---|
| 0:00-0:25 | Hook + problem |
| 0:25-0:45 | What we built (one breath) |
| 0:45-2:35 | Live demo -- 3 beats |
| 2:35-2:55 | Why this isn't just a chatbot wrapper |
| 2:55-3:00 | Close |

## Script

### Hook + problem (0:00-0:25)

> "Raise your hand if you've ever tried to figure out your own vision
> benefits and given up. [pause] Right -- because the answer depends on
> your specific plan, what you've already used this year, and rules nobody
> explains in plain English. Most chatbots either can't answer that, or
> confidently make something up. We built something that actually knows
> the difference."

### What we built (0:25-0:45)

> "This is a multi-agent VSP benefits explainer. One supervisor agent
> routes every question to the right specialist -- ID cards, benefits,
> claims, billing, find-a-doctor, or escalation -- built on Google ADK and
> Gemini on Vertex AI, grounded in a real knowledge base so it never
> guesses at plan rules. It's live right now on Cloud Run, not just running
> on my laptop."

### Live demo (0:45-2:35) -- 3 beats, member switches via the sidebar

**Beat 1 -- tangible proof it's not guessing (0:45-1:15)**
- Member: **Sara Kim**
- Type: `Can I get my son's ID card?`
- Say while it runs: *"It's not just answering in text -- it's generating
  a real ID card PDF, and it knows Sara has a dependent named Ethan without
  me telling it."*
- Point at the download button and the dependent's own member number.

**Beat 2 -- the reasoning, not a lookup (1:15-1:55)**
- Switch member: **Priya Patel**
- Type: `Can I get new frames this year?`
- Say while it runs: *"This is the trickiest rule in vision insurance --
  contacts or glasses, not both, per benefit period. Watch it explain the
  actual reason, not just say no."*
- Let the answer land, then: *"That's reasoning over her real data, not a
  canned FAQ answer."*

**Beat 3 -- it knows its own limits (1:55-2:35)**
- Same member is fine. Type: `I want to file a complaint about my last visit`
- Say while it runs: *"And when it's genuinely not this system's call to
  make, it doesn't improvise -- it hands off to a human with full context,
  so the member never repeats themselves."*
- Point out the escalation ticket ID appearing in the reply.

### Why this isn't just a chatbot wrapper (2:35-2:55)

> "Three things most hackathon prototypes skip: it's grounded -- every
> plan fact traces back to a tool call, never the model's memory. It's
> guarded -- Gemini safety filters, local PII redaction before anything
> hits our logs, and prompt-injection screening, all without a single extra
> paid API. And it's observable -- "
- Click **"How this was answered"** on any earlier reply.
> "-- every reply already shows you exactly which agent and tool answered
> it, and how long it took. Nothing here is a black box."

### Close (2:55-3:00)

> "Six specialists, one supervisor, grounded and guarded, live on Cloud Run
> right now. Happy to take it anywhere you want to poke at it."

## If something breaks live

- A quota hiccup mid-demo: open **"How this was answered"** on a *previous*
  successful turn and talk through the architecture while you retry --
  this is the one move that turns a stall into content.
- Don't re-type the same prompt twice in a row if it fails -- switch member
  or rephrase, so you're not visibly waiting on the exact same call.

## Cut list (if you're over time in rehearsal)

Cut Beat 3 (escalation) first -- Beats 1 and 2 alone still prove both
"real artifact" and "real reasoning." Never cut the "How this was
answered" close -- it's the cheapest, highest-credibility moment in the
whole pitch.

## Production Q&A (2 minutes)

The "how would you actually productionize this" question is close to
guaranteed. Answer with what's *already true* first, then the honest gap
-- judges trust "here's exactly what's missing" far more than "it's
basically done."

**Q: How does this scale beyond a demo?**
> "It already runs on Cloud Run, so horizontal autoscaling is free. The
> real gap is session storage -- it's in-memory per instance right now,
> so a conversation can lose context if two requests land on different
> instances. That's a known, scoped fix: swap in a persistent session
> store. Same story for the RAG index -- it's on ephemeral `/tmp` today,
> so multiple instances would each reindex independently; production
> wants that on a shared store."

**Q: What about auth and real member data?**
> "Today the member picker is a dropdown -- fine for a demo with fake
> data, not a login system. Production needs real member auth tied to
> actual VSP accounts before this touches real data, full stop."

**Q: What guardrails are actually in place?**
> "Three layers, already built and deployed: Gemini's safety filters,
> local PII redaction before anything hits our logs, and prompt-injection
> screening that blocks a bad request before it even reaches the model --
> all without a paid third-party API. The honest gap: those currently
> only wrap the supervisor, not the six specialists underneath it, and
> there's no automated check yet that a reply's dollar amounts actually
> trace back to a tool call versus the model just sounding confident."

**Q: How do you handle cost and quota at scale?**
> "We're deliberately on the flash-tier models, not pro, to stay inside
> free-tier quota during the hackathon. Production would mean a real
> Vertex quota increase, usage-based budget alerts, and caching for the
> repeat questions -- plan comparisons don't need a fresh Gemini call
> every time."

**Q: What's the testing and deployment story?**
> "91 unit tests today, all offline -- no live GCP calls, so they run in
> under two seconds and can't rack up API cost. What's missing is CI --
> right now a human runs pytest and deploys by hand. A GitHub Actions
> workflow gating merges on that test suite, with auto-deploy to Cloud
> Run on top, is the concrete next step, not a maybe."

**Q: Is this HIPAA-compliant / ready for real health data?**
> "Not today, and I won't pretend otherwise. Vertex AI is HIPAA-eligible
> under a signed BAA with Google Cloud, which is the real path -- but no
> BAA is signed, there's no access audit trail beyond what Cloud Logging
> gives for free, and the PII redaction we built is a safety net for logs,
> not a compliance control. That's real work before this is anywhere near
> production member data, and I'd rather say that plainly than oversell it."
