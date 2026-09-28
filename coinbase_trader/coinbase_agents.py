from __future__ import annotations

import json
import os
import subprocess


class CoinbaseAgentsCLI:
    """Single boundary for Coinbase access through the Coinbase for Agents CLI."""

    def __init__(self, binary: str | None = None, timeout: float = 30):
        self.binary = binary or os.getenv("COINBASE_CLI_BIN", "coinbase")
        self.timeout = timeout

    def run(self, *args: str) -> object:
        command = [self.binary, *args]
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=self.timeout)
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
            raise RuntimeError(f"Coinbase for Agents CLI failed ({' '.join(command[:3])}): {detail}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValueError("Coinbase for Agents CLI did not return JSON") from error
