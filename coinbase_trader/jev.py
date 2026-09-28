from __future__ import annotations

import hashlib
import json
import os
import urllib.request

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

    def sell_gate(self, observation: Observation, position: Position) -> tuple[bool, str]:
        if observation.momentum < -0.002 and observation.volume_ratio >= 1.25:
            return True, "negative momentum with volume expansion"
        return False, "no deterministic sell-pressure trigger"


class HttpJevDecisionEngine(JevDecisionEngine):
    """Real-call adapter. The endpoint must return decision/disposition and optional sell."""

    def __init__(self, url: str | None = None, api_key: str | None = None, timeout: float | None = None):
        self.url = url or os.getenv("JEV_API_URL", "").strip()
        self.api_key = api_key or os.getenv("JEV_API_KEY", "").strip()
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
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise ValueError("JEV endpoint returned a non-object response")
        self.call_log.append({"request": payload, "response": result})
        return result

    def decide(self, observation: Observation) -> DecisionRecord:
        result = self._call({"action": "ENTRY", "observation": observation.__dict__})
        raw = str(result.get("decision", result.get("disposition", "REJECT"))).upper()
        decision = Decision(raw) if raw in Decision else Decision.REJECT
        reasons = tuple(str(item) for item in result.get("reasons", ["real JEV response"]))
        payload = json.dumps(observation.__dict__, sort_keys=True).encode()
        return DecisionRecord(observation.product_id, decision, float(result.get("confidence", 0)), reasons, hashlib.sha256(payload).hexdigest())

    def sell_gate(self, observation: Observation, position: Position) -> tuple[bool, str]:
        position_payload = {**position.__dict__, "opened_at": position.opened_at.isoformat()}
        result = self._call({"action": "SELL_GATE", "observation": observation.__dict__, "position": position_payload})
        sell = bool(result.get("sell", result.get("exit", False)))
        return sell, str(result.get("reason", "real JEV sell-pressure response"))
