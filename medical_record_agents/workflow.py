import base64
import json
import os
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.workflow import Workflow, START
from google.genai import types as genai_types
from google.adk.models import Gemini

from medical_record_agents import config
from medical_record_agents.types import (
    CompletenessResult,
    StandardsOutput,
    HumanTranslationOutput,
    WorkflowState,
)

STANDARDS_CONTENT = ""
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths_to_try = [
        os.path.join(current_dir, "..", "docs", "standards.md"),
        os.path.join(current_dir, "docs", "standards.md"),
        "/code/docs/standards.md",
        "docs/standards.md",
    ]
    for path in paths_to_try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                STANDARDS_CONTENT = f.read()
                break
except Exception:
    pass

if not STANDARDS_CONTENT:
    STANDARDS_CONTENT = "HL7 FHIR, SNOMED CT, ICD-10, TMT, and TMLT clinical coding standard structures."



def parse_input(ctx: Context, node_input: Any) -> Event:
    """Parses raw input from JSON events, decoding base64 if needed."""
    raw_str = ""
    raw_data = None

    if isinstance(node_input, dict):
        raw_data = node_input
    elif hasattr(node_input, "parts") and node_input.parts:
        part_text = node_input.parts[0].text
        try:
            raw_data = json.loads(part_text)
        except Exception:
            raw_str = part_text
    elif isinstance(node_input, str):
        try:
            raw_data = json.loads(node_input)
        except Exception:
            raw_str = node_input
    else:
        raw_str = str(node_input)

    # If it is a dictionary, extract and check "data" key
    if isinstance(raw_data, dict):
        data_val = raw_data.get("data")
        if data_val:
            # Try to decode base64
            if isinstance(data_val, str):
                try:
                    decoded = base64.b64decode(data_val).decode("utf-8")
                    try:
                        data_val = json.loads(decoded)
                    except Exception:
                        data_val = decoded
                except Exception:
                    pass  # Not base64
        else:
            data_val = raw_data
    else:
        data_val = raw_str if raw_str else raw_data

    # Check if data_val is a dict or string representing dict (FHIR/Standards JSON)
    if isinstance(data_val, dict):
        return Event(
            output=data_val,
            state={"raw_input": data_val, "task_type": "json_to_human"},
        )
    elif isinstance(data_val, str):
        cleaned = data_val.strip()
        if (cleaned.startswith("{") and cleaned.endswith("}")) or (
            cleaned.startswith("[") and cleaned.endswith("]")
        ):
            try:
                parsed_json = json.loads(cleaned)
                return Event(
                    output=parsed_json,
                    state={"raw_input": parsed_json, "task_type": "json_to_human"},
                )
            except Exception:
                pass

    return Event(
        output=str(data_val),
        state={"input_text": str(data_val), "task_type": "human_to_json"},
    )


def determine_task(ctx: Context, node_input: Any) -> Event:
    """Routes the execution path based on the input type."""
    task_type = ctx.state.get("task_type")
    return Event(output=node_input, route=task_type)


# LLM agent to analyze the clinical completeness of the text input
completeness_assessor = LlmAgent(
    name="completeness_assessor",
    model=Gemini(model=config.MODEL_NAME),
    instruction=(
        "You are a medical record quality assessor.\n"
        "Analyze the provided medical record text and determine if there is enough clinical information "
        "(such as patient demographics, symptoms, diagnoses, or medication names/dosages) "
        "to format into standard HL7 FHIR, SNOMED CT, ICD-10, or TMT JSON payloads.\n"
        "Provide a completeness score from 0 to 100.\n"
        "If the input is vague or missing crucial details, set is_complete to False and detail the missing details."
    ),
    output_schema=CompletenessResult,
    output_key="completeness_result",
)



# LLM agent to analyze the clinical completeness of JSON input
json_completeness_assessor = LlmAgent(
    name="json_completeness_assessor",
    model=Gemini(model=config.MODEL_NAME),
    instruction=(
        "You are a medical record quality assessor.\n"
        "Analyze the provided medical record JSON payload (which may conform to HL7 FHIR, SNOMED, ICD-10, TMT, or TMLT) "
        "and determine if it contains enough clinical information (such as patient diagnostics, symptoms, codes, or medication name/dosages) "
        "to translate back to clear human language.\n"
        "Note: The input may be a dictionary containing 'original_json' (the standard medical JSON) and 'additional_details' (text details provided by the user). Combine both when assessing completeness.\n"
        "Provide a completeness score from 0 to 100.\n"
        "If the JSON is too vague, empty, lacks crucial clinical keys, or is otherwise incomplete, set is_complete to False and explain what details are missing."
    ),
    output_schema=CompletenessResult,
    output_key="completeness_result",
)


def route_completeness(ctx: Context, node_input: dict) -> Event:
    """Routes to HITL (vague) or Translation (complete) based on assessor output."""
    score = node_input.get("score", 0)
    is_complete = node_input.get("is_complete", False)

    # Save details to state
    ctx.state["completeness_score"] = score
    ctx.state["missing_details"] = node_input.get("missing_details")

    if is_complete and score >= config.COMPLETENESS_THRESHOLD:
        return Event(output=ctx.state.get("input_text"), route="complete")
    else:
        return Event(output=node_input.get("missing_details"), route="vague")


def route_json_completeness(ctx: Context, node_input: dict) -> Event:
    """Routes to HITL (vague) or Translation (complete) for JSON payloads."""
    score = node_input.get("score", 0)
    is_complete = node_input.get("is_complete", False)

    ctx.state["completeness_score"] = score
    ctx.state["missing_details"] = node_input.get("missing_details")

    if is_complete and score >= config.COMPLETENESS_THRESHOLD:
        return Event(output=ctx.state.get("raw_input"), route="complete")
    else:
        return Event(output=node_input.get("missing_details"), route="vague")


async def request_details(ctx: Context, node_input: str):
    """Yields RequestInput to pause workflow for doctor feedback and loops back once resumed."""
    loop_count = ctx.state.get("loop_count", 0) + 1
    ctx.state["loop_count"] = loop_count
    interrupt_id = f"clarify_{loop_count}"

    if not ctx.resume_inputs or interrupt_id not in ctx.resume_inputs:
        yield RequestInput(
            interrupt_id=interrupt_id,
            message=(
                f"The medical record is too vague (Score: {ctx.state.get('completeness_score')}/100).\n"
                f"Missing Details needed: {node_input}\n"
                f"Please provide the missing details to continue:"
            ),
        )
        return

    # Once resumed, append new details to the original text input
    additional_details = ctx.resume_inputs[interrupt_id]
    updated_text = (
        f"{ctx.state.get('input_text')}\n[Additional Details]: {additional_details}"
    )
    ctx.state["input_text"] = updated_text

    yield Event(output=updated_text, route="resumed")


async def request_json_details(ctx: Context, node_input: str):
    """Yields RequestInput to pause workflow for JSON feedback and loops back once resumed."""
    loop_count = ctx.state.get("loop_count", 0) + 1
    ctx.state["loop_count"] = loop_count
    interrupt_id = f"clarify_json_{loop_count}"

    if not ctx.resume_inputs or interrupt_id not in ctx.resume_inputs:
        yield RequestInput(
            interrupt_id=interrupt_id,
            message=(
                f"The JSON medical record is incomplete (Score: {ctx.state.get('completeness_score')}/100).\n"
                f"Missing Details needed: {node_input}\n"
                f"Please provide the missing details to continue:"
            ),
        )
        return

    # Once resumed, update raw_input to a dict containing original_json and the additional details
    additional_details = ctx.resume_inputs[interrupt_id]
    existing_input = ctx.state.get("raw_input")
    if isinstance(existing_input, dict) and "original_json" in existing_input:
        old_details = existing_input.get("additional_details", "")
        combined_details = f"{old_details}\n{additional_details}" if old_details else additional_details
        ctx.state["raw_input"] = {
            "original_json": existing_input["original_json"],
            "additional_details": combined_details,
        }
    else:
        ctx.state["raw_input"] = {
            "original_json": existing_input,
            "additional_details": additional_details,
        }

    yield Event(output=ctx.state["raw_input"], route="resumed")


# LLM agent to convert human readable clinical text to standards JSON
standards_translator = LlmAgent(
    name="standards_translator",
    model=Gemini(model=config.MODEL_NAME),
    instruction=(
        "You are an expert medical coder.\n"
        "Convert the provided clinical text into standard medical JSON payloads matching the formats and schemas specified below:\n\n"
        f"{STANDARDS_CONTENT}\n\n"
        "- Assess which standard(s) (HL7 FHIR, SNOMED CT, ICD-10, TMT, TMLT) are suitable for the clinical text.\n"
        "- If specific standards are mentioned in the clinical text, prioritize matching those first.\n"
        "- Map the clinical text into one or more standards and structure them as a single JSON object where each standard is a top-level key (e.g., 'fhir', 'tmt', 'snomed', 'icd10', 'tmlt').\n"
        "Ensure the output is valid JSON wrapped inside a ```json ... ``` code block."
    ),
)


def format_standards_output(ctx: Context, node_input: Any) -> Event:
    """Formats the final JSON standards mapping for clinical storage and UI rendering."""
    text_content = str(node_input)
    
    # Extract JSON block if present
    if "```json" in text_content:
        json_str = text_content.split("```json")[1].split("```")[0].strip()
    elif "```" in text_content:
        json_str = text_content.split("```")[1].split("```")[0].strip()
    else:
        json_str = text_content.strip()

    try:
        standards_dict = json.loads(json_str)
    except Exception:
        standards_dict = {"raw_response": text_content}

    # Clean up empty sub-dictionaries if any
    standards_dict = {
        k: v for k, v in standards_dict.items() if v != {} and v is not None
    }

    output_str = json.dumps(standards_dict, indent=2, ensure_ascii=False)
    return Event(
        output=standards_dict,
        content=genai_types.Content(
            role="model",
            parts=[
                genai_types.Part.from_text(
                    text=f"### Mapped Medical Standards JSON\n```json\n{output_str}\n```"
                )
            ],
        ),
        state={"output_result": standards_dict},
    )


# LLM agent to convert medical standards JSON back to human language
human_translator = LlmAgent(
    name="human_translator",
    model=Gemini(model=config.MODEL_NAME),
    instruction=(
        "You are a clinical interpreter.\n"
        "Translate the provided medical record JSON payload (which may conform to HL7 FHIR, SNOMED CT, ICD-10, TMT, or TMLT) "
        "back into clear, readable human language.\n"
        f"Refer to the following medical standard definitions if needed:\n\n{STANDARDS_CONTENT}\n\n"
        "If the input is a dictionary containing 'original_json' and 'additional_details', incorporate both the JSON data and the additional text details into the final interpretation.\n"
        "By default, translate the record to English. However, if the user requested a specific language (e.g. Thai), "
        "translate to that language instead.\n"
        "Make the explanation formatted, professional, and easy for a clinician to review."
    ),
    output_schema=HumanTranslationOutput,
    output_key="human_translation",
)


def format_human_output(ctx: Context, node_input: dict) -> Event:
    """Formats the translated human language output for display."""
    translation_str = node_input.get("translation", "")
    return Event(
        output=translation_str,
        content=genai_types.Content(
            role="model",
            parts=[
                genai_types.Part.from_text(
                    text=f"### Clinical Translation\n{translation_str}"
                )
            ],
        ),
        state={"output_result": translation_str},
    )


# Wire up the ADK 2.0 Graph Workflow
root_workflow = Workflow(
    name="thai_medical_record_workflow",
    state_schema=WorkflowState,
    edges=[
        # START and initial parse/routing
        (START, parse_input),
        (parse_input, determine_task),
        # Pathway A: Text -> Standards JSON
        (determine_task, {"human_to_json": completeness_assessor, "json_to_human": json_completeness_assessor}),
        
        # Text completeness routing
        (completeness_assessor, route_completeness),
        (route_completeness, {"vague": request_details, "complete": standards_translator}),
        (request_details, {"resumed": completeness_assessor}),  # Loop back on resume
        (standards_translator, format_standards_output),
        
        # Pathway B: Standards JSON -> Human Text
        (json_completeness_assessor, route_json_completeness),
        (route_json_completeness, {"vague": request_json_details, "complete": human_translator}),
        (request_json_details, {"resumed": json_completeness_assessor}),  # Loop back on resume
        (human_translator, format_human_output),
    ],
)

