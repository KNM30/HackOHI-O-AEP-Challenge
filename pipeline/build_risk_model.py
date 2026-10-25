"""Fit and validate the pre-storm outage-risk model on every circuit in the territory.

Usage:  python pipeline/build_risk_model.py

Unit of analysis: (premise, historical storm event). A premise is labelled "hit" in an
event when at least one ARCOS damage record from that event would have interrupted it
under the app's own protection model (backend/app/network.py relation()). That is a
proxy for an outage, not a confirmed outage: ARCOS records damage, not customer outages.

A logistic regression learns how storm size and the premise's network features map to
that label. It is validated by leaving out one whole storm at a time. Features, labels and
the history signal all come from the same backend code the app uses at request time.

Writes data/processed/risk_model.json (coefficients, uncertainty, validation, calibration,
event sizes and territory percentiles; no premise-level data).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import circuit as cm  # noqa: E402
import critical  # noqa: E402
from build_subset import circuit_doc  # noqa: E402
from common import PROCESSED, read_layer  # noqa: E402

from app import risk_config as rcfg  # noqa: E402
from app.network import CircuitNetwork, assign_events  # noqa: E402
from app.risk import event_hits, model_inputs  # noqa: E402

MIN_EVENT_SIZE = 10  # territory-wide damage records; smaller events are too sparse to label
L2 = 1.0             # ridge penalty on standardised coefficients (same scale as sklearn C=1)


# ------------------------------------------------------------------ logistic regression (numpy/scipy)
def _nll(beta, Z, y, w, l2):
    lg = Z @ beta
    ll = w * (y * lg - np.logaddexp(0, lg))
    p = 1 / (1 + np.exp(-lg))
    grad = -(Z.T @ (w * (y - p)))
    grad[1:] += l2 * beta[1:]
    return -ll.sum() + 0.5 * l2 * (beta[1:] ** 2).sum(), grad


def fit_logistic(X, y, w, l2=L2):
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    res = minimize(_nll, np.zeros(Z.shape[1]), args=(Z, y, w, l2), jac=True, method="L-BFGS-B")
    beta = res.x
    p = 1 / (1 + np.exp(-(Z @ beta)))
    H = Z.T @ (Z * (w * p * (1 - p))[:, None])
    H[1:, 1:] += l2 * np.eye(len(beta) - 1)
    return dict(mu=mu, sd=sd, beta=beta, cov=np.linalg.inv(H))


def predict(m, X):
    Z = np.column_stack([np.ones(len(X)), (X - m["mu"]) / m["sd"]])
    return 1 / (1 + np.exp(-(Z @ m["beta"])))


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_platt(p, y) -> tuple[float, float]:
    """Recalibration logit(p_cal) = a + b * logit(p), fitted on held-out predictions."""
    X, yy, w = compress(logit(p)[:, None].round(4), y)
    m = fit_logistic(X, yy, w, l2=0.0)
    b = m["beta"][1] / m["sd"][0]
    return float(m["beta"][0] - b * m["mu"][0]), float(b)


def calibration_table(P, Y):
    bins = [0, .02, .05, .1, .2, .3, .45, .6, .8, 1.0001]
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        sel = (P >= lo) & (P < hi)
        if sel.any():
            out.append(dict(bin=f"{lo:.2f}-{min(hi, 1):.2f}", rows=int(sel.sum()),
                            mean_predicted=round(float(P[sel].mean()), 4), observed=round(float(Y[sel].mean()), 4)))
    return out


def weighted_auc(score, y, w):
    """Mann-Whitney AUC with weights; ties count half."""
    if y.min() == y.max():
        return None
    df = pd.DataFrame(dict(s=score, pos=w * y, neg=w * (1 - y))).groupby("s").sum().sort_index()
    neg_below = df.neg.cumsum() - df.neg
    num = (df.pos * (neg_below + 0.5 * df.neg)).sum()
    return float(num / (df.pos.sum() * df.neg.sum()))


def brier(p, y, w):
    return float(np.average((p - y) ** 2, weights=w))


# ------------------------------------------------------------------ data
def global_events(damage) -> tuple[dict[str, str], dict[str, int]]:
    recs = [dict(public_id=str(i), report_date=t.date().isoformat())
            for i, t in enumerate(damage.Report_Tim) if pd.notna(t)]
    ev = assign_events(recs)
    by_date = {r["report_date"]: ev[r["public_id"]] for r in recs}
    sizes = pd.Series(list(ev.values())).value_counts().to_dict()
    return by_date, {k: int(v) for k, v in sizes.items()}


def collect(ctx, events: list[str], by_date: dict[str, str]):
    """Per-premise features and an (n_premises x n_events) hit matrix over the whole territory."""
    ids = sorted(set(ctx.customer.circuit_id.dropna()))
    links = critical.link_facilities(critical.load_facilities(), ctx.transformer)
    rows, hits, skipped = [], [], 0
    for k, cid in enumerate(ids):
        try:
            net = CircuitNetwork(circuit_doc(cm.build_circuit_model(ctx, cid), cid, links))
        except Exception as e:  # a circuit that cannot be oriented is left out, and reported
            print(f"  {cid}: skipped ({type(e).__name__}: {e})")
            skipped += 1
            continue
        n0 = len(rows)
        for p in net.premises.values():
            inp = model_inputs(net, p)
            if inp is None:
                continue
            hit = event_hits(net, p, by_date)
            rows.append(dict(circuit=cid, **inp))
            hits.append([1 if e in hit else 0 for e in events])
        if k % 10 == 0:
            print(f"  [{k + 1}/{len(ids)}] {cid}: {len(rows) - n0} premises")
    return pd.DataFrame(rows), np.array(hits, dtype=np.int8), len(ids), skipped


def design(df, hist_rate, storm_size):
    cols = {
        "log_storm_size": np.log(np.full(len(df), float(storm_size))),
        "log_exposure_km": np.log1p(df.overhead_km.values),
        "hist_rate": hist_rate,
        "protect_depth": df.protect_depth.values.astype(float),
        "overhead_service": df.overhead_service.values,
    }
    return np.column_stack([cols[f] for f in rcfg.MODEL_FEATURES])


def stack(df, hits, events, sizes, keep: list[int]):
    """Rows = (premise, event in keep); history uses only the other kept events."""
    Xs, ys = [], []
    for k in keep:
        others = [j for j in keep if j != k]
        hr = hits[:, others].mean(1) if others else np.zeros(len(df))
        Xs.append(design(df, hr, sizes[events[k]]))
        ys.append(hits[:, k])
    return np.vstack(Xs), np.concatenate(ys).astype(float)


def compress(X, y):
    """Identical rows collapse to one weighted row (many premises share features)."""
    u, inv, cnt = np.unique(np.column_stack([X, y]), axis=0, return_inverse=True, return_counts=True)
    return u[:, :-1], u[:, -1], cnt.astype(float)


def heuristic(df, n_hist_events):
    exp = rcfg.EXPOSURE_MAX_POINTS * np.minimum(df.overhead_km.values / rcfg.EXPOSURE_SATURATION_KM, 1)
    hist = rcfg.HISTORY_MAX_POINTS * np.minimum(n_hist_events / rcfg.HISTORY_SATURATION_EVENTS, 1)
    svc = df.service_type.map(rcfg.SERVICE_POINTS).fillna(rcfg.SERVICE_POINTS["Unknown"]).values
    return exp + hist + svc


def validate(df, hits, events, sizes):
    """Leave one storm out: fit on the others, score the held-out storm."""
    per, P, Y, K = [], [], [], []
    for k, e in enumerate(events):
        train = [j for j in range(len(events)) if j != k]
        m = fit_logistic(*compress(*stack(df, hits, events, sizes, train)))
        Xs, ys = stack(df, hits, events, sizes, train)
        base = fit_logistic(*compress(Xs[:, [0]], ys))  # storm size only: everyone gets the same risk
        hist_train = hits[:, train]
        Xte = design(df, hist_train.mean(1), sizes[e])
        y = hits[:, k].astype(float)
        w = np.ones(len(y))
        p = predict(m, Xte)
        pb = predict(base, Xte[:, [0]])
        per.append(dict(event=e, size=sizes[e], observed_rate=round(float(y.mean()), 4),
                        predicted_rate=round(float(p.mean()), 4),
                        auc_within_storm=weighted_auc(p, y, w),
                        auc_heuristic_within_storm=weighted_auc(heuristic(df, hist_train.sum(1)), y, w),
                        brier=round(brier(p, y, w), 4), brier_storm_size_only=round(brier(pb, y, w), 4)))
        P.append(p)
        Y.append(y)
        K.append(np.full(len(y), k))
        print(f"  held out {e} (n={sizes[e]}): observed {y.mean():.3f}, predicted {p.mean():.3f}, "
              f"AUC {per[-1]['auc_within_storm']}, heuristic AUC {per[-1]['auc_heuristic_within_storm']}")
    P, Y, K = np.concatenate(P), np.concatenate(Y), np.concatenate(K)
    W = np.ones(len(P))
    # The raw model over-predicts above ~10% (driven by the largest storm). A two-parameter
    # recalibration fitted on the held-out predictions corrects the level; ranking is unchanged.
    a, b = fit_platt(P, Y)
    Pc = 1 / (1 + np.exp(-(a + b * logit(P))))
    for k, r in enumerate(per):
        r["predicted_rate_recalibrated"] = round(float(Pc[K == k].mean()), 4)
    # storm-to-storm variation the features cannot explain: logit gap between observed and
    # (recalibrated) predicted territory-wide rates in each held-out storm, weighted toward larger storms
    res = [logit(np.array(r["observed_rate"])) - logit(np.array(r["predicted_rate_recalibrated"])) for r in per]
    sigma = float(np.sqrt(np.average(np.square(res), weights=[np.sqrt(r["size"]) for r in per])))
    within = [r["auc_within_storm"] for r in per if r["auc_within_storm"] is not None]
    within_h = [r["auc_heuristic_within_storm"] for r in per if r["auc_heuristic_within_storm"] is not None]
    return dict(per_event=per, pooled_auc=weighted_auc(P, Y, W),
                mean_auc_within_storm=float(np.mean(within)),
                mean_auc_heuristic_within_storm=float(np.mean(within_h)),
                brier=brier(P, Y, W), brier_recalibrated=brier(Pc, Y, W),
                calibration=calibration_table(P, Y),
                calibration_recalibrated=calibration_table(Pc, Y),
                recalibration_note=("Recalibrated rows use two parameters fitted on these same held-out predictions, "
                                    "so that table is in-sample for those two parameters."),
                platt=dict(a=a, b=b), event_sigma=sigma)


def main() -> None:
    t0 = time.time()
    print("loading source layers ...")
    ctx = cm.load_context()
    by_date, sizes = global_events(read_layer("damage"))
    events = sorted(e for e, n in sizes.items() if n >= MIN_EVENT_SIZE)
    print(f"{len(events)} training storms (>= {MIN_EVENT_SIZE} records): "
          + ", ".join(f"{e} ({sizes[e]})" for e in events))
    print("collecting premise features on every circuit ...")
    df, hits, n_circuits, skipped = collect(ctx, events, by_date)
    print(f"{len(df)} premises on {n_circuits - skipped}/{n_circuits} circuits")
    if df.empty:
        raise SystemExit("no premises collected; nothing to fit")

    print("validating (leave one storm out) ...")
    val = validate(df, hits, events, sizes)
    print("fitting final model on all storms ...")
    m = fit_logistic(*compress(*stack(df, hits, events, sizes, list(range(len(events))))))
    coef = dict(zip(rcfg.MODEL_FEATURES, m["beta"][1:].round(4).tolist()))
    print("  coefficients (standardised):", coef)

    oh = np.sort(df.overhead_km.values)
    out = dict(
        generated=str(date.today()),
        label_definition=("A premise is 'hit' in a storm when at least one ARCOS damage record from that storm would "
                          "have interrupted it under the app's protection model. This is a damage-based proxy for an "
                          "outage, not a confirmed customer outage."),
        training=dict(premises=int(len(df)), circuits=n_circuits - skipped, circuits_skipped=skipped,
                      storms=len(events), min_event_size=MIN_EVENT_SIZE, l2=L2,
                      hit_rate_by_storm={e: round(float(hits[:, k].mean()), 4) for k, e in enumerate(events)}),
        features=rcfg.MODEL_FEATURES,
        mu=m["mu"].tolist(), sd=m["sd"].tolist(), intercept=float(m["beta"][0]), coef=m["beta"][1:].tolist(),
        cov=m["cov"].tolist(), event_sigma=val["event_sigma"], platt=val["platt"],
        events=events, event_sizes={e: sizes[e] for e in events}, date_to_event=by_date,
        validation={k: v for k, v in val.items() if k not in ("event_sigma", "platt")},
        exposure_km_percentiles=[round(float(np.quantile(oh, q / 100)), 3) for q in range(101)],
    )
    (PROCESSED / "risk_model.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"pooled AUC {val['pooled_auc']:.3f}; mean within-storm AUC {val['mean_auc_within_storm']:.3f} "
          f"(heuristic {val['mean_auc_heuristic_within_storm']:.3f}); event sigma {val['event_sigma']:.2f}")
    print(f"wrote {PROCESSED / 'risk_model.json'} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
