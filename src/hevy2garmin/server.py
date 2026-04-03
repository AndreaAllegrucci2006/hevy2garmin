"""FastAPI web dashboard for hevy2garmin."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader

from hevy2garmin import db
from hevy2garmin.config import is_configured, load_config, save_config
from hevy2garmin.sync import sync

logger = logging.getLogger("hevy2garmin")

TEMPLATES_DIR = Path(__file__).parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _render(template_name: str, **ctx) -> HTMLResponse:
    t = _jinja_env.get_template(template_name)
    return HTMLResponse(t.render(**ctx))


app = FastAPI(title="hevy2garmin", docs_url=None, redoc_url=None)


@app.middleware("http")
async def check_setup(request: Request, call_next):
    if not is_configured() and request.url.path not in ("/setup", "/favicon.ico"):
        return RedirectResponse("/setup")
    return await call_next(request)


# ── Pages ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    config = load_config()
    synced_count = db.get_synced_count()
    recent = db.get_recent_synced(5)
    hevy_total = 0
    matched_count = 0
    try:
        from hevy2garmin.hevy import HevyClient
        from hevy2garmin.garmin import get_client
        from hevy2garmin.matcher import fetch_garmin_activities, count_matched_workouts

        hevy = HevyClient(api_key=config.get("hevy_api_key"))
        hevy_total = hevy.get_workout_count()

        # Count how many Hevy workouts are already on Garmin
        if config.get("garmin_email"):
            try:
                garmin_client = get_client(config.get("garmin_email"))
                garmin_acts = fetch_garmin_activities(garmin_client, count=1000)
                hevy_sample = hevy.get_workouts(page=1, page_size=10).get("workouts", [])
                matched_count = count_matched_workouts(hevy_total, hevy_sample, garmin_acts)
            except Exception:
                pass
    except Exception:
        pass
    return _render(
        "dashboard.html",
        synced_count=synced_count,
        matched_count=matched_count,
        hevy_total=hevy_total,
        recent=recent,
    )


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    return _render("setup.html", config=load_config())


@app.post("/setup")
async def setup_save(
    hevy_api_key: str = Form(""),
    garmin_email: str = Form(""),
    garmin_password: str = Form(""),
    weight_kg: float = Form(80.0),
    birth_year: int = Form(1990),
    sex: str = Form("male"),
):
    config = load_config()
    if hevy_api_key:
        config["hevy_api_key"] = hevy_api_key
    if garmin_email:
        config["garmin_email"] = garmin_email
    config["user_profile"]["weight_kg"] = weight_kg
    config["user_profile"]["birth_year"] = birth_year
    config["user_profile"]["sex"] = sex
    save_config(config)
    if garmin_password and garmin_email:
        try:
            from garmin_auth import GarminAuth
            GarminAuth(email=garmin_email, password=garmin_password).login()
        except Exception as e:
            logger.warning("Garmin login test failed: %s", e)
    return RedirectResponse("/", status_code=303)


@app.get("/workouts", response_class=HTMLResponse)
async def workouts_page(request: Request):
    config = load_config()
    workouts = []
    try:
        from hevy2garmin.hevy import HevyClient
        from hevy2garmin.garmin import get_client
        from hevy2garmin.matcher import fetch_garmin_activities, match_workouts_to_garmin

        data = HevyClient(api_key=config.get("hevy_api_key")).get_workouts(page=1, page_size=10)
        workouts_raw = data.get("workouts", [])

        # Match against Garmin
        matches = {}
        if config.get("garmin_email"):
            try:
                garmin_client = get_client(config.get("garmin_email"))
                garmin_acts = fetch_garmin_activities(garmin_client, count=50)
                matches = match_workouts_to_garmin(workouts_raw, garmin_acts)
            except Exception:
                pass

        for w in workouts_raw:
            w["start_time"] = w.get("start_time") or w.get("startTime", "")
            w["end_time"] = w.get("end_time") or w.get("endTime", "")
            if db.is_synced(w["id"]):
                w["status"] = "uploaded"  # we uploaded it
            elif w["id"] in matches:
                w["status"] = "matched"   # already on Garmin (not by us)
                w["garmin_match"] = matches[w["id"]]
            else:
                w["status"] = "pending"   # not on Garmin
        workouts = workouts_raw
    except Exception as e:
        logger.error("Failed to fetch workouts: %s", e)
    return _render("workouts.html", workouts=workouts)


@app.get("/mappings", response_class=HTMLResponse)
async def mappings_page(request: Request):
    from hevy2garmin.mapper import HEVY_TO_GARMIN, _custom_mappings, _ensure_custom_loaded

    _ensure_custom_loaded()

    CAT_NAMES = {
        0: "Bench Press", 1: "Calf Raise", 2: "Cardio", 3: "Carry", 4: "Chop",
        5: "Core", 6: "Crunch", 7: "Curl", 8: "Deadlift", 9: "Flye",
        10: "Hip Raise", 11: "Hip Stability", 12: "Hip Swing", 13: "Hyperextension",
        14: "Lateral Raise", 15: "Leg Curl", 16: "Leg Raise", 17: "Lunge",
        18: "Olympic Lift", 19: "Plank", 20: "Plyo", 21: "Pull Up", 22: "Push Up",
        23: "Row", 24: "Shoulder Press", 25: "Shoulder Stability", 26: "Shrug",
        27: "Sit Up", 28: "Squat", 29: "Total Body", 30: "Triceps Extension",
        31: "Warm Up", 32: "Run", 42: "Indoor Row", 65534: "Unknown",
    }

    mappings = []
    for name, (cat, subcat) in sorted(HEVY_TO_GARMIN.items()):
        cat_name = CAT_NAMES.get(cat, f"Category {cat}")
        mappings.append((name, cat, subcat, cat_name))
    for name, (cat, subcat) in sorted(_custom_mappings.items()):
        cat_name = CAT_NAMES.get(cat, f"Category {cat}")
        mappings.append((name, cat, subcat, f"{cat_name} (custom)"))

    return _render(
        "mappings.html",
        mappings=mappings,
        total=len(mappings),
        custom_count=len(_custom_mappings),
    )


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    return _render("history.html", total=db.get_synced_count(), history=db.get_recent_synced(50))


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    config = load_config()
    unmapped: dict[str, int] = {}
    try:
        from hevy2garmin.hevy import HevyClient
        from hevy2garmin.mapper import lookup_exercise
        data = HevyClient(api_key=config.get("hevy_api_key")).get_workouts(page=1, page_size=10)
        for w in data.get("workouts", []):
            for ex in w.get("exercises", []):
                name = ex.get("title") or ex.get("name", "")
                if lookup_exercise(name)[0] == 65534:
                    unmapped[name] = unmapped.get(name, 0) + 1
    except Exception:
        pass
    return _render("settings.html", config=config, unmapped=sorted(unmapped.items(), key=lambda x: -x[1]))


@app.post("/settings")
async def settings_save(
    hevy_api_key: str = Form(""), garmin_email: str = Form(""), garmin_password: str = Form(""),
    weight_kg: float = Form(80.0), birth_year: int = Form(1990), sex: str = Form("male"),
    working_set_seconds: int = Form(40), warmup_set_seconds: int = Form(25),
    rest_between_sets_seconds: int = Form(75), rest_between_exercises_seconds: int = Form(120),
):
    config = load_config()
    if hevy_api_key:
        config["hevy_api_key"] = hevy_api_key
    if garmin_email:
        config["garmin_email"] = garmin_email
    config["user_profile"].update(weight_kg=weight_kg, birth_year=birth_year, sex=sex)
    config["timing"].update(
        working_set_seconds=working_set_seconds, warmup_set_seconds=warmup_set_seconds,
        rest_between_sets_seconds=rest_between_sets_seconds,
        rest_between_exercises_seconds=rest_between_exercises_seconds,
    )
    save_config(config)
    return RedirectResponse("/settings", status_code=303)


# ── API (HTMX) ──────────────────────────────────────────────────────────────

@app.post("/api/sync", response_class=HTMLResponse)
async def api_sync(request: Request):
    try:
        result = sync(limit=10, dry_run=False)
    except Exception as e:
        result = {"synced": 0, "skipped": 0, "failed": 1, "unmapped": [], "error": str(e)}
    return _render("partials/sync_result.html", result=result)


@app.post("/api/sync/{workout_id}", response_class=HTMLResponse)
async def api_sync_single(request: Request, workout_id: str):
    try:
        from hevy2garmin.hevy import HevyClient
        from hevy2garmin.fit import generate_fit
        from hevy2garmin.garmin import get_client, rename_activity, set_description, upload_fit, generate_description
        import tempfile

        config = load_config()
        data = HevyClient(api_key=config.get("hevy_api_key")).get_workouts(page=1, page_size=10)
        workout = next((w for w in data.get("workouts", []) if w["id"] == workout_id), None)
        if not workout:
            return HTMLResponse('<td colspan="5">Workout not found</td>')

        with tempfile.TemporaryDirectory() as tmp:
            fit_path = f"{tmp}/{workout_id}.fit"
            result = generate_fit(workout, hr_samples=None, output_path=fit_path)
            garmin_client = get_client(config.get("garmin_email"))
            upload_result = upload_fit(garmin_client, fit_path, workout_start=workout.get("start_time"))
            aid = upload_result.get("activity_id")
            if aid:
                rename_activity(garmin_client, aid, workout["title"])
                set_description(garmin_client, aid, generate_description(workout, calories=result.get("calories"), avg_hr=result.get("avg_hr")))
            db.mark_synced(hevy_id=workout_id, garmin_activity_id=str(aid) if aid else None, title=workout["title"], calories=result.get("calories"), avg_hr=result.get("avg_hr"))

        start = (workout.get("start_time") or "")[:16]
        return HTMLResponse(f'<tr><td><span class="badge badge-success">✓ Synced</span></td><td>{start}</td><td><strong>{workout["title"]}</strong></td><td>{len(workout.get("exercises", []))}</td><td></td></tr>')
    except Exception as e:
        return HTMLResponse(f'<td colspan="5" style="color: var(--pico-del-color);">Failed: {e}</td>')


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn
    logging.basicConfig(format="%(message)s", level=logging.INFO, force=True)
    logger.info("Starting hevy2garmin dashboard at http://localhost:%d", port)
    uvicorn.run(app, host=host, port=port, log_level="warning")
