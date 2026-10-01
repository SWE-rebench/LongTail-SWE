def instance_image_tag(instance_id: str, prefix: str = "longtail/") -> str:
    """Docker repository names must be lowercase."""
    return f"{prefix}{instance_id.lower()}"
