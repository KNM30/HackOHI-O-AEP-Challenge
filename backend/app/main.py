from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import assistant, briefing, data_store, restoration, risk, risk_config, scenarios, schemas
from .config import CORS_ORIGINS
from .context import circuit_map, premise_context, supply_path

app = FastAPI(title="AI Outage Concierge (prototype)", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])


def _net(circuit_id: str):
    try:
        return data_store.circuit(circuit_id)
    except KeyError:
        raise HTTPException(404, f"circuit {circuit_id} is not in the processed subset")
    except data_store.DataNotBuilt as e:
        raise HTTPException(503, str(e))


@app.get("/api/health")
def health():
    try:
        circuits = [c["circuit_id"] for c in data_store.index()["circuits"]]
        return {"status": "ok", "circuits": circuits}
    except data_store.DataNotBuilt as e:
        return {"status": "data_not_built", "detail": str(e)}


@app.get("/api/circuits", response_model=list[schemas.CircuitSummary])
def circuits():
    try:
        return data_store.index()["circuits"]
    except data_store.DataNotBuilt as e:
        raise HTTPException(503, str(e))


@app.get("/api/circuits/{circuit_id}/premises", response_model=list[schemas.PremiseListItem])
def premises(circuit_id: str, q: str | None = Query(None, max_length=20), limit: int = Query(2000, le=5000)):
    net = _net(circuit_id)
    items = [schemas.PremiseListItem(id=p["public_id"], service_type=p["service_type"],
                                     transformer_id=p["transformer_id"]) for p in net.premises.values()]
    if q:
        items = [i for i in items if q.upper() in i.id]
    return sorted(items, key=lambda i: i.id)[:limit]


@app.get("/api/circuits/{circuit_id}/map", response_model=schemas.CircuitMap)
def map_layers(circuit_id: str):
    net = _net(circuit_id)
    return circuit_map(net, data_store.lines_geojson(circuit_id))


def _premise(premise_id: str):
    try:
        found = data_store.find_premise(premise_id)
    except data_store.DataNotBuilt as e:
        raise HTTPException(503, str(e))
    if found is None:
        raise HTTPException(404, "unknown premise id")
    return found


@app.get("/api/premises/{premise_id}", response_model=schemas.PremiseContext)
def premise(premise_id: str):
    net, p = _premise(premise_id)
    return premise_context(net, p)


@app.get("/api/premises/{premise_id}/risk", response_model=schemas.RiskResult)
def premise_risk(premise_id: str, severity: str = Query(risk_config.DEFAULT_SEVERITY, max_length=20)):
    if severity not in risk_config.SEVERITY:
        raise HTTPException(422, f"severity must be one of {', '.join(risk_config.SEVERITY)}")
    net, p = _premise(premise_id)
    path = supply_path(net, p.get("transformer_node"))
    return risk.assess(net, p, severity, path.approximated_gaps if path else 0)


@app.post("/api/circuits/{circuit_id}/simulation", response_model=schemas.SimulationResult)
def simulation(circuit_id: str, req: schemas.SimulationRequest):
    """Evaluate one fixed scenario (a set of damage locations) for a premise.

    The job set and schedule depend only on the locations and crew inputs, so every
    premise evaluated against the same request body sees the same repairs.
    """
    net = _net(circuit_id)
    p = net.premises.get(req.premise_id)
    if p is None:
        raise HTTPException(404, "premise is not on this circuit")
    try:
        scen = scenarios.resolve_fixed(net, req.scenario_id, req.scenario_label, req.location_ids)
        labor_ref = data_store.labor_reference()
    except LookupError as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except data_store.DataNotBuilt as e:
        raise HTTPException(503, str(e))
    impact = scenarios.evaluate(net, p, scen, scen.locations)
    params = restoration.CrewParams(**req.crew.model_dump())
    return schemas.SimulationResult(impact=impact,
                                    restoration=restoration.simulate(net, p, scen, params, labor_ref, impact))


@app.get("/api/premises/{premise_id}/scenarios", response_model=schemas.ScenarioCatalog)
def premise_scenarios(premise_id: str):
    net, p = _premise(premise_id)
    return scenarios.scenario_catalog_response(net, p)


@app.post("/api/premises/{premise_id}/scenario", response_model=schemas.ScenarioResult)
def premise_scenario(premise_id: str, req: schemas.ScenarioRequest):
    net, p = _premise(premise_id)
    try:
        return scenarios.run(net, p, req.scenario_id, req.location_ids)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    except (LookupError, ValueError) as e:
        raise HTTPException(422, str(e))


# ---------------------------------------------------------------- Milestone 4
@app.post("/api/briefing", response_model=schemas.BriefingResponse)
def briefing_endpoint(req: schemas.BriefingRequest):
    """Guidance and alert previews for the premise, recomputed from the request inputs."""
    try:
        return briefing.response(briefing.compute(req))
    except briefing.BriefingError as e:
        raise HTTPException(e.status, e.detail)


@app.post("/api/assistant", response_model=schemas.AssistantResponse)
def assistant_endpoint(req: schemas.AssistantRequest):
    """Grounded Q&A over a sanitized snapshot of the same computation."""
    try:
        b = briefing.compute(req.briefing)
    except briefing.BriefingError as e:
        raise HTTPException(e.status, e.detail)
    return assistant.answer(b, req)
