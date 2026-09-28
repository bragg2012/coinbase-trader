from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import replace

from .models import Decision, DecisionRecord, Observation, Position


class JevDecisionEngine:
    """Auditable local decision boundary; replaceable by a JEV service later."""

    def decide(self, observation: Observation) -> DecisionRecord:
        payload = json.dumps(observation.__dict__, sort_keys=True).encode()
        input_hash = hashlib.sha256(payload).hexdigest()
        reasons: list[str] = []
        if observation.momentum > 0.001 and observation.volume_ratio >= 1.25 and observation.return_lookback > -0.01:
            decision, confidence = Decision.ACCEPT, min(0.99, 0.55 + observation.volume_ratio / 10)
            reasons.extend(["positive short-term momentum", "volume expansion", "price not materially below lookback"])
        elif observation.momentum > 0:
            decision, confidence = Decision.WATCH, 0.52
            reasons.append("movement is positive but flow confirmation is incomplete")
        else:
            decision, confidence = Decision.REJECT, 0.70
            reasons.append("no positive momentum setup")
        return DecisionRecord(observation.product_id, decision, confidence, tuple(reasons), input_hash)

    def sell_gate(self, observation: Observation, position: Position, context: dict | None = None) -> tuple[bool, str]:
        if observation.momentum < -0.002 and observation.volume_ratio >= 1.25:
            return True, "negative momentum with volume expansion"
        return False, "no deterministic sell-pressure trigger"

    def decide_signal(self, signal: dict, product_id: str) -> DecisionRecord:
        """Evaluate a rich feature state while retaining the simple Jev-compatible API."""
        if "timeframes" in signal:
            frames = signal["timeframes"]
            score = int(signal.get("trend_score", 0))
            volume_ratio = float(frames["1m"]["volume_ratio"])
            if signal.get("entry_signal") and score >= 6 and volume_ratio >= 1.10:
                payload = json.dumps(signal, sort_keys=True).encode()
                return DecisionRecord(product_id, Decision.ACCEPT, min(0.95, 0.60 + score / 20), ("multi-timeframe trend alignment", "volume confirmation"), hashlib.sha256(payload).hexdigest())
            if score > 0:
                payload = json.dumps(signal, sort_keys=True).encode()
                return DecisionRecord(product_id, Decision.WATCH, 0.55, ("trend is positive but setup confirmation is incomplete",), hashlib.sha256(payload).hexdigest())
        observation = Observation(
            product_id,
            float(signal["timeframes"]["1m"]["close"]),
            float(signal["timeframes"]["1m"]["return_lookback"]),
            float(signal["timeframes"]["1m"]["volume_ratio"]),
            float(signal["timeframes"]["1m"]["atr"]) / float(signal["timeframes"]["1m"]["close"]),
            float(signal["timeframes"]["1m"]["macd_histogram"]) / float(signal["timeframes"]["1m"]["close"]),
        )
        result = self.decide(observation)
        digest = hashlib.sha256(json.dumps(signal, sort_keys=True).encode()).hexdigest()
        return replace(result, input_hash=digest)


class HttpJevDecisionEngine(JevDecisionEngine):
    """Real-call adapter. The endpoint must return decision/disposition and optional sell."""

    def __init__(self, url: str | None = None, api_key: str | None = None, timeout: float | None = None):
        self.url = url or os.getenv("JEV_API_URL", "").strip()
        self.api_key = api_key or os.getenv("TYPESAFE_API_KEY", os.getenv("JEV_API_KEY", "")).strip()
        self.timeout = timeout or float(os.getenv("JEV_TIMEOUT_SECONDS", "30"))
        self.call_log: list[dict] = []
        if not self.url:
            raise ValueError("JEV_API_URL is required for JEV_MODE=HTTP")

    def _call(self, payload: dict) -> dict:
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", "X-JEV-Model": os.getenv("JEV_MODEL", "jev-1.13.0")}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.url, body, headers=headers, method="POST")
        result = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    result = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
                time.sleep(1.0 * (attempt + 1))
        if not isinstance(result, dict):
            raise ValueError("JEV endpoint returned a non-object response")
        self.call_log.append({"request": payload, "response": result})
        return result

    def decide(self, observation: Observation) -> DecisionRecord:
        return self._decide_state({"action": "ENTRY", "observation": observation.__dict__}, observation.product_id)

    def _decide_state(self, state_payload: dict, product_id: str) -> DecisionRecord:
        state = json.dumps(state_payload, sort_keys=True)
        request = {
            "state": state,
            "model": os.getenv("JEV_MODEL", "jev-1.13.0"),
            "questions": {
                "disposition": {
                    "type": "choice",
                    "instructions": "Should this observed BTC/ETH setup be bought at the next available execution point? Use only the supplied state. Return REJECT when evidence is insufficient.",
                    "criteria": {
                        "ACCEPT": "The setup has coherent positive momentum and volume confirmation.",
                        "WATCH": "The setup is interesting but confirmation is incomplete.",
                        "REJECT": "The setup is adverse, unclear, or insufficient for a buy.",
                    },
                },
                "setup_quality": {
                    "type": "score",
                    "instructions": "Score the quality of this short-term trading setup.",
                    "criteria": ["Poor or adverse", "Mixed or uncertain", "Strong and confirmed"],
                },
            },
        }
        result = self._call(request)
        answers = result.get("answers", {})
        disposition = answers.get("disposition", {})
        raw = str(disposition.get("choice", result.get("decision", "REJECT"))).upper()
        decision = Decision(raw) if raw in {item.value for item in Decision} else Decision.REJECT
        quality = answers.get("setup_quality", {})
        reasons = (f"TypeSafe disposition={raw}", f"setup_quality={quality.get('score', 'unknown')}")
        payload = json.dumps(state_payload, sort_keys=True).encode()
        return DecisionRecord(product_id, decision, float(disposition.get("confidence", 0)), reasons, hashlib.sha256(payload).hexdigest())

    def decide_signal(self, signal: dict, product_id: str) -> DecisionRecord:
        return self._decide_state(signal, product_id)

    def sell_gate(self, observation: Observation, position: Position, context: dict | None = None) -> tuple[bool, str]:
        position_payload = {**position.__dict__, "opened_at": position.opened_at.isoformat()}
        request = {
            "state": json.dumps({"action": "SELL_GATE", "observation": observation.__dict__, "position": position_payload, "cost_context": context or {}}, sort_keys=True),
            "model": os.getenv("JEV_MODEL", "jev-1.13.0"),
            "questions": {
                "sell_pressure": {
                    "type": "choice",
                    "instructions": "Should this open position be sold now because of observed sell pressure or deteriorating structure? Use only the supplied state.",
                    "criteria": {
                        "SELL": "Sell pressure or structure deterioration is sufficient to exit.",
                        "HOLD": "No sufficient sell-pressure evidence; continue holding.",
                    },
                }
            },
        }
        result = self._call(request)
        answer = result.get("answers", {}).get("sell_pressure", {})
        choice = str(answer.get("choice", "HOLD")).upper()
        return choice == "SELL", f"TypeSafe sell_pressure={choice}"
