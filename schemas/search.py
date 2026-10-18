from pydantic import BaseModel


class SearchResult(BaseModel):
    id: int
    name: str
    score: float
    source: str
