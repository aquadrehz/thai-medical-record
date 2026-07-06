from pydantic import BaseModel, Field
from typing import Any, Optional

class WorkflowState(BaseModel):
    """State schema for the medical record processing workflow."""
    raw_input: Optional[Any] = None
    input_text: Optional[str] = None
    task_type: Optional[str] = None  # "human_to_json" or "json_to_human"
    completeness_score: int = 0
    missing_details: Optional[str] = None
    output_result: Optional[Any] = None
    completeness_result: Optional["CompletenessResult"] = None
    standards_output: Optional["StandardsOutput"] = None
    human_translation: Optional["HumanTranslationOutput"] = None
    loop_count: int = 0

class CompletenessResult(BaseModel):
    """Schema for the LLM completeness assessor."""
    is_complete: bool = Field(
        description="True if the patient record text has enough details to format into HL7 FHIR / TMT / TMLT / SNOMED / ICD-10 JSON (e.g. at least basic demographics, disease/procedure details, or medication names). False if key information is missing or too vague."
    )
    score: int = Field(
        description="Completeness score from 0 (completely vague/empty) to 100 (fully detailed)."
    )
    missing_details: str = Field(
        description="A concise question or list of missing details if is_complete is False. If is_complete is True, keep this empty."
    )

class StandardsOutput(BaseModel):
    """Schema for the LLM standards translator."""
    fhir: Optional[dict[str, Any]] = Field(
        default=None,
        description="The HL7 FHIR JSON payload (e.g. Patient, MedicationRequest, or Observation resources) if suitable."
    )
    tmt: Optional[dict[str, Any]] = Field(
        default=None,
        description="The Thai Medicines Terminology (TMT) JSON coding if suitable."
    )
    snomed: Optional[dict[str, Any]] = Field(
        default=None,
        description="The SNOMED CT JSON coding if suitable."
    )
    icd10: Optional[dict[str, Any]] = Field(
        default=None,
        description="The ICD-10/ICD-11 JSON coding if suitable."
    )
    tmlt: Optional[dict[str, Any]] = Field(
        default=None,
        description="The Thai Medical Laboratory Terminology (TMLT) JSON coding if suitable."
    )


class HumanTranslationOutput(BaseModel):
    """Schema for the LLM human language translator."""
    translation: str = Field(
        description="The human-readable translation of the medical record in the requested language (default to English)."
    )

WorkflowState.model_rebuild()

