"""Landslide AI backend (FastAPI).
Run:  uvicorn app:app --reload --port 8000
"""
import base64, io, json, math, os, sqlite3, time
import cv2
import numpy as np
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

WEIGHTS = os.path.join(os.path.dirname(__file__), "weights", "unet.pth")
DB = os.path.join(os.path.dirname(__file__), "reports.db")
SIZE = 512

app = FastAPI(title="Landslide AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- optional trained model (see train.py) ----------
_model = None
def load_model():
    global _model
    if _model is not None or not os.path.exists(WEIGHTS):
        return _model
    import torch, segmentation_models_pytorch as smp
    m = smp.Unet("resnet34", encoder_weights=None, in_channels=3, classes=1)
    m.load_state_dict(torch.load(WEIGHTS, map_location="cpu"))
    _model = m.eval()
    return _model

def segment(img_bgr):
    """Returns (binary mask uint8 0/1, engine name)."""
    model = load_model()
    if model is not None:
        import torch
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        rgb = (rgb - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
        x = torch.from_numpy(rgb.transpose(2, 0, 1)).float().unsqueeze(0)
        with torch.no_grad():
            p = torch.sigmoid(model(x))[0, 0].numpy()
        return (p > 0.5).astype(np.uint8), "U-Net (trained)"
    # Fallback: classical computer-vision heuristic so the demo works without weights
    b, g, r = [c.astype(np.float32) / 255 for c in cv2.split(img_bgr)]
    exg = 2 * g - r - b                                   # excess-green vegetation index
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    soil = (hsv[..., 0] < 35) & (hsv[..., 1] > 30) & (hsv[..., 2] > 50) & (exg < 0.05)
    mask = soil.astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_OPEN, k), cv2.MORPH_CLOSE, k)
    return mask, "Colour/texture heuristic (no trained weights)"

def vegetation_pct(img_bgr):
    b, g, r = [c.astype(np.float32) / 255 for c in cv2.split(img_bgr)]
    return float(((2 * g - r - b) > 0.08).mean() * 100)

def sigmoid(z): return 1 / (1 + math.exp(-z))

def level(score):
    return "Low" if score < 25 else "Moderate" if score < 50 else "High" if score < 75 else "Critical"

def analyse(img_bgr, lat=None, lon=None, rain=None, slope=None, footprint_m=500):
    img = cv2.resize(img_bgr, (SIZE, SIZE))
    mask, engine = segment(img)

    # remove tiny blobs
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    clean = np.zeros_like(mask)
    regions = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] > 0.002 * SIZE * SIZE:
            clean[lab == i] = 1
            regions.append(int(stats[i, cv2.CC_STAT_AREA]))
    mask = clean

    # ---- 1. DETECTION ----
    area_pct = float(mask.mean() * 100)
    veg = vegetation_pct(img)
    edges = cv2.Canny(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 80, 160)
    crack = float((edges[mask > 0] > 0).mean()) if mask.any() else 0.0   # crack/scar density
    detected = area_pct >= 3.0
    confidence = round(min(0.99, 0.5 + area_pct / 60 + crack / 2), 2) if detected else round(max(0.5, 0.95 - area_pct / 10), 2)

    # ---- 2. SEVERITY ----
    sev_score = min(100, area_pct * 1.4 + crack * 60 + min(len(regions), 5) * 3 + max(0, 40 - veg) * 0.5)
    severity = level(sev_score) if detected else "None"

    # ---- 3. PREDICTION (future occurrence / reactivation likelihood) ----
    z = (-3.2 + 0.05 * area_pct + 0.03 * (100 - veg) + 2.5 * crack
         + 0.012 * (rain or 0) + 0.045 * (slope or 20))
    prob = round(sigmoid(z), 3)

    # ---- 4. RISK MAP (8x8 grid + heatmap overlay) ----
    g = 8
    cell = SIZE // g
    risk_grid = []
    for i in range(g):
        row = []
        for j in range(g):
            sl = (slice(i * cell, (i + 1) * cell), slice(j * cell, (j + 1) * cell))
            m = mask[sl].mean()
            bare = 1 - np.clip(vegetation_pct(img[sl]) / 100, 0, 1)
            e = (edges[sl] > 0).mean()
            row.append(round(float(np.clip(0.6 * m + 0.25 * bare + 0.15 * e * 4, 0, 1)), 3))
        risk_grid.append(row)
    heat = cv2.resize(np.array(risk_grid, np.float32), (SIZE, SIZE), interpolation=cv2.INTER_CUBIC)
    heat = cv2.applyColorMap((np.clip(heat, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(img, 0.55, heat, 0.45, 0)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay, cnts, -1, (255, 255, 255), 2)

    geo = None
    if lat is not None and lon is not None:
        dlat = footprint_m / 111_320 / g
        dlon = footprint_m / (111_320 * math.cos(math.radians(lat))) / g
        feats = []
        for i in range(g):
            for j in range(g):
                la0 = lat + (g / 2 - i) * dlat; lo0 = lon + (j - g / 2) * dlon
                feats.append({"type": "Feature", "properties": {"risk": risk_grid[i][j]},
                              "geometry": {"type": "Polygon", "coordinates": [[
                                  [lo0, la0], [lo0 + dlon, la0], [lo0 + dlon, la0 - dlat], [lo0, la0 - dlat], [lo0, la0]]]}})
        geo = {"type": "FeatureCollection", "features": feats}

    def b64(a):
        return "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", a)[1]).decode()

    overall = max(sev_score if detected else 0, prob * 100)
    return {
        "engine": engine,
        "detection": {"detected": detected, "confidence": confidence, "affected_area_pct": round(area_pct, 1),
                      "regions": len(regions), "vegetation_pct": round(veg, 1)},
        "severity": {"level": severity, "score": round(sev_score, 1)},
        "prediction": {"probability": prob, "level": level(prob * 100),
                       "inputs": {"rainfall_mm": rain, "slope_deg": slope}},
        "risk_map": {"overall_level": level(overall), "overall_score": round(overall, 1),
                     "grid": risk_grid, "heatmap": b64(overlay), "mask": b64(mask * 255), "geojson": geo},
        "location": {"lat": lat, "lon": lon},
    }

# ---------- API ----------
@app.post("/api/analyze")
async def analyze(image: UploadFile = File(...), lat: float | None = Form(None), lon: float | None = Form(None),
                  rainfall_mm: float | None = Form(None), slope_deg: float | None = Form(None)):
    data = await image.read()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not read the file as an image. Upload a JPG or PNG.")
    res = analyse(img, lat, lon, rainfall_mm, slope_deg)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, ts REAL, lat REAL, lon REAL, level TEXT, score REAL, area REAL)")
    con.execute("INSERT INTO reports(ts,lat,lon,level,score,area) VALUES(?,?,?,?,?,?)",
                (time.time(), lat, lon, res["risk_map"]["overall_level"], res["risk_map"]["overall_score"],
                 res["detection"]["affected_area_pct"]))
    con.commit(); con.close()
    return res

@app.get("/api/reports")
def reports():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, ts REAL, lat REAL, lon REAL, level TEXT, score REAL, area REAL)")
    rows = con.execute("SELECT ts,lat,lon,level,score,area FROM reports WHERE lat IS NOT NULL ORDER BY ts DESC LIMIT 200").fetchall()
    con.close()
    return [dict(zip(["ts", "lat", "lon", "level", "score", "area"], r)) for r in rows]

class Chat(BaseModel):
    message: str
    context: dict | None = None

ADVICE = {
    "Low": "Monitor the slope after heavy rain and keep drainage channels clear.",
    "Moderate": "Inspect the slope for new cracks, avoid building at the toe, and improve surface drainage.",
    "High": "Restrict access below the slope, install monitoring (crack gauges), and alert local authorities.",
    "Critical": "Evacuate people below the slope now, close nearby roads, and contact disaster management authorities.",
}

@app.post("/api/chat")
def chat(q: Chat):
    m, c = q.message.lower(), q.context
    if any(w in m for w in ["hello", "hi ", "hey"]) or m.strip() in ("hi", "hello"):
        return {"reply": "Hi! Upload a slope photo, then ask me about the result, severity, prediction, or what to do."}
    if not c:
        if "what is" in m or "landslide" in m:
            return {"reply": "A landslide is the downslope movement of rock, soil or debris, usually triggered by heavy rain, earthquakes, steep slopes, or vegetation loss. Upload a photo and I'll analyse it."}
        return {"reply": "I don't have an analysis yet. Upload an image first, then ask me about it."}
    d, s, p, r = c["detection"], c["severity"], c["prediction"], c["risk_map"]
    if "severity" in m:
        return {"reply": f"Severity is {s['level']} (score {s['score']}/100), based on affected area ({d['affected_area_pct']}%), scar texture, number of regions and vegetation loss."}
    if "predict" in m or "probab" in m or "future" in m or "likely" in m:
        return {"reply": f"Estimated landslide likelihood is {round(p['probability']*100)}% ({p['level']}). Adding rainfall and slope angle on the upload form makes this estimate more reliable."}
    if "detect" in m or "found" in m or "area" in m:
        t = "A landslide was detected" if d["detected"] else "No clear landslide was detected"
        return {"reply": f"{t}: {d['affected_area_pct']}% of the frame is affected across {d['regions']} region(s). Vegetation cover is {d['vegetation_pct']}%."}
    if "do" in m or "safe" in m or "advice" in m or "recommend" in m:
        return {"reply": f"Overall risk is {r['overall_level']}. {ADVICE[r['overall_level']]}"}
    if "map" in m or "risk" in m:
        return {"reply": f"Overall risk is {r['overall_level']} ({r['overall_score']}/100). The heatmap shows red/yellow cells where bare soil, scars and cracks are concentrated."}
    return {"reply": f"Summary: detection={'yes' if d['detected'] else 'no'}, severity={s['level']}, likelihood={round(p['probability']*100)}%, overall risk={r['overall_level']}. Ask about severity, prediction, the map, or what to do."}

# serve the website (fallback to the project root so the local demo still works)
static_dir = os.path.join(os.path.dirname(__file__), "frontend")
if not os.path.isdir(static_dir):
    static_dir = os.path.dirname(__file__)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
