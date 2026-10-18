from pydantic import BaseModel, Field


class TestGenerationResult(BaseModel):
    description: str = Field(
        default="",
        description="Clear description of the laboratory service."
    )

    patient_instructions: str = Field(
        default="",
        description="Patient preparation or sample collection instructions."
    )

    keywords: list[str] = Field(
        default_factory=list,
        description="Important keywords related to the laboratory service."
    )

    alias_name: list[str] = Field(
        default_factory=list,
        description="Alternative names for the laboratory service in arabic and english."
    )

    duration: int = Field(
        default=24,
        description="Estimated duration of the laboratory service in hours."
    )

    sample_type: str = Field(
        default="دم",
        description="Type of sample required for the laboratory service."
    )

    @property
    def instructions(self) -> str:
        return self.patient_instructions

    @property
    def aliases(self) -> list[str]:
        return self.alias_name