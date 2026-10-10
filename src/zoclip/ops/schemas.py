from typing import Literal

from zoclip.credits.schemas import StrictModel


class ComponentUsage(StrictModel):
    component: Literal["deepgram", "gemini_input", "gemini_output", "render", "storage"]
    unit: Literal["minute", "token", "cpu_second", "gb_day"]
    units: int
    actual_usd: str


class Economics(StrictModel):
    assumptions_version: str
    assumptions_sha256: str
    rate_source: str
    usd_pkr: str
    vps_allocated_usd: str
    net_pkr: str
    modeled_cost_pkr: str
    margin: str | None
    below_target: bool | None


class OperationReport(StrictModel):
    start: str
    end: str
    usage: list[ComponentUsage]
    actual_usd: str
    failed_reservation_cost_usd: str
    held_or_unknown_usd_all_periods: str
    gross_paisa: int
    reversed_paisa: int
    fee_paisa: int
    job_states: dict[str, int]
    media_materialized_bytes: int
    media_reserved_bytes: int
    disk_free_bytes: int
    oldest_pending_outbox_at: str | None
    economics: Economics | None
    limitations: str
