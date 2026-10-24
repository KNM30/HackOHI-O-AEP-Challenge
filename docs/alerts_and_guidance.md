# Guidance, alerts, messages and the assistant (Milestone 4)

Everything here belongs to a **challenge prototype with simulated scenarios**. It does not describe AEP policy or send
anything.

## 1. Estimate accuracy shown to customers

Restoration results carry a `range_kind`. Templates, guidance and the assistant all read it, so an estimate is never
shown as more certain than it is.

| `range_kind` | Meaning | Shown as |
|---|---|---|
| `bounded` | All required work is covered by the workbook | "6 h - 14 h" |
| `lower_bound_only` | Part of the work (for example conductor re-stringing) has no labor entry | "At least X (repair scope incomplete)". The modeled upper time is explained, but never presented as a bound. |
| `conditional` | Isolation is possible | **Two alternative outcomes**: "If crews isolate: X - Y" and "Otherwise, after the repair: A - B". This is never one interval. |
| `crew_infeasible` | The selected crews are too small for a required job | "The selected crews cannot do a required repair under these assumptions", with the minimum crew size. This is not reported as missing data. |
| `insufficient_data` | A required repair has no workbook mapping | "Cannot estimate", with the reason |
| `not_interrupted` | The premise keeps power in this simulation | "No restoration needed" |

`network_uncertain` is set when the premise is unresolved, or when a fault walk skipped an unevidenced device. It adds
a caveat to messages and guidance.

The risk score was not retuned, and the labor-unit assumption stays in `labor_config.py` and is disclosed on every
result.

## 2. Preparation guidance

The content is in [`guidance_content.py`](../backend/app/guidance_content.py); the rules are in
[`guidance.py`](../backend/app/guidance.py).

- **Inputs:**
  - the risk band
  - whether the scenario interrupts the premise
  - a planning horizon: the bounded upper time, the repair-based conditional time, or "at least" for lower bounds
  - incomplete or uncertain estimates
  - needs the customer **declared this session**
- **Never used:** the customer layer's life-support flag (`critical_c`) or any other source attribute.
- **Format:** each recommendation has a short action, a computed "why", an urgency, a category (emergency or routine),
  and a source.

Sources were verified on **2026-10-24** by reading each page:

| Source | Used for |
|---|---|
| [Ready.gov - Power Outages](https://www.ready.gov/power-outages) (page updated 2026-06-04) | kit, flashlights, medical-device plan, fridge about 4 h and full freezer about 48 h, discard food at 40°F or warmer for 2 h or more, medication after more than a day, generator 20 ft rule, no gas stove for heat, unplug electronics, extreme temperatures, CO detector |
| [CDC - Prevent Carbon Monoxide Poisoning](https://www.cdc.gov/natural-disasters/psa-toolkit/prevent-carbon-monoxide-poisoning.html) (reviewed 2026-08-25) | generators at least 20 ft from doors, windows and vents; battery CO detector |
| [Appalachian Power - Safety](https://www.appalachianpower.com/safety/) | stay away from downed lines and anything touching them, report on 800-956-4237, tell the utility if you run a generator, unplug major appliances, leave one light switch on, kit contents |
| [Appalachian Power - Power Line Safety](https://www.appalachianpower.com/safety/power-lines) | treat all lines as live, keep away |

Items without a verified source are marked as such and carry no citation:

- "call 911 if life is in danger" (general emergency practice)
- "arrange someone to check on you" (based on declared accessibility needs)
- "choose an alert channel you can receive"

A declared medical need adds a planning item and an escalation note. Both say explicitly that it **does not register
you with the utility or guarantee faster restoration**.

## 3. Prototype alert rules (`alert_config.py`, not AEP policy)

The app keeps these questions separate:

1. **Is an alert warranted?**
2. **Has the customer opted in?**
3. **Is a channel selected?** (Demo only; no contact details are collected.)

Only all three together produce a "would be sent (simulated)" message.

| Trigger | Rule |
|---|---|
| Elevated storm risk | The pre-storm band reaches `PRE_STORM_MIN_BAND` (default `high`) under the chosen severity scenario |
| Outage confirmed | Only after the explicit **"Simulate: outage confirmed"** action for this scenario, and only if the premise is interrupted in it. Risk and historical damage never confirm an outage. |
| Estimate updated | After confirmation: the latest modeled time moves by at least max(2 h, 25%) since the last message sent |
| Loss of confidence or estimate | The estimate kind changes (for example to "cannot estimate"), or confidence drops from moderate to low |
| Restoration complete | Only after the explicit **"Simulate: power restored"** action. A predicted finish time passing never counts. |

**Escalation:** a declared medical need plus an outage that may exceed 4 h, or cannot be estimated, adds "follow your
medical outage plan; call 911 if health is at risk; this does not guarantee faster restoration".

**Duplicates:** each preview has a deterministic `dedupe_key` (type, premise, scenario, estimate signature). The
session log adds a message once per key, so re-renders and repeated identical calculations add nothing.

**Resets:**
- Resetting or changing the scenario clears simulated events and their messages, but keeps pre-storm alerts.
- Changing the premise clears everything.

## 4. Message templates (`alerts.py`)

Each message has five parts, in order:

1. `[SIMULATED - prototype message, not from AEP]`
2. what happened
3. the estimate or uncertainty, worded per `range_kind`
4. what to do (from approved guidance)
5. what would trigger the next update

The message ends with a prototype footer, so copied text keeps the simulated label.

Templates never include internal equipment IDs, workbook references, percentages or utility statements. The
unaffected, conditional, incomplete and cannot-estimate cases each have their own wording, and none of them makes a
promise.

## 5. Grounded assistant (`assistant.py`)

- **Source of truth:** `/api/assistant` reruns the same server-side computation as `/api/briefing` (risk, the fixed
  scenario, restoration, guidance, alerts).
- **Sanitized snapshot:** the model receives only:
  - premise alias and circuit label
  - risk and its factors
  - scenario counts and the premise's status
  - restoration kind, display, "why", warnings and assumptions
  - one validated **what-if**: one more crew, computed by the backend scheduler
  - approved guidance
  - alert state
  - declared needs
  - the client's previous estimate (numbers and enums only)
  
  No raw data, internal identifiers (removed by regex), medical source flags or facility locations are included.
- **Provider (verified 2026-10-24 against the official docs and with live calls):**
  - Official `anthropic` Python SDK 2.3.0 (the latest release) calling the **stable** `client.messages.create`. JSON-schema
    output via `output_config.format` is GA, with no beta header. Effort is `low`.
  - **Default model `claude-haiku-5-5`**: the economical current model (from $0.10 / $0.50 per million input / output
    tokens), which supports structured outputs and `effort`. Override it with `AI_MODEL`; the model actually served is
    recorded in the developer diagnostics.
  - **No server-side fallback.** Milestone 4 sent `fallbacks: "default"`, a beta feature. On Claude Haiku 5.5 it does
    nothing, and on larger models it can answer from a different model without telling the user. It was removed so the
    answering model is always the configured one. A refusal (`stop_reason: "refusal"`) is shown as a standard answer.
  - **Limits:** `max_tokens` 2000, `AI_TIMEOUT_S` 15 s, and `AI_MAX_RETRIES` 1 (SDK retries on connection errors, 408,
    409, 429 and 5xx), so the worst case is about 30 s. The snapshot is capped at about 12k characters and the question
    at 500 characters.
  - **Authentication:** the SDK resolves credentials from the environment (`ANTHROPIC_API_KEY`, etc.), enabled only when
    `AI_PROVIDER=anthropic`. With no credentials, SDK 2.3.0 raises `TypeError("Could not resolve authentication
    method...")`. This is handled as "not configured" instead of returning a 500 (found with the real SDK).
  - **Live checks** (four calls, about 3-4 s and 2.5-4.6k input tokens each, served by `claude-haiku-5-5`):
    - risk explanation
    - an incomplete ("at least") restoration estimate
    - an estimate change after crews went from 3 to 1
    - the conditional isolation case

    All four were consistent with the snapshot. The incomplete estimate stayed "at least", the isolation case stayed
    two conditional outcomes, and no answer contained a confirmation, probability, promise, priority claim or internal
    identifier.
- **Answer status** shown to the customer, with technical detail under "Developer details":

  | Status | Customer text |
  |---|---|
  | `ai` | AI explanation, checked against the calculations |
  | `not_configured` | Standard answer: AI not set up (including a missing key) |
  | `provider_failed` | Standard answer: AI service did not respond (error, timeout, rate limit or refusal) |
  | `validation_failed` | Standard answer: AI wording could not be matched to the calculations |
  | `not_shared` | Standard answer: the question asks for data this app does not share |

  Server logs record status, model, stop reason, token counts and latency only. They never include the question text,
  the snapshot or credentials.
- **Validation (reviewed in M5).** It reduces risk; it does **not** prove grounding. The calculated numbers stay
  authoritative and are always shown next to the explanation.
  - **Now accepted** (previously rejected):
    - rounding (88 for 87.63) and hour/day conversions of snapshot durations
    - spelled-out small numbers
    - percentages quoted from the snapshot (the 25% alert rule)
    - negated claims ("does not guarantee", "no priority restoration")
    - phone and distance numbers from approved guidance
  - **Now rejected** (previously missed):
    - spelled-out invented numbers ("forty hours")
    - an "at least" estimate described without any lower-bound wording
    - a conditional estimate merged into one range
    - "will be restored by" without hedging
    - "outage confirmed" when no simulated confirmation exists
    - probability phrasing
    - official AEP statements
    - mentions of the life-support source flag
  - Each case has a regression test in `backend/tests/test_m5_assistant.py`.
- **Standard answers (no AI):** deterministic intent answers for risk, delays, crews, preparation, estimate changes and
  alerts. They are used when no provider is configured, the provider fails or times out, or the check fails, and the
  reason is always shown.
  - Questions about other people's data are answered with a limitation and never sent to the provider.
  - Unsupported questions get an explicit limitation.
- **Staleness:** every briefing has a `snapshot_version`, a hash of all inputs. The panel clears its answer when the
  version changes and drops answers computed for an older version. Each answer carries its own question.

## 6. Browser storage

None. Preferences, opt-in, channel, simulated events and the message log live in React state for the session only, and
are cleared on reload. The `?medical=1&alerts=sms` demo link only presets them in memory.
