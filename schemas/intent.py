from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    VISIT = "visit"
    INQUIRY = "inquiry"
    COMPLAINT = "complaint"
    DIRECT = "direct"
    LABRESULTS = "labresults"


class RefinedQuery(BaseModel):

    query: str = Field(
        ...,
        min_length=1,
        description="Exact standardized name of ONE distinct lab test, panel, or bundle. Do not include a semantic description or explanation."
    )

    aliases: List[str] = Field(
        ...,
        min_length=1,
        description="Alternative names, abbreviations, Arabic and Franco-Arab terms for the exact same test."
    )

    keywords: List[str] = Field(
        ...,
        min_length=2,
        description="2-5 distinctive English search terms for the test."
    )

    description: str = Field(
        ...,
        min_length=1,
        description="Short medically accurate English description of the test purpose."
    )


class IntentResponse(BaseModel):

    intent: IntentType = Field(
        ...,
        description="The main intent classification of the user's message."
    )

    refined_queries: List[RefinedQuery] = Field(
        ...,
        description="One RefinedQuery per requested lab test/panel/bundle. Empty list [] if no lab retrieval is needed. The key must always be included."
    )

    is_bundle_query: bool = Field(
        ...,
        description="True ONLY if the user is explicitly asking about bundles, checkup offers, or packages."
    )