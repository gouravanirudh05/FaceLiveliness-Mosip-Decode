#!/usr/bin/env python3
"""
Browser webcam → WebSocket → liveness gRPC bridge.

Three modes, selectable in the browser UI:
  passive : passive PAD frame stream  → passive service (:50052)
  active  : challenge-response        → active service  (:50051)
  hybrid  : passive then challenges   → passive service (:50052)

Run:
    python browser_liveness.py

Then open:
    http://127.0.0.1:8080
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from typing import Optional

import grpc
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
import uvicorn

from active_liveness.grpc_gen import active_liveness_pb2 as apb
from active_liveness.grpc_gen import active_liveness_pb2_grpc as apb_grpc
from passive_liveness.grpc_gen import passive_liveness_pb2 as pb
from passive_liveness.grpc_gen import passive_liveness_pb2_grpc as pb_grpc


HOST = "127.0.0.1"
PORT = 8080
GRPC_ADDRESS_ACTIVE  = "127.0.0.1:50051"
GRPC_ADDRESS_PASSIVE = "127.0.0.1:50052"
FRAME_QUEUE_SIZE = 2

WORKFLOWS: dict[str, int] = {
    "resident":   apb.WORKFLOW_RESIDENT,
    "operator":   apb.WORKFLOW_OPERATOR,
    "supervisor": apb.WORKFLOW_SUPERVISOR,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("browser_liveness")

app = FastAPI(title="Face Liveness")


# ─────────────────────────────── helpers ──────────────────────────────────────

def enum_name(enum_type, value: int, prefix: str) -> str:
    try:
        return enum_type.Name(value).removeprefix(prefix).lower()
    except Exception:
        return str(value)


def _passive_frame_json(frame) -> dict:
    score = float(frame.bonafide_probability) if frame.HasField("bonafide_probability") else None
    return {
        "type":     "passive_frame",
        "decision": enum_name(pb.Decision, frame.decision, "DECISION_"),
        "category": enum_name(pb.AttackCategory, frame.attack_category, "ATTACK_CATEGORY_"),
        "pai":      enum_name(pb.PAISpecies, frame.suspected_pai_species, "PAI_SPECIES_"),
        "score":    score,
        "message":  "No decision yet" if score is None else f"Live score: {score:.3f}",
    }


def _passive_result_json(result, msg_type: str = "passive_result") -> dict:
    score = float(result.bonafide_probability) if result.HasField("bonafide_probability") else None
    return {
        "type":        msg_type,
        "decision":    enum_name(pb.Decision, result.decision, "DECISION_"),
        "category":    enum_name(pb.AttackCategory, result.attack_category, "ATTACK_CATEGORY_"),
        "pai":         enum_name(pb.PAISpecies, result.suspected_pai_species, "PAI_SPECIES_"),
        "score":       score,
        "frames":      int(result.frames_analysed),
        "frames_used": int(result.frames_used),
        "message":     f"Processed {result.frames_analysed} frames ({result.frames_used} used)",
    }


def _active_msg_json(m) -> Optional[dict]:
    """Convert an ActiveServerMessage → JSON dict, or None to skip."""
    kind = m.WhichOneof("payload")
    if kind == "session_started":
        s = m.session_started
        return {
            "type":         "session_started",
            "session_id":   s.session_id[:8],
            "max_attempts": s.max_attempts,
        }
    if kind == "challenge_prompt":
        p = m.challenge_prompt
        return {
            "type":        "challenge_prompt",
            "prompt":      p.prompt,
            "attempt":     p.attempt,
            "step_index":  p.step_index,
            "total_steps": p.total_steps,
            "timeout_ms":  p.timeout_ms,
            "tier":        enum_name(apb.Tier, p.tier, "TIER_"),
        }
    if kind == "feedback":
        f = m.feedback
        return {"type": "feedback", "message": f.message, "progress": float(f.progress)}
    if kind == "challenge_result":
        r = m.challenge_result
        return {
            "type":       "challenge_result",
            "step_index": r.step_index,
            "passed":     r.passed,
            "reason":     enum_name(apb.FailureReason, r.reason, "FAILURE_REASON_") if not r.passed else "",
            "margin":     float(r.margin) if r.passed else 0.0,
        }
    if kind == "retry_available":
        r = m.retry_available
        return {
            "type":              "retry_available",
            "message":           r.message,
            "retries_remaining": r.retries_remaining,
            "reason":            enum_name(apb.FailureReason, r.reason, "FAILURE_REASON_"),
            "guidance":          list(r.guidance),
        }
    if kind == "decision":
        d = m.decision
        return {
            "type":    "active_decision",
            "status":  enum_name(apb.DecisionStatus, d.status, "DECISION_"),
            "message": d.message,
            "reason":  enum_name(apb.FailureReason, d.reason, "FAILURE_REASON_") if d.reason else "",
        }
    if kind == "error":
        return {
            "type":    "error",
            "message": f"{enum_name(apb.ErrorCode, m.error.code, 'ERROR_CODE_')}: {m.error.message}",
        }
    return None


# ─────────────────────────────── base bridge ──────────────────────────────────

class _BaseBridge:
    """Shared WebSocket ↔ gRPC lifecycle: channel, frame queue, tasks, cleanup."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket      = websocket
        self.channel:       Optional[grpc.aio.Channel] = None
        self.call           = None
        self.request_queue: asyncio.Queue = asyncio.Queue(maxsize=FRAME_QUEUE_SIZE + 2)
        self.response_task: Optional[asyncio.Task] = None
        self.closed         = False
        self.result_sent    = False

    # ── outgoing helpers ──────────────────────────────────────────────────────

    async def send_json(self, payload: dict) -> None:
        if self.closed:
            return
        try:
            await self.websocket.send_text(json.dumps(payload))
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            self.closed = True

    async def put_frame(self, msg) -> None:
        """Drop oldest queued frame when inference falls behind."""
        if self.closed:
            return
        try:
            self.request_queue.put_nowait(msg)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self.request_queue.get_nowait()
            with suppress(asyncio.QueueFull):
                self.request_queue.put_nowait(msg)

    async def _request_iterator(self):
        """Async generator consumed by grpc.aio; None is the sentinel."""
        while True:
            item = await self.request_queue.get()
            if item is None:
                return
            yield item

    # ── gRPC connection ───────────────────────────────────────────────────────

    async def _connect(self, address: str, timeout: float = 5.0) -> bool:
        self.channel = grpc.aio.insecure_channel(address)
        try:
            await asyncio.wait_for(self.channel.channel_ready(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            await self.send_json({
                "type":    "error",
                "message": f"Cannot connect to liveness service at {address}",
            })
            return False

    # ── cleanup ───────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Idempotent, cancellation-safe teardown."""
        if self.closed:
            return
        self.closed = True

        while True:          # drain request queue
            try:
                self.request_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        if self.call is not None:
            with suppress(Exception):
                self.call.cancel()

        current = asyncio.current_task()
        if self.response_task is not None and self.response_task is not current:
            self.response_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.response_task

        if self.channel is not None:
            with suppress(Exception):
                await self.channel.close()

        self.call = self.response_task = None

    async def _on_rpc_error(self, exc: grpc.aio.AioRpcError, label: str) -> None:
        if exc.code() == grpc.StatusCode.CANCELLED:
            return
        log.error("%s gRPC stream failed: %s: %s", label, exc.code().name, exc.details())
        await self.send_json({
            "type":    "error",
            "message": f"{label} error: {exc.code().name}"
                       + (f" — {exc.details()}" if exc.details() else ""),
        })


# ─────────────────────────────── passive bridge ───────────────────────────────

class PassiveBridge(_BaseBridge):

    async def start(self) -> None:
        if not await self._connect(GRPC_ADDRESS_PASSIVE):
            raise ConnectionError(GRPC_ADDRESS_PASSIVE)
        # Rebuild queue so the StartStream is always the very first item.
        self.request_queue = asyncio.Queue(maxsize=FRAME_QUEUE_SIZE + 1)
        await self.request_queue.put(pb.StreamRequest(start=pb.StartStream()))
        stub = pb_grpc.PassiveLivenessServiceStub(self.channel)
        self.call = stub.AnalyzeStream(self._request_iterator())
        self.response_task = asyncio.create_task(
            self._read(), name="passive-grpc-responses"
        )

    async def send_frame(self, jpeg: bytes) -> None:
        frame = apb.Frame(
            data=jpeg,
            encoding=apb.FRAME_ENCODING_JPEG,
            timestamp_ms=int(time.monotonic() * 1000),
        )
        await self.put_frame(pb.StreamRequest(frame=frame))

    async def _read(self) -> None:
        try:
            async for m in self.call:
                kind = m.WhichOneof("payload")
                if kind == "frame":
                    await self.send_json(_passive_frame_json(m.frame))
                elif kind == "result":
                    self.result_sent = True
                    await self.send_json(_passive_result_json(m.result))
                elif kind == "error":
                    await self.send_json({"type": "error", "message": m.error.message})
        except asyncio.CancelledError:
            raise
        except grpc.aio.AioRpcError as exc:
            await self._on_rpc_error(exc, "passive")
        except Exception as exc:
            log.exception("passive gRPC reader error")
            await self.send_json({"type": "error", "message": f"Passive error: {exc}"})


# ─────────────────────────────── active bridge ────────────────────────────────

class ActiveBridge(_BaseBridge):

    def __init__(self, websocket: WebSocket, workflow: int) -> None:
        super().__init__(websocket)
        self.workflow = workflow

    async def start(self) -> None:
        if not await self._connect(GRPC_ADDRESS_ACTIVE):
            raise ConnectionError(GRPC_ADDRESS_ACTIVE)
        await self.request_queue.put(
            apb.ClientMessage(start=apb.StartSession(workflow=self.workflow))
        )
        stub = apb_grpc.ActiveLivenessServiceStub(self.channel)
        self.call = stub.RunSession(self._request_iterator())
        self.response_task = asyncio.create_task(
            self._read(), name="active-grpc-responses"
        )

    async def send_frame(self, jpeg: bytes) -> None:
        frame = apb.Frame(
            data=jpeg,
            encoding=apb.FRAME_ENCODING_JPEG,
            timestamp_ms=int(time.monotonic() * 1000),
        )
        await self.put_frame(apb.ClientMessage(frame=frame))

    async def send_retry(self) -> None:
        if not self.closed:
            await self.request_queue.put(apb.ClientMessage(retry=apb.Retry()))

    async def _read(self) -> None:
        try:
            async for m in self.call:
                msg = _active_msg_json(m)
                if msg:
                    if msg["type"] == "active_decision":
                        self.result_sent = True
                    await self.send_json(msg)
        except asyncio.CancelledError:
            raise
        except grpc.aio.AioRpcError as exc:
            await self._on_rpc_error(exc, "active")
        except Exception as exc:
            log.exception("active gRPC reader error")
            await self.send_json({"type": "error", "message": f"Active error: {exc}"})


# ─────────────────────────────── hybrid bridge ────────────────────────────────

class HybridBridge(_BaseBridge):

    def __init__(self, websocket: WebSocket, workflow: int) -> None:
        super().__init__(websocket)
        self.workflow = workflow

    async def start(self) -> None:
        if not await self._connect(GRPC_ADDRESS_PASSIVE):
            raise ConnectionError(GRPC_ADDRESS_PASSIVE)
        await self.request_queue.put(
            pb.HybridClientMessage(start=pb.HybridStart(workflow=self.workflow))
        )
        stub = pb_grpc.PassiveLivenessServiceStub(self.channel)
        self.call = stub.HybridSession(self._request_iterator())
        self.response_task = asyncio.create_task(
            self._read(), name="hybrid-grpc-responses"
        )

    async def send_frame(self, jpeg: bytes) -> None:
        frame = apb.Frame(
            data=jpeg,
            encoding=apb.FRAME_ENCODING_JPEG,
            timestamp_ms=int(time.monotonic() * 1000),
        )
        await self.put_frame(pb.HybridClientMessage(frame=frame))

    async def send_retry(self) -> None:
        if not self.closed:
            await self.request_queue.put(
                pb.HybridClientMessage(retry=apb.Retry())
            )

    async def _read(self) -> None:
        try:
            async for m in self.call:
                kind = m.WhichOneof("payload")

                if kind == "started":
                    await self.send_json({
                        "type":       "hybrid_started",
                        "session_id": m.started.session_id[:8],
                    })

                elif kind == "passive_progress":
                    p = m.passive_progress
                    reasons = [
                        enum_name(pb.NonResponseReason, r, "NON_RESPONSE_")
                        for r in p.quality.reasons
                    ]
                    await self.send_json({
                        "type":            "passive_progress",
                        "frames_used":     p.frames_used,
                        "frames_required": p.frames_required,
                        "quality_passed":  p.quality.passed,
                        "quality_reasons": reasons,
                    })

                elif kind == "passive_verdict":
                    v = m.passive_verdict
                    payload = _passive_result_json(v.result, "passive_verdict")
                    payload["next_step"] = enum_name(pb.NextStep, v.next_step, "NEXT_STEP_")
                    await self.send_json(payload)

                elif kind == "monitor":
                    f = m.monitor.frame
                    score = float(f.bonafide_probability) if f.HasField("bonafide_probability") else None
                    await self.send_json({
                        "type":     "monitor",
                        "decision": enum_name(pb.Decision, f.decision, "DECISION_"),
                        "score":    score,
                    })

                elif kind == "active":
                    # Nested active challenge messages; hybrid decision arrives separately.
                    msg = _active_msg_json(m.active)
                    if msg:
                        await self.send_json(msg)

                elif kind == "decision":
                    d = m.decision
                    self.result_sent = True
                    await self.send_json({
                        "type":    "hybrid_decision",
                        "status":  enum_name(pb.HybridStatus,  d.status, "HYBRID_"),
                        "reason":  enum_name(pb.HybridReason,  d.reason, "HYBRID_REASON_"),
                        "message": d.message,
                    })

                elif kind == "error":
                    await self.send_json({"type": "error", "message": m.error.message})

        except asyncio.CancelledError:
            raise
        except grpc.aio.AioRpcError as exc:
            await self._on_rpc_error(exc, "hybrid")
        except Exception as exc:
            log.exception("hybrid gRPC reader error")
            await self.send_json({"type": "error", "message": f"Hybrid error: {exc}"})


# ──────────────────────────────── HTML UI ─────────────────────────────────────

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Face Liveness</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg:      #111;
    --surface: #1b1b1b;
    --border:  #2b2b2b;
    --text:    #eee;
    --muted:   #888;
    --green:   #22c55e;
    --red:     #ef4444;
    --blue:    #38bdf8;
    --amber:   #f59e0b;
    --purple:  #a78bfa;
  }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: system-ui, sans-serif;
    min-height: 100vh;
  }
  main { max-width: 900px; margin: 0 auto; padding: 20px 16px; }
  h1   { font-size: 1.4rem; font-weight: 700; margin-bottom: 16px; }

  /* ── Mode tabs ──────────────────────────────────────────────────────── */
  .tabs {
    display: flex; gap: 4px;
    background: var(--surface); border-radius: 10px; padding: 4px;
    margin-bottom: 12px;
  }
  .tab {
    flex: 1; padding: 8px 0; border: none; border-radius: 7px;
    cursor: pointer; font-size: .88rem; font-weight: 600;
    background: transparent; color: var(--muted); transition: all .15s;
  }
  .tab:hover:not(:disabled) { color: var(--text); background: var(--border); }
  .tab.on { background: #2d2d5e; color: #a5b4fc; }
  .tab:disabled { opacity: .4; cursor: default; }

  /* ── Config row ────────────────────────────────────────────────────── */
  .cfg {
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
    background: var(--surface); border-radius: 8px;
    padding: 10px 14px; margin-bottom: 12px;
    font-size: .88rem; color: var(--muted);
  }
  .cfg label { display: flex; align-items: center; gap: 6px; }
  .cfg select {
    background: var(--bg); color: var(--text);
    border: 1px solid var(--border); border-radius: 6px;
    padding: 5px 8px; font-size: .88rem; cursor: pointer;
  }
  .cfg-hint { margin-left: auto; font-style: italic; }

  /* ── Video ──────────────────────────────────────────────────────────── */
  .vid-wrap {
    position: relative;
    background: #000; border-radius: 12px; overflow: hidden;
    margin-bottom: 12px;
  }
  video {
    display: block; width: 100%;
    max-height: 62vh; object-fit: contain;
  }
  canvas { display: none; }

  /* face oval */
  .oval {
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    width: 34%; padding-top: 48%;
    border: 2px solid rgba(255,255,255,.28);
    border-radius: 50%;
    pointer-events: none;
  }

  /* challenge overlay */
  .ch-overlay {
    position: absolute; inset: 0;
    display: flex; flex-direction: column;
    justify-content: flex-end;
    background: linear-gradient(transparent 40%, rgba(0,0,0,.82));
    padding: 12px 20px 20px;
    pointer-events: none;
  }
  .ch-overlay.hidden { display: none; }
  .ch-prompt {
    font-size: clamp(1.1rem, 3.5vw, 1.6rem);
    font-weight: 700; text-align: center;
    color: #fff; text-shadow: 0 1px 6px rgba(0,0,0,.9);
    margin-bottom: 10px;
  }
  .ch-meta {
    display: flex; justify-content: center;
    align-items: center; gap: 20px;
    font-size: .85rem; color: rgba(255,255,255,.7);
  }
  .ch-timer {
    font-size: 1.25rem; font-weight: 700;
    color: var(--green); min-width: 3.5em; text-align: right;
    transition: color .2s;
  }
  .ch-timer.urgent { color: var(--red); }

  /* ── Buttons ────────────────────────────────────────────────────────── */
  .btns { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
  .btn {
    padding: 10px 22px; border: none; border-radius: 8px;
    cursor: pointer; font-size: .9rem; font-weight: 600;
    transition: opacity .15s;
  }
  .btn:disabled { opacity: .32; cursor: not-allowed; }
  #btn-start { background: #166534; color: #bbf7d0; }
  #btn-stop  { background: #7f1d1d; color: #fecaca; }
  #btn-retry { background: #4c1d95; color: #ddd6fe; }

  /* ── Status cards ───────────────────────────────────────────────────── */
  .cards { display: grid; gap: 10px; }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 14px;
  }
  .card.hidden { display: none; }
  .card-title {
    font-size: .72rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .07em; color: var(--muted); margin-bottom: 10px;
  }

  /* key-value grid */
  .kv { display: grid; grid-template-columns: auto 1fr; gap: 5px 14px; font-size: .88rem; }
  .k  { color: var(--muted); white-space: nowrap; align-self: center; }
  .v  { font-weight: 600; word-break: break-word; }
  .mono { font-family: monospace; font-size: .82rem; font-weight: 400; }

  /* state badge */
  .badge {
    display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: .78rem; font-weight: 700;
    background: var(--border); color: var(--muted);
  }
  .badge.running, .badge.finished { background: #14532d; color: var(--green); }
  .badge.retry    { background: #1e1b4b; color: var(--purple); }
  .badge.failed, .badge.error { background: #450a0a; color: var(--red); }

  /* decision colours */
  .dec-live   { color: var(--green); }
  .dec-attack { color: var(--red); }
  .dec-none   { color: var(--muted); }
  .dec-pass   { color: var(--green); font-size: 1.1em; }
  .dec-fail   { color: var(--red);   font-size: 1.1em; }

  /* progress bar */
  .prog-wrap { height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 10px; }
  .prog-fill { height: 100%; background: var(--green); border-radius: 3px; transition: width .25s; }

  /* step dots */
  .dots { display: inline-flex; gap: 4px; vertical-align: middle; margin-left: 6px; }
  .dot  { width: 8px; height: 8px; border-radius: 50%; background: var(--border); }
  .dot.done   { background: var(--green); }
  .dot.active { background: var(--blue); }

  /* guidance */
  .guidance { list-style: none; margin-top: 10px; padding: 0; }
  .guidance.hidden { display: none; }
  .guidance li {
    font-size: .85rem; color: var(--blue);
    padding: 3px 0; display: flex; gap: 6px; align-items: baseline;
  }
  .guidance li::before { content: "→"; }
</style>
</head>
<body>
<main>
  <h1>Face Liveness</h1>

  <!-- Mode tabs -->
  <div class="tabs" id="mode-tabs">
    <button class="tab on"  data-mode="passive">Passive</button>
    <button class="tab"     data-mode="active">Active</button>
    <button class="tab"     data-mode="hybrid">Hybrid</button>
  </div>

  <!-- Config row -->
  <div class="cfg" id="cfg-row">
    <label id="wf-label" class="hidden">
      Workflow
      <select id="wf-select">
        <option value="resident">Resident</option>
        <option value="operator">Operator</option>
        <option value="supervisor">Supervisor</option>
      </select>
    </label>
    <span class="cfg-hint" id="cfg-hint">PAD without challenges</span>
  </div>

  <!-- Video -->
  <div class="vid-wrap">
    <video id="video" autoplay muted playsinline></video>
    <canvas id="canvas"></canvas>
    <div class="oval"></div>
    <div class="ch-overlay hidden" id="ch-overlay">
      <p class="ch-prompt" id="ch-prompt-text"></p>
      <div class="ch-meta">
        <span id="ch-step-info"></span>
        <span class="ch-timer" id="ch-timer"></span>
      </div>
    </div>
  </div>

  <!-- Buttons -->
  <div class="btns">
    <button class="btn" id="btn-start">▶ Start</button>
    <button class="btn" id="btn-stop"  disabled>■ Stop</button>
    <button class="btn" id="btn-retry" disabled>↺ Retry</button>
  </div>

  <!-- Status cards -->
  <div class="cards">

    <!-- Session (always visible) -->
    <div class="card" id="card-session">
      <div class="card-title">Session</div>
      <div class="kv">
        <div class="k">State</div>
        <div class="v"><span class="badge" id="state-badge">idle</span></div>
        <div class="k">Mode</div>
        <div class="v" id="st-mode">passive</div>
        <div class="k">Message</div>
        <div class="v mono" id="st-message">—</div>
      </div>
    </div>

    <!-- Challenge progress (active / hybrid active phase) -->
    <div class="card hidden" id="card-challenge">
      <div class="card-title">Challenge</div>
      <div class="kv">
        <div class="k">Attempt</div>
        <div class="v" id="ch-attempt">—</div>
        <div class="k">Step</div>
        <div class="v">
          <span id="ch-step-txt">—</span>
          <span class="dots" id="ch-dots"></span>
        </div>
        <div class="k">Tier</div>
        <div class="v" id="ch-tier">—</div>
        <div class="k">Feedback</div>
        <div class="v" id="ch-feedback">—</div>
      </div>
      <div class="prog-wrap">
        <div class="prog-fill" id="ch-prog" style="width:0"></div>
      </div>
      <ul class="guidance hidden" id="ch-guidance"></ul>
    </div>

    <!-- PAD scores (passive always; hybrid after passive_verdict) -->
    <div class="card" id="card-pad">
      <div class="card-title">PAD Scores</div>
      <div class="kv">
        <div class="k">Decision</div>  <div class="v" id="pad-decision">—</div>
        <div class="k">Live score</div><div class="v" id="pad-score">—</div>
        <div class="k">Category</div>  <div class="v" id="pad-category">—</div>
        <div class="k">PAI species</div><div class="v" id="pad-pai">—</div>
        <div class="k">Frames</div>    <div class="v" id="pad-frames">0</div>
      </div>
    </div>

    <!-- Hybrid passive collection progress -->
    <div class="card hidden" id="card-hp">
      <div class="card-title">Passive Phase — collecting frames</div>
      <div class="kv">
        <div class="k">Frames</div>  <div class="v" id="hp-frames">0 / —</div>
        <div class="k">Quality</div> <div class="v" id="hp-quality">—</div>
      </div>
      <div class="prog-wrap">
        <div class="prog-fill" id="hp-prog" style="width:0"></div>
      </div>
    </div>

  </div><!-- /cards -->
</main>

<script>
// ── element refs ──────────────────────────────────────────────────────────────
const video       = document.getElementById("video");
const canvas      = document.getElementById("canvas");
const ctx         = canvas.getContext("2d");

const modeTabs    = document.querySelectorAll(".tab");
const wfLabel     = document.getElementById("wf-label");
const wfSelect    = document.getElementById("wf-select");
const cfgHint     = document.getElementById("cfg-hint");

const chOverlay   = document.getElementById("ch-overlay");
const chPromptEl  = document.getElementById("ch-prompt-text");
const chStepInfo  = document.getElementById("ch-step-info");
const chTimerEl   = document.getElementById("ch-timer");

const btnStart    = document.getElementById("btn-start");
const btnStop     = document.getElementById("btn-stop");
const btnRetry    = document.getElementById("btn-retry");

const stateBadge  = document.getElementById("state-badge");
const stMode      = document.getElementById("st-mode");
const stMessage   = document.getElementById("st-message");

const cardChallenge = document.getElementById("card-challenge");
const cardPad       = document.getElementById("card-pad");
const cardHp        = document.getElementById("card-hp");

const chAttempt   = document.getElementById("ch-attempt");
const chStepTxt   = document.getElementById("ch-step-txt");
const chDots      = document.getElementById("ch-dots");
const chTier      = document.getElementById("ch-tier");
const chFeedback  = document.getElementById("ch-feedback");
const chProg      = document.getElementById("ch-prog");
const chGuidance  = document.getElementById("ch-guidance");

const padDecision = document.getElementById("pad-decision");
const padScore    = document.getElementById("pad-score");
const padCategory = document.getElementById("pad-category");
const padPai      = document.getElementById("pad-pai");
const padFrames   = document.getElementById("pad-frames");

const hpFrames    = document.getElementById("hp-frames");
const hpQuality   = document.getElementById("hp-quality");
const hpProg      = document.getElementById("hp-prog");

// ── runtime state ─────────────────────────────────────────────────────────────
let currentMode     = "passive";
let stream          = null;
let ws              = null;
let captureTimer    = null;
let timerInterval   = null;
let challengeEnd    = null;
let stopping        = false;

const MODE_HINTS = {
  passive: "PAD without challenges",
  active:  "Challenge-response liveness",
  hybrid:  "Passive PAD, then challenges if needed",
};

// ── mode tab switching ────────────────────────────────────────────────────────
modeTabs.forEach(tab => {
  tab.addEventListener("click", () => {
    if (ws) return;
    modeTabs.forEach(t => t.classList.remove("on"));
    tab.classList.add("on");
    currentMode = tab.dataset.mode;
    wfLabel.classList.toggle("hidden", currentMode === "passive");
    cfgHint.textContent = MODE_HINTS[currentMode];
    stMode.textContent  = currentMode;
    resetUI();
  });
});

// ── state helpers ─────────────────────────────────────────────────────────────
function setState(name) {
  stateBadge.className = "badge " + name;
  stateBadge.textContent = name;
}
function setMsg(txt) { stMessage.textContent = txt || "—"; }

function decClass(d) {
  if (!d || d === "—" || d === "unknown" || d === "pending") return "v dec-none";
  if (d === "bonafide" || d === "passed") return "v dec-live";
  if (d === "attack"   || d === "failed") return "v dec-attack";
  return "v";
}

function resetUI() {
  setState("idle");
  setMsg("—");
  stopTimer();
  hideChallenge();
  cardChallenge.classList.add("hidden");
  cardHp.classList.add("hidden");
  chGuidance.classList.add("hidden");
  chGuidance.innerHTML = "";

  // Passive scores card: shown for passive; hidden for others until data arrives
  cardPad.classList.toggle("hidden", currentMode !== "passive");
  if (currentMode === "hybrid") cardHp.classList.remove("hidden");

  [padDecision, padScore, padCategory, padPai].forEach(el => {
    el.textContent = "—"; el.className = "v";
  });
  padFrames.textContent = "0";
  hpFrames.textContent = "0 / —";
  hpQuality.textContent = "—";
  hpProg.style.width = "0";
  chProg.style.width = "0";
  chAttempt.textContent = chStepTxt.textContent = chTier.textContent = chFeedback.textContent = "—";
  chDots.innerHTML = "";
}

// ── countdown timer ───────────────────────────────────────────────────────────
function startTimer(ms) {
  challengeEnd = Date.now() + ms;
  clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    const rem = Math.max(0, challengeEnd - Date.now()) / 1000;
    chTimerEl.textContent = rem.toFixed(1) + "s";
    chTimerEl.classList.toggle("urgent", rem < 3);
    if (rem <= 0) stopTimer();
  }, 100);
}
function stopTimer() {
  clearInterval(timerInterval);
  timerInterval = null;
  challengeEnd = null;
  chTimerEl.textContent = "";
  chTimerEl.classList.remove("urgent");
}

// ── challenge overlay ─────────────────────────────────────────────────────────
function showChallenge(prompt, stepInfo) {
  chPromptEl.textContent = prompt;
  chStepInfo.textContent = stepInfo;
  chOverlay.classList.remove("hidden");
}
function hideChallenge() {
  chOverlay.classList.add("hidden");
  chPromptEl.textContent = "";
}
function buildDots(current, total) {
  chDots.innerHTML = "";
  for (let i = 0; i < total; i++) {
    const d = document.createElement("div");
    d.className = "dot" + (i < current ? " done" : i === current ? " active" : "");
    chDots.appendChild(d);
  }
}

// ── WebSocket message dispatch ────────────────────────────────────────────────
function handleMsg(msg) {
  switch (msg.type) {

    // ── common ────────────────────────────────────────────────────────────
    case "status":
      setState(msg.state || "running");
      if (msg.message) setMsg(msg.message);
      break;

    case "error":
      setState("error");
      setMsg(msg.message || "Unknown error");
      stopTimer(); hideChallenge();
      btnRetry.disabled = true;
      break;

    // ── passive ───────────────────────────────────────────────────────────
    case "passive_frame":
      if (msg.decision !== undefined) {
        padDecision.textContent = msg.decision;
        padDecision.className   = decClass(msg.decision);
      }
      if (msg.score  != null) padScore.textContent    = Number(msg.score).toFixed(3);
      if (msg.category)       padCategory.textContent = msg.category;
      if (msg.pai != null)    padPai.textContent      = msg.pai || "none";
      if (msg.message)        setMsg(msg.message);
      break;

    case "passive_result":
      setState("finished");
      padDecision.textContent = msg.decision ?? "—";
      padDecision.className   = decClass(msg.decision);
      padScore.textContent    = msg.score != null ? Number(msg.score).toFixed(3) : "—";
      padCategory.textContent = msg.category ?? "—";
      padPai.textContent      = msg.pai || "none";
      padFrames.textContent   = msg.frames ?? "0";
      setMsg(msg.message ?? "");
      stopCapture();
      break;

    // ── active: session lifecycle ─────────────────────────────────────────
    case "session_started":
      setState("running");
      setMsg(`Session ${msg.session_id} · max ${msg.max_attempts} attempt${msg.max_attempts !== 1 ? "s" : ""}`);
      cardChallenge.classList.remove("hidden");
      break;

    case "challenge_prompt":
      stopTimer();
      chGuidance.classList.add("hidden");
      chGuidance.innerHTML = "";
      btnRetry.disabled = true;
      chAttempt.textContent = `Attempt ${msg.attempt}`;
      chStepTxt.textContent = `${msg.step_index + 1} / ${msg.total_steps}`;
      chTier.textContent    = msg.tier;
      chFeedback.textContent = "—";
      chProg.style.width = "0";
      buildDots(msg.step_index, msg.total_steps);
      showChallenge(
        msg.prompt,
        `Attempt ${msg.attempt} · Step ${msg.step_index + 1} / ${msg.total_steps}`
      );
      startTimer(msg.timeout_ms);
      setMsg(msg.prompt);
      break;

    case "feedback":
      if (msg.message)  { chFeedback.textContent = msg.message; setMsg(msg.message); }
      if (msg.progress != null)
        chProg.style.width = (msg.progress * 100).toFixed(0) + "%";
      break;

    case "challenge_result":
      stopTimer();
      if (msg.passed) {
        chProg.style.width = "100%";
        const dot = chDots.querySelectorAll(".dot")[msg.step_index];
        if (dot) dot.className = "dot done";
        hideChallenge();
        setMsg(`Step ${msg.step_index + 1} passed  (margin ${msg.margin.toFixed(2)})`);
      } else {
        setMsg(`Step ${msg.step_index + 1} failed: ${msg.reason}`);
      }
      break;

    case "retry_available":
      stopTimer(); hideChallenge();
      setState("retry");
      setMsg(msg.message);
      if (msg.guidance?.length) {
        chGuidance.innerHTML = msg.guidance.map(g => `<li>${g}</li>`).join("");
        chGuidance.classList.remove("hidden");
      }
      btnRetry.disabled = false;
      break;

    case "active_decision": {
      stopTimer(); hideChallenge();
      const ok = msg.status === "passed";
      setState(ok ? "finished" : "failed");
      setMsg(msg.message || (ok ? "Liveness confirmed ✓" : "Liveness check failed ✗"));
      if (ok) chProg.style.width = "100%";
      btnRetry.disabled = true;
      stopCapture();
      break;
    }

    // ── hybrid ────────────────────────────────────────────────────────────
    case "hybrid_started":
      setState("running");
      setMsg(`Session ${msg.session_id} · Passive phase — look at the camera`);
      cardHp.classList.remove("hidden");
      break;

    case "passive_progress": {
      const used = msg.frames_used  ?? 0;
      const req  = msg.frames_required ?? 0;
      hpFrames.textContent = `${used} / ${req > 0 ? req : "?"}`;
      hpProg.style.width   = req > 0 ? ((used / req) * 100).toFixed(0) + "%" : "0";
      hpQuality.textContent = msg.quality_passed
        ? "good"
        : (msg.quality_reasons?.join(", ") || "—");
      break;
    }

    case "passive_verdict":
      cardHp.classList.add("hidden");
      cardPad.classList.remove("hidden");
      padDecision.textContent = msg.decision ?? "—";
      padDecision.className   = decClass(msg.decision);
      padScore.textContent    = msg.score != null ? Number(msg.score).toFixed(3) : "—";
      padCategory.textContent = msg.category ?? "—";
      padPai.textContent      = msg.pai || "none";
      padFrames.textContent   = msg.frames_used ?? "0";
      setMsg(`Passive: ${msg.decision} · next → ${msg.next_step}`);
      // Show challenge card if active phase is coming
      if (msg.next_step && !["done","accept","reject"].includes(msg.next_step)) {
        cardChallenge.classList.remove("hidden");
        setMsg("Passive phase complete. Starting challenges…");
      }
      break;

    case "monitor":
      if (msg.score != null) padScore.textContent = Number(msg.score).toFixed(3);
      break;

    case "hybrid_decision": {
      stopTimer(); hideChallenge();
      const ok = msg.status === "passed";
      setState(ok ? "finished" : "failed");
      setMsg(msg.message || `Hybrid result: ${msg.status} (${msg.reason})`);
      btnRetry.disabled = true;
      stopCapture();
      break;
    }
  }
}

// ── capture helpers ───────────────────────────────────────────────────────────
function stopCapture() {
  if (captureTimer) { clearInterval(captureTimer); captureTimer = null; }
}
function stopCamera() {
  if (stream) { for (const t of stream.getTracks()) t.stop(); stream = null; }
  video.srcObject = null;
}
function closeSocket() {
  if (ws) { try { ws.close(1000, "client stopped"); } catch(_){} ws = null; }
}
function stopAll() {
  stopping = true;
  stopCapture(); closeSocket(); stopCamera(); stopTimer(); hideChallenge();
  btnStart.disabled  = false;
  btnStop.disabled   = true;
  btnRetry.disabled  = true;
  modeTabs.forEach(t => t.disabled = false);
  setState("stopped");
}

function captureFrame() {
  if (stopping || !ws || ws.readyState !== WebSocket.OPEN) return;
  if (!video.videoWidth || !video.videoHeight) return;

  const maxW  = 640;
  const scale = Math.min(1, maxW / video.videoWidth);
  const w = Math.round(video.videoWidth  * scale);
  const h = Math.round(video.videoHeight * scale);
  canvas.width = w; canvas.height = h;
  ctx.drawImage(video, 0, 0, w, h);

  canvas.toBlob(blob => {
    if (!blob || stopping || !ws || ws.readyState !== WebSocket.OPEN) return;
    blob.arrayBuffer().then(buf => {
      if (!stopping && ws && ws.readyState === WebSocket.OPEN) ws.send(buf);
    });
  }, "image/jpeg", 0.85);
}

// ── start ─────────────────────────────────────────────────────────────────────
async function start() {
  stopping = false;
  resetUI();
  modeTabs.forEach(t => t.disabled = true);

  try {
    setState("requesting camera");
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    video.srcObject = stream;
    await video.play();

    setState("connecting");
    const wf  = wfSelect.value;
    const url = `ws://${location.host}/ws?mode=${currentMode}&workflow=${wf}`;
    ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      if (stopping) return;
      setState("running");
      btnStart.disabled = true;
      btnStop.disabled  = false;
      captureTimer = setInterval(captureFrame, 100);
    };

    ws.onmessage = evt => {
      try { handleMsg(JSON.parse(evt.data)); }
      catch(e) { console.error("bad message", e); }
    };

    ws.onerror = () => {
      if (!stopping) { setState("error"); setMsg("WebSocket error"); }
    };

    ws.onclose = () => {
      const s = stateBadge.textContent;
      if (!stopping && (s === "running" || s === "connecting")) {
        setState("disconnected"); setMsg("Connection closed");
      }
      stopCapture(); btnRetry.disabled = true;
    };

  } catch(err) {
    console.error(err);
    setState("error");
    setMsg(err?.message || String(err));
    stopCapture(); stopCamera();
    btnStart.disabled = false;
    btnStop.disabled  = true;
    modeTabs.forEach(t => t.disabled = false);
  }
}

btnStart.onclick = start;
btnStop.onclick  = stopAll;
btnRetry.onclick = () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "retry" }));
  btnRetry.disabled = true;
  chGuidance.classList.add("hidden");
  setState("running");
};
</script>
</body>
</html>
"""


# ──────────────────────────── FastAPI routes ──────────────────────────────────

@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(HTML)


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    mode:     str = Query(default="passive"),
    workflow: str = Query(default="resident"),
) -> None:
    await websocket.accept()

    wf = WORKFLOWS.get(workflow, apb.WORKFLOW_RESIDENT)

    if mode == "active":
        bridge: _BaseBridge = ActiveBridge(websocket, wf)
    elif mode == "hybrid":
        bridge = HybridBridge(websocket, wf)
    else:
        bridge = PassiveBridge(websocket)
        mode = "passive"

    log.info("WebSocket connected  mode=%-7s workflow=%s", mode, workflow)

    try:
        await bridge.start()
        await bridge.send_json({
            "type":    "status",
            "state":   "running",
            "message": f"{mode.capitalize()} liveness stream started",
        })

        while True:
            data = await websocket.receive()

            if data.get("type") == "websocket.disconnect":
                break

            if data.get("bytes"):
                await bridge.send_frame(data["bytes"])

            elif data.get("text"):
                try:
                    ctrl = json.loads(data["text"])
                except json.JSONDecodeError:
                    ctrl = {}

                if ctrl.get("type") == "stop":
                    break
                elif ctrl.get("type") == "retry" and hasattr(bridge, "send_retry"):
                    await bridge.send_retry()

    except WebSocketDisconnect:
        log.info("WebSocket disconnected  mode=%s", mode)

    except asyncio.CancelledError:
        raise

    except grpc.aio.AioRpcError as exc:
        if exc.code() != grpc.StatusCode.CANCELLED:
            log.error("gRPC connection error: %s: %s", exc.code().name, exc.details())

    except ConnectionError as exc:
        log.error("Connection error: %s", exc)

    except Exception:
        log.exception("WebSocket handler failed  mode=%s", mode)
        with suppress(Exception):
            await bridge.send_json({"type": "error", "message": "Internal server error"})

    finally:
        await bridge.close()
        log.info("WebSocket cleanup complete  mode=%s", mode)


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
