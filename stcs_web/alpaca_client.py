"""
STCS Alpaca HTTP Command Client.

This module provides a client for sending telescope commands via the
existing STCS V1 Alpaca HTTP server (port 11111).

Commands supported:
- slewtocoordinatesasync: Go-To target (async)
- slewtocoordinates: Go-To target (sync - not used)
- abortslew: Abort current slew
- synctocoordinates: Sync coordinates (calibration)
- tracking: Set tracking ON/OFF
- connected: Connection management

WHY this exists:
The browser must never speak hardware protocols directly. The existing
STCS V1 Alpaca server already implements command validation, safety
interlocks, and routes commands through MotionState/SlewEngine.
This client reuses that exact path instead of creating a parallel one.
"""

import logging
import os
import time
import urllib.parse
import urllib.request
import json
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("AlpacaClient")


class AlpacaCommandStatus(Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    NOT_CONNECTED = "NOT_CONNECTED"


@dataclass
class AlpacaCommandResult:
    """Result of a command sent to the STCS Alpaca server."""
    status: AlpacaCommandStatus
    command: str
    message: str
    error_number: int = 0
    error_message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class AlpacaClient:
    """
    HTTP client for sending commands to the STCS V1 Alpaca server.

    Uses the existing Alpaca REST API which routes through the
    SlewEngine/MotionState safety layer.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        timeout: float = 10.0,
        client_id: int = 1,
    ):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}/api/v1/telescope/0"
        self.timeout = timeout
        self.client_id = client_id
        self._transaction_id = 0

    def _next_transaction_id(self) -> int:
        self._transaction_id += 1
        return self._transaction_id

    def _send_put(self, method: str, params: Dict[str, Any]) -> AlpacaCommandResult:
        """Send a PUT request to the Alpaca telescope endpoint."""
        url = f"{self.base_url}/{method}"
        tid = self._next_transaction_id()

        # Build form data with required Alpaca parameters
        form_data = {
            "ClientID": str(self.client_id),
            "ClientTransactionID": str(tid),
        }
        form_data.update(params)

        data = urllib.parse.urlencode(form_data).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="PUT")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            error_number = body.get("ErrorNumber", 0)
            error_message = body.get("ErrorMessage", "")

            if error_number == 0:
                return AlpacaCommandResult(
                    status=AlpacaCommandStatus.SUCCESS,
                    command=method,
                    message="Command accepted",
                    details=body,
                )
            else:
                return AlpacaCommandResult(
                    status=AlpacaCommandStatus.ERROR,
                    command=method,
                    message=error_message or f"Alpaca error {error_number}",
                    error_number=error_number,
                    error_message=error_message,
                    details=body,
                )

        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
                error_number = body.get("ErrorNumber", e.code)
                error_message = body.get("ErrorMessage", str(e))
            except Exception:
                error_number = e.code
                error_message = str(e)
            return AlpacaCommandResult(
                status=AlpacaCommandStatus.ERROR,
                command=method,
                message=f"HTTP {e.code}: {error_message}",
                error_number=error_number,
                error_message=error_message,
            )
        except urllib.error.URLError as e:
            return AlpacaCommandResult(
                status=AlpacaCommandStatus.NOT_CONNECTED,
                command=method,
                message=f"Connection failed: {e.reason}",
                error_number=0,
                error_message=str(e.reason),
            )
        except Exception as e:
            return AlpacaCommandResult(
                status=AlpacaCommandStatus.ERROR,
                command=method,
                message=f"Request failed: {e}",
                error_number=0,
                error_message=str(e),
            )

    def _send_get(self, property_name: str) -> AlpacaCommandResult:
        """Send a GET request to the Alpaca telescope endpoint."""
        url = f"{self.base_url}/{property_name}?ClientID={self.client_id}&ClientTransactionID={self._next_transaction_id()}"

        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            error_number = body.get("ErrorNumber", 0)
            if error_number == 0:
                return AlpacaCommandResult(
                    status=AlpacaCommandStatus.SUCCESS,
                    command=f"get_{property_name}",
                    message="OK",
                    details=body,
                )
            else:
                return AlpacaCommandResult(
                    status=AlpacaCommandStatus.ERROR,
                    command=f"get_{property_name}",
                    message=body.get("ErrorMessage", f"Error {error_number}"),
                    error_number=error_number,
                    error_message=body.get("ErrorMessage", ""),
                    details=body,
                )
        except Exception as e:
            return AlpacaCommandResult(
                status=AlpacaCommandStatus.ERROR,
                command=f"get_{property_name}",
                message=f"GET failed: {e}",
                error_number=0,
                error_message=str(e),
            )

    # ─── Convenience Command Methods ───

    def slew_to_coordinates_async(self, ra_deg: float, dec_deg: float) -> AlpacaCommandResult:
        """Start an async slew to target coordinates (RA in degrees, DEC in degrees)."""
        # Alpaca expects RA in hours, DEC in degrees
        ra_hours = ra_deg / 15.0
        return self._send_put("slewtocoordinatesasync", {
            "RightAscension": str(ra_hours),
            "Declination": str(dec_deg),
        })

    def slew_to_coordinates(self, ra_deg: float, dec_deg: float) -> AlpacaCommandResult:
        """Start a sync slew to target coordinates."""
        ra_hours = ra_deg / 15.0
        return self._send_put("slewtocoordinates", {
            "RightAscension": str(ra_hours),
            "Declination": str(dec_deg),
        })

    def abort_slew(self) -> AlpacaCommandResult:
        """Abort the current slew."""
        return self._send_put("abortslew", {})

    def sync_to_coordinates(self, ra_deg: float, dec_deg: float) -> AlpacaCommandResult:
        """Sync telescope coordinates to target (calibration)."""
        ra_hours = ra_deg / 15.0
        return self._send_put("synctocoordinates", {
            "RightAscension": str(ra_hours),
            "Declination": str(dec_deg),
        })

    def set_tracking(self, enabled: bool) -> AlpacaCommandResult:
        """Enable or disable sidereal tracking."""
        return self._send_put("tracking", {"Tracking": "true" if enabled else "false"})

    def set_connected(self, connected: bool) -> AlpacaCommandResult:
        """Set Alpaca connection state."""
        return self._send_put("connected", {"Connected": "true" if connected else "false"})

    def get_slewing(self) -> AlpacaCommandResult:
        """Check if telescope is currently slewing."""
        return self._send_get("slewing")

    def get_tracking(self) -> AlpacaCommandResult:
        """Check if tracking is enabled."""
        return self._send_get("tracking")

    def get_at_park(self) -> AlpacaCommandResult:
        """Check if telescope is at park position."""
        return self._send_get("atpark")

    def get_at_home(self) -> AlpacaCommandResult:
        """Check if telescope is at home position."""
        return self._send_get("athome")


# Module-level singleton
_alpaca_client: Optional[AlpacaClient] = None


def get_alpaca_client() -> AlpacaClient:
    """Get or create the global Alpaca client."""
    global _alpaca_client
    if _alpaca_client is None:
        host = os.environ.get("ALPACA_HOST", "127.0.0.1")
        port = int(os.environ.get("ALPACA_PORT", "11111"))
        _alpaca_client = AlpacaClient(host=host, port=port)
    return _alpaca_client