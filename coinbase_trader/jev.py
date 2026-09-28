from __future__ import annotations

import hashlib
import json

from .models import Decision, DecisionRecord, Observation


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

