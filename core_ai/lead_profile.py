from core_ai.customer_state import CustomerState


class LeadProfile(CustomerState):
    """
    Backward-compatible alias for CustomerState.

    Existing code can continue using LeadProfile while the
    platform migrates to CustomerState.
    """
    pass