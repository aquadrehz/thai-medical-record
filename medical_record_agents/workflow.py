import base64
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.workflow import Workflow, START, node
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
        "Write the missing_details explanation in Thai language by default.\n"
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
        "Write the missing_details explanation in Thai language by default.\n"
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


def _extract_details_from_resume(resume_val: Any) -> str:
    """Safely extracts the text response from a resume input dict or string."""
    if isinstance(resume_val, dict):
        if "result" in resume_val:
            return str(resume_val["result"])
        if "response" in resume_val:
            return str(resume_val["response"])
        if resume_val:
            return str(next(iter(resume_val.values())))
    return str(resume_val)


@node(rerun_on_resume=True)
async def request_details(ctx: Context, node_input: str):
    """Yields RequestInput to pause workflow for doctor feedback and loops back once resumed."""
    logger.warning(
        "[request_details] ENTERED. loop_count=%s, resume_inputs_keys=%s",
        ctx.state.get("loop_count"),
        list(ctx.resume_inputs.keys()) if ctx.resume_inputs else None,
    )

    # Scan resume_inputs for any clarify_* key (not clarify_json_*)
    matched_interrupt_id = None
    if ctx.resume_inputs:
        for key in ctx.resume_inputs:
            if key.startswith("clarify_") and not key.startswith("clarify_json_"):
                matched_interrupt_id = key
                break

    processed_list = ctx.state.get("processed_interrupts") or []

    if matched_interrupt_id and matched_interrupt_id not in processed_list:
        new_processed = list(processed_list) + [matched_interrupt_id]
        ctx.state["processed_interrupts"] = new_processed
        additional_details = _extract_details_from_resume(ctx.resume_inputs[matched_interrupt_id])
        updated_text = (
            f"{ctx.state.get('input_text')}\n[Additional Details]: {additional_details}"
        )
        ctx.state["input_text"] = updated_text
        logger.warning(
            "[request_details] Resumed with key '%s'. Routing 'resumed'.",
            matched_interrupt_id,
        )
        yield Event(
            output=updated_text,
            route="resumed",
            state={"input_text": updated_text, "processed_interrupts": new_processed}
        )
        return

    current_loop = ctx.state.get("loop_count", 0)
    new_loop = current_loop + 1
    ctx.state["loop_count"] = new_loop
    new_interrupt_id = f"clarify_{new_loop}"

    logger.warning(
        "[request_details] No resume match. Yielding RequestInput "
        "interrupt_id='%s', loop_count=%s",
        new_interrupt_id,
        new_loop,
    )
    yield RequestInput(
        interrupt_id=new_interrupt_id,
        message=(
            f"ข้อมูลบันทึกทางการแพทย์ยังไม่ครบถ้วน (คะแนนความสมบูรณ์: {ctx.state.get('completeness_score')}% / 100%)\n"
            f"รายละเอียดที่ยังขาดอยู่: {node_input}\n"
            f"กรุณากรอกข้อมูลเพิ่มเติมเพื่อดำเนินการต่อ:"
        ),
    )


@node(rerun_on_resume=True)
async def request_json_details(ctx: Context, node_input: str):
    """Yields RequestInput to pause workflow for JSON feedback and loops back once resumed."""
    logger.warning(
        "[request_json_details] ENTERED. loop_count=%s, resume_inputs_keys=%s",
        ctx.state.get("loop_count"),
        list(ctx.resume_inputs.keys()) if ctx.resume_inputs else None,
    )

    # Scan resume_inputs for any clarify_json_* key
    matched_interrupt_id = None
    if ctx.resume_inputs:
        for key in ctx.resume_inputs:
            if key.startswith("clarify_json_"):
                matched_interrupt_id = key
                break

    processed_list = ctx.state.get("processed_interrupts") or []

    if matched_interrupt_id and matched_interrupt_id not in processed_list:
        new_processed = list(processed_list) + [matched_interrupt_id]
        ctx.state["processed_interrupts"] = new_processed
        additional_details = _extract_details_from_resume(ctx.resume_inputs[matched_interrupt_id])
        existing_input = ctx.state.get("raw_input")
        if isinstance(existing_input, dict) and "original_json" in existing_input:
            old_details = existing_input.get("additional_details", "")
            combined_details = f"{old_details}\n{additional_details}" if old_details else additional_details
            new_input = {
                "original_json": existing_input["original_json"],
                "additional_details": combined_details,
            }
        else:
            new_input = {
                "original_json": existing_input,
                "additional_details": additional_details,
            }
        ctx.state["raw_input"] = new_input
        logger.warning(
            "[request_json_details] Resumed with key '%s'. Routing 'resumed'.",
            matched_interrupt_id,
        )
        yield Event(
            output=new_input,
            route="resumed",
            state={"raw_input": new_input, "processed_interrupts": new_processed}
        )
        return

    current_loop = ctx.state.get("loop_count", 0)
    new_loop = current_loop + 1
    ctx.state["loop_count"] = new_loop
    new_interrupt_id = f"clarify_json_{new_loop}"

    logger.warning(
        "[request_json_details] No resume match. Yielding RequestInput "
        "interrupt_id='%s', loop_count=%s",
        new_interrupt_id,
        new_loop,
    )
    yield RequestInput(
        interrupt_id=new_interrupt_id,
        message=(
            f"ข้อมูลทางการแพทย์ในรูปแบบ JSON ยังไม่ครบถ้วน (คะแนนความสมบูรณ์: {ctx.state.get('completeness_score')}% / 100%)\n"
            f"รายละเอียดที่ยังขาดอยู่: {node_input}\n"
            f"กรุณากรอกข้อมูลเพิ่มเติมเพื่อดำเนินการต่อ:"
        ),
    )


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
        "By default, translate the record to Thai. However, if the user requested a specific language (e.g. English), "
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


# LLM agent to generate a brief summary of clinical data in Thai
summary_generator = LlmAgent(
    name="summary_generator",
    model=Gemini(model=config.MODEL_NAME),
    instruction=(
        "You are a clinical secretary.\n"
        "Generate a brief, bulleted clinical summary of the accumulated medical data (text or JSON) in Thai language.\n"
        "Do not output raw JSON, just clean, readable bullet points of the patient details, symptoms, diagnoses, and treatments."
    ),
    output_key="summary_text",
)


@node(rerun_on_resume=True)
async def check_confirmation(ctx: Context, node_input: Any):
    """Asks the user to confirm the clinical summary, allowing correction or finalization."""
    logger.warning(
        "[check_confirmation] ENTERED. confirmed=%s, loop_count=%s, "
        "resume_inputs_keys=%s, resume_inputs=%s, node_input_type=%s",
        ctx.state.get("confirmed"),
        ctx.state.get("loop_count"),
        list(ctx.resume_inputs.keys()) if ctx.resume_inputs else None,
        ctx.resume_inputs,
        type(node_input).__name__,
    )

    if ctx.state.get("confirmed"):
        logger.warning("[check_confirmation] Already confirmed, routing 'confirmed'")
        yield Event(output=node_input, route="confirmed")
        return

    # --- Scan ALL resume_inputs for any confirm_* key ---
    matched_interrupt_id = None
    if ctx.resume_inputs:
        for key in ctx.resume_inputs:
            if key.startswith("confirm_"):
                matched_interrupt_id = key
                break

    processed_list = ctx.state.get("processed_interrupts") or []

    if (
        matched_interrupt_id
        and matched_interrupt_id not in processed_list
    ):
        logger.warning(
            "[check_confirmation] Found resume key '%s', processing...",
            matched_interrupt_id,
        )
        new_processed = list(processed_list) + [matched_interrupt_id]
        ctx.state["processed_interrupts"] = new_processed
        user_response = _extract_details_from_resume(
            ctx.resume_inputs[matched_interrupt_id]
        ).strip()
        user_response_lower = user_response.lower()
        logger.warning(
            "[check_confirmation] user_response='%s', lower='%s'",
            user_response,
            user_response_lower,
        )
        if user_response_lower in ["confirm", "yes", "ยืนยัน", "ok", "ตกลง", "y"]:
            ctx.state["confirmed"] = True
            logger.warning("[check_confirmation] User CONFIRMED. Routing 'confirmed'.")
            yield Event(
                output=node_input,
                route="confirmed",
                state={"confirmed": True, "processed_interrupts": new_processed}
            )
            return
        else:
            # User wants to correct/add details!
            ctx.state["confirmed"] = False
            task_type = ctx.state.get("task_type")
            state_delta = {"confirmed": False, "processed_interrupts": new_processed}
            if task_type == "human_to_json":
                updated_text = (
                    f"{ctx.state.get('input_text')}\n[Correction]: {user_response}"
                )
                ctx.state["input_text"] = updated_text
                state_delta["input_text"] = updated_text
            else:
                existing_input = ctx.state.get("raw_input")
                if isinstance(existing_input, dict) and "original_json" in existing_input:
                    old_details = existing_input.get("additional_details", "")
                    combined_details = f"{old_details}\n[Correction]: {user_response}" if old_details else user_response
                    new_input = {
                        "original_json": existing_input["original_json"],
                        "additional_details": combined_details,
                    }
                else:
                    new_input = {
                        "original_json": existing_input,
                        "additional_details": user_response,
                    }
                ctx.state["raw_input"] = new_input
                state_delta["raw_input"] = new_input
            logger.warning("[check_confirmation] User sent CORRECTION. Routing 'correction'.")
            yield Event(output=user_response, route="correction", state=state_delta)
            return

    # No resume match — issue a new RequestInput
    current_loop = ctx.state.get("loop_count", 0)
    new_loop = current_loop + 1
    ctx.state["loop_count"] = new_loop
    new_interrupt_id = f"confirm_{new_loop}"

    summary_text = str(node_input)
    logger.warning(
        "[check_confirmation] No resume match. Yielding RequestInput "
        "interrupt_id='%s', loop_count=%s",
        new_interrupt_id,
        new_loop,
    )
    yield RequestInput(
        interrupt_id=new_interrupt_id,
        message=(
            f"กรุณาตรวจสอบและยืนยันข้อมูลสรุปดังต่อไปนี้:\n\n"
            f"{summary_text}\n\n"
            f"หากข้อมูลถูกต้อง กรุณาพิมพ์ 'confirm' หรือ 'ยืนยัน' เพื่อยืนยันข้อมูล\n"
            f"หากมีข้อมูลต้องการแก้ไขหรือเพิ่มเติม กรุณาพิมพ์รายละเอียดเพื่อแก้ไข:"
        ),
    )


def determine_final_translation(ctx: Context, node_input: Any) -> Event:
    """Routes the execution to the appropriate translator node upon user confirmation."""
    task_type = ctx.state.get("task_type")
    
    if task_type == "human_to_json":
        return Event(output=ctx.state.get("input_text"), route=task_type)
    else:
        return Event(output=ctx.state.get("raw_input"), route=task_type)


def route_correction_task(ctx: Context, node_input: Any) -> Event:
    """Routes the execution back to the correct completeness assessor upon user correction."""
    task_type = ctx.state.get("task_type")
    
    if task_type == "human_to_json":
        return Event(output=ctx.state.get("input_text"), route=task_type)
    else:
        return Event(output=ctx.state.get("raw_input"), route=task_type)


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
        (route_completeness, {"vague": request_details, "complete": summary_generator}),
        (request_details, {"resumed": completeness_assessor}),  # Loop back on resume
        
        # Pathway B: Standards JSON -> Human Text
        (json_completeness_assessor, route_json_completeness),
        (route_json_completeness, {"vague": request_json_details, "complete": summary_generator}),
        (request_json_details, {"resumed": json_completeness_assessor}),  # Loop back on resume
        
        # Confirmation Stage
        (summary_generator, check_confirmation),
        (check_confirmation, {"confirmed": determine_final_translation, "correction": route_correction_task}),
        (determine_final_translation, {"human_to_json": standards_translator, "json_to_human": human_translator}),
        (route_correction_task, {"human_to_json": completeness_assessor, "json_to_human": json_completeness_assessor}),
        
        # Translators and Formatting Outputs
        (standards_translator, format_standards_output),
        (human_translator, format_human_output),
    ],
)

