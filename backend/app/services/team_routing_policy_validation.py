from __future__ import annotations

from backend.app.models.governance import AIRoutingPoliciesUpdateRequest


def validate_routing_update(payload: AIRoutingPoliciesUpdateRequest) -> None:
    for item in payload.items:
        stage = item.stage.strip()
        if item.model_name and item.model_name.strip() and not item.connector_id:
            raise ValueError(f"{stage} 阶段只填写了模型名但没有 connector_id。请显式选择连接器。")
