from pydantic import BaseModel, ConfigDict
from typing import Dict, Any

class BasePayload(BaseModel):
    """Base class for all airline API payloads using Pydantic for validation."""
    model_config = ConfigDict(populate_by_name=True)
    
    def to_dict(self) -> Dict[str, Any]:
        """Converts the model to a dictionary, ensuring types are JSON-serializable (e.g. dates to strings)."""
        return self.model_dump(exclude_none=True, mode="json", by_alias=True)
