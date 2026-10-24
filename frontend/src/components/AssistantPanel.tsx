import { Fragment, useEffect, useRef, useState } from "react";
import { api, isAbort } from "../api";
import { isCurrentAnswer } from "../commsState";
import type { AssistantResponse, BriefingRequest, PreviousEstimate } from "../types";

type Section = keyof AssistantResponse["answer"];

const LABEL: Record<Section, string> = {
  facts: "Scenario results",
  estimates: "Model estimates (simulated)",
  assumptions: "Assumptions",
  actions: "What you can do",
  limitations: "Limitations",
};
const SUPPORT_ORDER: Section[] = ["estimates", "facts", "assumptions", "actions", "limitations"];

// Which section answers the question most directly, by the backend's intent classification.
const LEAD: Record<string, Section[]> = {
  prepare: ["actions", "facts", "estimates", "limitations"],
  alerts: ["facts", "actions", "limitations"],
  changed: ["facts", "estimates", "limitations"],
  private: ["limitations"],
  unsupported: ["limitations"],
};
const DEFAULT_LEAD: Section[] = ["estimates", "facts", "actions", "limitations"];

/**
 * Up to three suggestions that fit the current state. They use the challenge brief's customer
 * questions where possible; each wording maps to an existing backend intent.
 */
export function suggestions(scenarioActive: boolean, hasPrevious: boolean): string[] {
  if (scenarioActive) {
    return [
      "How long could restoration take?",
      "How would another crew change this?",
      hasPrevious ? "Why did my estimate change?" : "Do I qualify for outage alerts?",
    ];
  }
  return ["Will I lose power?", "What should I do to prepare?", "Do I qualify for outage alerts?"];
}

interface Props {
  request: BriefingRequest | null;
  snapshotVersion: string | null;
  previous: PreviousEstimate | null;
  contextLabel: string | null; // "premise, severity, scenario" the answer is grounded in
  scenarioActive: boolean;
}

export function AssistantPanel({ request, snapshotVersion, previous, contextLabel, scenarioActive }: Props) {
  const [question, setQuestion] = useState("");
  // the answer keeps the question and context it answers, so a pending question never relabels an old answer
  const [answer, setAnswer] = useState<(AssistantResponse & { question: string; context: string | null }) | null>(null);
  const [asked, setAsked] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error" | "stale">("idle");
  const [cleared, setCleared] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const hasAnswer = useRef(false);
  hasAnswer.current = answer !== null;

  // Inputs changed: the previous answer no longer describes the current scenario.
  useEffect(() => {
    controller.current?.abort();
    setCleared(hasAnswer.current);
    setAnswer(null);
    setStatus("idle");
  }, [snapshotVersion]);

  const ask = (q: string) => {
    if (!request || !snapshotVersion || !q.trim()) return;
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    const sentFor = snapshotVersion;
    const sentContext = contextLabel;
    setAsked(q);
    setAnswer(null);
    setCleared(false);
    setStatus("loading");
    api
      .assistant(request, q.trim().slice(0, 500), previous, c.signal)
      .then((r) => {
        if (c.signal.aborted) return;
        if (!isCurrentAnswer(sentFor, r.snapshot_version)) {
          setStatus("stale");
          return;
        }
        setAnswer({ ...r, question: q, context: sentContext });
        setStatus("idle");
      })
      .catch((e) => {
        if (!isAbort(e)) setStatus("error");
      });
  };

  const lead = answer ? (LEAD[answer.intent] ?? DEFAULT_LEAD).find((k) => answer.answer[k].length) : undefined;
  const firstLimit = answer && lead !== "limitations" ? answer.answer.limitations[0] : undefined;
  const busy = !request || status === "loading";

  return (
    <section className="card" aria-labelledby="ask-title">
      <h2 id="ask-title">Ask about your results</h2>
      {contextLabel && <p className="muted small">Based on your current scenario: {contextLabel}.</p>}
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
      >
        <input
          id="ask-input"
          value={question}
          maxLength={500}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={request ? "Ask a question about your results" : "Choose your home first"}
          disabled={!request}
          aria-label="Your question"
        />
        <button type="submit" disabled={busy || !question.trim()}>
          Ask
        </button>
      </form>
      <div className="chips" aria-label="Suggested questions">
        {suggestions(scenarioActive, previous !== null).map((q) => (
          <button key={q} type="button" className="chip" disabled={busy} onClick={() => ask(q)}>
            {q}
          </button>
        ))}
      </div>

      <div aria-live="polite">
        {status === "loading" && <p className="muted small">Thinking about "{asked}"...</p>}
        {status === "error" && (
          <p className="error small">The assistant is unavailable. Overview and Explore scenarios still show all results.</p>
        )}
        {status === "stale" && <p className="muted small">Your inputs changed while answering. Please ask again.</p>}
        {status === "idle" && cleared && !answer && (
          <p className="muted small">Your home or scenario changed, so the previous answer was cleared. Ask again for an updated answer.</p>
        )}
        {answer && (
          <div className="answer">
            <p className="answer-q">
              <strong>{answer.question}</strong>{" "}
              <span className={`tag ${answer.mode === "ai" ? "tag-model" : "tag-fallback"}`} title={answer.status_text}>
                {answer.mode === "ai" ? "AI explanation" : "Standard answer"}
              </span>
            </p>
            {lead ? (
              <ul className="lead">
                {answer.answer[lead].slice(0, 2).map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            ) : (
              <p className="muted small">No answer could be produced for this question.</p>
            )}
            {firstLimit && <p className="small limit-note">Limitation: {firstLimit}</p>}
            <details>
              <summary>Supporting calculations and assumptions</summary>
              {SUPPORT_ORDER.filter((k) => answer.answer[k].length).map((k) => (
                <div key={k}>
                  <h4>{LABEL[k]}</h4>
                  <ul className="small">
                    {answer.answer[k].map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                </div>
              ))}
              {answer.context && <p className="muted small">Answered for: {answer.context}.</p>}
              <p className="muted small">{answer.status_text}</p>
              <p className="muted small">{answer.disclaimer}</p>
              {(answer.fallback_reason || Object.keys(answer.diagnostics).length > 0) && (
                <details>
                  <summary className="small">Developer details</summary>
                  <dl className="counts small">
                    <dt>status</dt>
                    <dd>{answer.status}</dd>
                    {answer.fallback_reason && (
                      <>
                        <dt>reason</dt>
                        <dd>{answer.fallback_reason}</dd>
                      </>
                    )}
                    {Object.entries(answer.diagnostics).map(([k, v]) => (
                      <Fragment key={k}>
                        <dt>{k}</dt>
                        <dd>{v}</dd>
                      </Fragment>
                    ))}
                  </dl>
                </details>
              )}
            </details>
          </div>
        )}
      </div>
    </section>
  );
}
