from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Shared response base: snake_case fields, camelCase wire aliases."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)
