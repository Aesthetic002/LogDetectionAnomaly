"""LogPulse dashboard (note 13). Live mode for the projector, Investigate mode for drill-down.

    streamlit run dashboard/app.py          (API_URL defaults to http://localhost:9000)

Everything is read from the detector API, so a recorded run can be replayed by picking it
in the sidebar ("Live but reproducible").
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

API = os.environ.get("API_URL", "http://localhost:9000")
ROOT = Path(os.environ.get("LOGPULSE_ROOT", Path(__file__).resolve().parents[1]))
SERVICE_COLOR = {"gateway": "#2a78d6", "orders": "#eb6834", "inventory": "#1baf7a", "payment": "#eda100",
                 "db": "#898781", "fluent-bit": "#898781"}
STATUS = {"green": "#0ca30c", "amber": "#fab219", "red": "#d03b3b", "grey": "#898781"}
STATUS_LABEL = {"green": "● healthy", "amber": "▲ suspicious", "red": "■ alerting", "grey": "infra"}
DETECTOR_LABEL = {"B1_keyword": "Keyword alert", "B2_error_rate": "Error-rate threshold", "B3_health": "Health check",
                  "rf": "Random Forest", "deeplog_vanilla": "Vanilla DeepLog", "deeplog_matcher": "+ matcher",
                  "deeplog_topp": "+ top-p", "deeplog_both": "+ matcher + top-p",
                  "deeplog_full": "Our model (step-wise)"}
POS = {"gateway": (0, 1), "orders": (1, 1), "inventory": (2, 1.6), "payment": (2, 0.4), "db": (3, 1.6),
       "fluent-bit": (0.5, -0.1)}

st.set_page_config(page_title="LogPulse", layout="wide", page_icon="📈")
st.markdown("""<style>
.chip{display:inline-block;padding:1px 6px;margin:1px;border-radius:4px;font:12px ui-monospace,monospace;
      border:1px solid rgba(0,0,0,.12)}
.chip.unseen{border:1px dashed #d03b3b}.chip.bad{outline:2px solid #d03b3b}
.logline{font:12px ui-monospace,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card{border:1px solid rgba(128,128,128,.35);border-radius:8px;padding:8px 10px;margin-bottom:8px;
      font:12.5px ui-monospace,monospace}
.lit{border-radius:6px;padding:6px;text-align:center;font-size:13px;margin:2px}
</style>""", unsafe_allow_html=True)


def get(path, **params):
    try:
        r = httpx.get(f"{API}{path}", params={k: v for k, v in params.items() if v is not None}, timeout=10)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        st.error(f"API {path}: {e}")
        return None


def post(path, **kw):
    try:
        return httpx.post(f"{API}{path}", timeout=60, **kw).json()
    except httpx.HTTPError as e:
        st.error(f"API {path}: {e}")


def chip(eid, service, tooltip="", unseen=False, bad=False):
    c = SERVICE_COLOR.get(service, "#c3c2b7")
    cls = "chip" + (" unseen" if unseen else "") + (" bad" if bad else "")
    return f'<span class="{cls}" style="background:{c}33" title="{tooltip}">E{eid}</span>'


# ------------------------------------------------------------------ sidebar
st.sidebar.title("LogPulse")
runs = get("/api/runs") or []
status = get("/api/status") or {}
live_run = status.get("run")
choice = st.sidebar.selectbox("Run", ["● live"] + [r for r in runs if r != live_run],
                              help="Pick a recorded run to replay it")
RUN = None if choice == "● live" else choice
st.sidebar.caption(f"live run: `{live_run}` · mode `{status.get('mode')}` · model `{(status.get('version') or {}).get('model')}`")
refresh = st.sidebar.slider("Refresh (s)", 1, 10, 2)
templates = {t["event_id"]: t for t in (get("/api/templates", run=RUN) or [])}

tab_live, tab_inv, tab_flow, tab_tpl, tab_inc, tab_bench = st.tabs(
    ["Live", "Investigate", "Normal flow graph", "Template library", "Incidents", "Benchmarks"])


# ------------------------------------------------------------------ panel 1 topology
def topology(svc):
    fig = go.Figure()
    nodes = {n["id"]: n for n in svc["nodes"]}
    for e in svc["edges"]:
        (x0, y0), (x1, y1) = POS[e["source"]], POS[e["target"]]
        w = 1.5 + min((e["req_per_s"] or 0) / 4, 6)
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", hoverinfo="text",
                                 text=f"{e['source']} → {e['target']}: {e['req_per_s']} req/s",
                                 line={"width": w, "color": "#d03b3b" if e["anomalous"] else "#c3c2b7"}))
    xs, ys, colors, text, hover = [], [], [], [], []
    for nid, n in nodes.items():
        x, y = POS[nid]
        xs.append(x)
        ys.append(y)
        colors.append(STATUS[n["color"]])
        text.append(f"<b>{nid}</b><br>{n['lines_per_s']} lines/s" + ("" if n["infra"] else f"<br>{n['anomalous_per_min']} anom/min"))
        hover.append(f"{nid}: {STATUS_LABEL[n['color']]} · health {n['health']}")
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", text=text, textposition="bottom center",
                             hovertext=hover, hoverinfo="text",
                             marker={"size": 34, "color": colors, "line": {"width": 2, "color": "white"},
                                     "symbol": ["square" if nodes[n]["infra"] else "circle" for n in nodes]}))
    fig.update_layout(showlegend=False, height=330, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(visible=False, range=[-0.4, 3.4]), yaxis=dict(visible=False, range=[-0.6, 2.1]))
    return fig


# ------------------------------------------------------------------ live tab
with tab_live:
    @st.fragment(run_every=refresh)
    def live_panels():
        svc = get("/api/services", run=RUN)
        board = get("/api/scoreboard", run=RUN) or {}
        top_l, top_r = st.columns([3, 2])
        with top_l:
            st.subheader("1 · Live topology")
            if svc:
                st.plotly_chart(topology(svc), width="stretch", key="topo")
                st.caption(" · ".join(f"{STATUS_LABEL[k]}" for k in ("green", "amber", "red")) +
                           " — colour from the step-wise model's alerts in the last 30 s and B3 health")
        with top_r:
            st.subheader("8 · Scoreboard")
            lit = board.get("lit", {})
            cols = st.columns(3)
            for c, d in zip(cols, ["B1_keyword", "B2_error_rate", "deeplog_full"]):
                on = lit.get(d)
                c.markdown(f'<div class="lit" style="background:{"#d03b3b" if on else "rgba(128,128,128,.15)"};'
                           f'color:{"white" if on else "inherit"}">{"🔔 " if on else ""}{DETECTOR_LABEL[d]}</div>',
                           unsafe_allow_html=True)
            rows = []
            for d, v in (board.get("detectors") or {}).items():
                rows.append({"detector": DETECTOR_LABEL.get(d, d), "faults detected": v["faults_detected"],
                             "missed": v["faults_missed"], "TP alerts": v["tp_alerts"], "FP (debounced)": v["fp_alerts"],
                             "median TTD s": None if v["mttd"] is None else round(v["mttd"], 1),
                             "FA / h": None if v["fa_per_h"] is None else round(v["fa_per_h"], 1)})
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=300)
            c = board.get("counts", {})
            st.caption(f"F7 deploy check — alerts so far: vanilla DeepLog **{c.get('deeplog_vanilla', 0)}** · "
                       f"ours **{c.get('deeplog_full', 0)}**")

        mid_l, mid_r = st.columns([3, 2])
        with mid_l:
            st.subheader("2 · Log wall → event chips")
            s = get("/api/stream", run=RUN, limit=40) or {"lines": []}
            st.caption(f"raw lines last minute: **{s.get('lines_last_min', 0):,}** · distinct events: "
                       f"**{s.get('distinct_events_last_min', 0)}**")
            a, b = st.columns([3, 1])
            html_l, html_r = [], []
            for ln in s["lines"][-22:]:
                col = "#d03b3b" if ln["level"] == "ERROR" else SERVICE_COLOR.get(ln["service"], "inherit")
                html_l.append(f'<div class="logline"><span style="color:{col}">[{ln["service"]}]</span> '
                              f'{ln["level"][:4]} {ln["trace_id"][:6]} {ln["msg"]}</div>')
                html_r.append(chip(ln["event_id"], ln["service"], ln["template"], ln["unseen"]))
            a.markdown("".join(html_l), unsafe_allow_html=True)
            b.markdown("<br>".join(html_r), unsafe_allow_html=True)
        with mid_r:
            st.subheader("6 · Alerts")
            alerts = get("/api/alerts", run=RUN, limit=6, detector="deeplog_full") or []
            for al in alerts:
                exp = json.loads(al["expected"]) if al.get("expected") else []
                exp_txt = "<br>".join(f"&nbsp;&nbsp;E{e} {t[:46]} p={p:.2f}" for e, p, t in exp[:3])
                verdict = {"TP": "✅ TRUE POSITIVE", "FP": "❌ FALSE POSITIVE", "?": "… in fault window"}[al["verdict"]]
                ttd = f" (fault start +{al['ts'] - al['fault_start']:.1f} s)" if al.get("fault_start") else ""
                st.markdown(
                    f'<div class="card"><b>ALERT</b> · trace {al["trace_id"]} · {al["service"]} · step {al["step"]}{ttd}<br>'
                    f'expected:<br>{exp_txt}<br>observed: E{al["observed"]} {str(al["observed_template"])[:50]} '
                    f'p={al["p_observed"] or 0:.3f}<br><i>{al["reason"]}</i><br>{verdict}</div>',
                    unsafe_allow_html=True)

        low_l, low_r = st.columns([3, 2])
        with low_l:
            st.subheader("3 · Untangling view")
            tr = get("/api/traces", run=RUN, seconds=20, limit=14) or {"traces": [], "interleaved": []}
            st.caption("as it arrives (interleaved):")
            st.markdown("".join(chip(e["event_id"], e["service"]) for e in tr["interleaved"][-45:]), unsafe_allow_html=True)
            st.caption("one lane per trace_id:")
            lanes = []
            for t in tr["traces"]:
                chips = "".join(chip(e, s, templates.get(e, {}).get("template", ""), bad=(t["bad_step"] == i))
                                for i, (e, s) in enumerate(zip(t["events"], t["services"])))
                flag = "🟥" if t["anomalous"] else "▫️"
                lanes.append(f'<div>{flag} <code>{t["trace_id"]}</code> {chips}</div>')
            st.markdown("".join(lanes), unsafe_allow_html=True)
        with low_r:
            st.subheader("7 · Fault control")
            if RUN:
                st.info("Replaying a recorded run — fault buttons act on the live system only.")
            faults = get("/api/faults")
            active = {f["fault_id"].split("-")[0] for f in (faults or {}).get("active", [])}
            cat = (faults or {}).get("catalogue", {})
            grid = st.columns(2)
            for i, (fid, f) in enumerate(cat.items()):
                lab = f"{'⏹ ' if fid in active else ''}{fid} · {f['label']}"
                if grid[i % 2].button(lab, key=f"btn{fid}", width="stretch"):
                    post(f"/api/faults/{fid}/end" if fid in active else f"/api/faults/{fid}",
                         params={} if fid in active or fid == "F7" else {"duration": 90})
            if st.button("Restore all", width="stretch"):
                post("/api/faults/restore")
            st.caption("Each fault is applied by the injector, which records it in the ground truth "
                       "(auto-restores after 90 s; F7 stays until pressed again).")

    live_panels()


# ------------------------------------------------------------------ investigate
with tab_inv:
    st.subheader("Investigate an alert")
    al = get("/api/alerts", run=RUN, limit=200) or []
    det = st.selectbox("Detector", list(DETECTOR_LABEL), index=list(DETECTOR_LABEL).index("deeplog_full"),
                       format_func=lambda d: DETECTOR_LABEL[d])
    opts = sorted([a for a in al if a["detector"] == det and a.get("trace_id")],
                  key=lambda a: {"TP": 0, "?": 1, "FP": 2}[a["verdict"]])  # true positives first
    pick = st.selectbox("Alert", opts, format_func=lambda a: f"{a['verdict']} · {a['trace_id']} · {a['service']} · "
                                                                f"{str(a['observed_template'])[:50]}") if opts else None
    tid = st.text_input("…or a trace id", value=pick["trace_id"] if pick else "")
    if tid:
        t = get(f"/api/traces/{tid}", run=RUN)
        if t and t["events"]:
            alerts_t = [a for a in t["alerts"] if a["detector"] == det]
            bad = alerts_t[0]["step"] if alerts_t else None
            st.markdown("**1 · Sequence**")
            st.markdown("".join(chip(e["event_id"], e["service"], e["template"], bool(e["unseen"]), i == bad)
                                for i, e in enumerate(t["events"])), unsafe_allow_html=True)
            decs = pd.DataFrame(t["decisions"])
            c1, c2 = st.columns(2)
            if len(decs):
                with c1:
                    st.markdown("**2 · Predicted distribution at the bad step**")
                    row = decs[decs["step"] == bad] if bad is not None and (decs["step"] == bad).any() else decs.iloc[[-1]]
                    r = row.iloc[0]
                    top = json.loads(r["top5"])
                    obs = int(r["event_id"])
                    labels = [f"E{e}" for e, _ in top] + ([f"E{obs} (observed)"] if obs not in [e for e, _ in top] else [])
                    vals = [p for _, p in top] + ([r["p_actual"]] if obs not in [e for e, _ in top] else [])
                    colors = ["#2a78d6" if i < r["allowed_k"] else "#c3c2b7" for i in range(len(top))] + \
                             (["#d03b3b"] if len(vals) > len(top) else [])
                    fig = go.Figure(go.Bar(x=labels, y=vals, marker_color=colors,
                                           hovertext=[templates.get(int(lb[1:].split()[0]), {}).get("template", "")
                                                      for lb in labels]))
                    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="p")
                    st.plotly_chart(fig, width="stretch")
                    st.caption(f"blue = allowed set (k={r['allowed_k']}), red = observed outside it")
                with c2:
                    st.markdown("**3 · Per-step surprise  −log p(actual)**")
                    s = -decs["p_actual"].clip(lower=1e-12).map(math.log)
                    fig = go.Figure(go.Scatter(x=decs["step"], y=s, mode="lines+markers", line={"color": "#2a78d6"}))
                    if bad is not None:
                        fig.add_vline(x=bad, line_color="#d03b3b", line_dash="dash")
                    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="step")
                    st.plotly_chart(fig, width="stretch")
            st.markdown("**4 · Raw evidence**")
            ev = pd.DataFrame(t["events"])[["container", "line_no", "ts", "level", "event_id", "msg"]]
            ev["ts"] = pd.to_datetime(ev["ts"], unit="s").dt.strftime("%H:%M:%S.%f").str[:-3]
            st.dataframe(ev.style.apply(lambda r: ["background:#d03b3b33" if r.name == bad else "" for _ in r], axis=1),
                         hide_index=True, width="stretch")
            st.markdown("**6 · Ground-truth verdict**")
            for v in t["verdicts"]:
                st.write(f"{DETECTOR_LABEL.get(v['detector'], v['detector'])}: **{v['verdict']}** {v['fault_id'] or ''}")
            if st.button("Mark false alarm (feedback for retraining)"):
                post("/api/feedback", json={"trace_id": tid})
                st.success("feedback stored")
            st.session_state["overlay"] = [e["event_id"] for e in t["events"]]
            st.caption("Path on the normal flow graph: see the *Normal flow graph* tab (overlay = this trace).")


# ------------------------------------------------------------------ flow graph
with tab_flow:
    st.subheader("5 · Normal flow graph — what the model learned")
    tr = get("/api/transitions") or {"nodes": [], "edges": []}
    if tr["nodes"]:
        min_p = st.slider("Hide transitions below probability", 0.0, 0.2, 0.005, 0.005)
        nodes = {str(n["id"]): n for n in tr["nodes"]}
        order = ["START"] + [str(n["id"]) for n in sorted(tr["nodes"], key=lambda n: -n["count"])] + ["END"]
        # layered layout: BFS depth from START along the most likely edges
        depth = {"START": 0}
        edges = [e for e in tr["edges"] if e["prob"] >= min_p]
        for _ in range(30):
            for e in edges:
                s, d = str(e["source"]), str(e["target"])
                if s in depth and d not in depth:
                    depth[d] = depth[s] + 1
        for n in order:
            depth.setdefault(n, max(depth.values()) + 1)
        by_layer: dict = {}
        for n in order:
            by_layer.setdefault(depth[n], []).append(n)
        pos = {n: (layer, i - len(ns) / 2) for layer, ns in by_layer.items() for i, n in enumerate(ns)}
        overlay = st.session_state.get("overlay", [])
        path = list(zip(["START"] + [str(x) for x in overlay], [str(x) for x in overlay] + ["END"])) if overlay else []
        known = {(str(e["source"]), str(e["target"])) for e in tr["edges"]}
        fig = go.Figure()
        for e in edges:
            s, d = str(e["source"]), str(e["target"])
            (x0, y0), (x1, y1) = pos[s], pos[d]
            fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", line={"width": 0.5 + 6 * e["prob"],
                                     "color": "#86b6ef"}, hoverinfo="text", text=f"{s}→{d} {e['prob']:.0%}"))
        for s, d in path:
            if s in pos and d in pos:
                (x0, y0), (x1, y1) = pos[s], pos[d]
                ok = (s, d) in known
                fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                                         line={"width": 3, "color": "#0b0b0b" if ok else "#d03b3b",
                                               "dash": "solid" if ok else "dash"}, hoverinfo="skip"))
        xs = [pos[n][0] for n in order]
        ys = [pos[n][1] for n in order]
        cols = [SERVICE_COLOR.get(nodes.get(n, {}).get("services", ["-"])[0], "#898781") for n in order]
        hov = [nodes[n]["template"] if n in nodes else n for n in order]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", text=[n if n in ("START", "END") else f"E{n}" for n in order],
                                 textposition="top center", hovertext=hov, hoverinfo="text",
                                 marker={"size": 16, "color": cols, "line": {"width": 1, "color": "white"}}))
        fig.update_layout(showlegend=False, height=620, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis=dict(visible=False), yaxis=dict(visible=False))
        st.plotly_chart(fig, width="stretch")
        st.caption("Nodes = templates (colour = service); edge width = transition probability in training. "
                   "Overlay (from Investigate): black = a road that exists, red dashed = a road that does not. "
                   "This is a first-order view; the LSTM uses the last h events, so it also catches "
                   "\"a retry is fine once, not five times\".")
    else:
        st.info("No trained model yet (artifacts/demo/transitions.json).")


# ------------------------------------------------------------------ template library
with tab_tpl:
    st.subheader("4 · Template library")
    if templates:
        df = pd.DataFrame(templates.values())
        df["first_seen"] = pd.to_datetime(df["first_seen"], unit="s").dt.strftime("%H:%M:%S")
        df["status"] = [s if s != "new-matched" else f"new → matched to E{int(m)} ({sc:.2f})"
                        for s, m, sc in zip(df["status"], df["matched_to"].fillna(0), df["match_score"].fillna(0))]
        st.dataframe(df[["event_id", "template", "service", "count", "first_seen", "level", "status"]],
                     hide_index=True, width="stretch", height=480)
        cum = df.sort_values("event_id")
        fs = pd.to_datetime(pd.DataFrame(templates.values())["first_seen"], unit="s").sort_values()
        fig = go.Figure(go.Scatter(x=fs, y=list(range(1, len(fs) + 1)), mode="lines", line={"shape": "hv"}))
        fig.update_layout(height=240, margin=dict(l=10, r=10, t=30, b=10), title="templates over time",
                          yaxis_title="distinct templates")
        st.plotly_chart(fig, width="stretch")


# ------------------------------------------------------------------ incidents
with tab_inc:
    st.subheader("Incident reports")
    inc = get("/api/incidents", run=RUN)
    if inc:
        s = inc["summary"]
        c = st.columns(4)
        c[0].metric("Requests processed", f"{s['requests_processed']:,}")
        c[1].metric("Faults detected", s["faults_detected"])
        c[2].metric("New templates", s["new_templates"])
        c[3].metric("False alarms / h", "—" if s["false_alarms_per_h"] is None else f"{s['false_alarms_per_h']:.1f}")
        for r in inc["reports"][::-1]:
            with st.expander(r["fault_id"]):
                st.markdown(r["markdown"])
                st.download_button("Download .md", r["markdown"], file_name=f"incident_{r['fault_id']}.md",
                                   key=f"dl{r['fault_id']}")


# ------------------------------------------------------------------ benchmarks
with tab_bench:
    st.subheader("Benchmarks and headline results")
    res_path = ROOT / "reports" / "results.csv"
    tables = ROOT / "reports" / "tables.md"
    if tables.exists():
        st.markdown(tables.read_text(encoding="utf-8"))
    figs = sorted((ROOT / "reports" / "figures").glob("*.png"))
    for i in range(0, len(figs), 2):
        cols = st.columns(2)
        for c, f in zip(cols, figs[i:i + 2]):
            c.image(str(f), caption=f.stem)
    if res_path.exists():
        with st.expander("results.csv (every reported number)"):
            st.dataframe(pd.read_csv(res_path), width="stretch")
