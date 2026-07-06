import base64
import json
from google.adk.events.event import Event
from medical_record_agents.workflow import parse_input, determine_task

class DummyContext:
    def __init__(self):
        self.state = {}

def test_parse_input_string():
    ctx = DummyContext()
    event = parse_input(ctx, "Patient Somchai has fever")
    assert event.actions.state_delta["task_type"] == "human_to_json"
    assert event.actions.state_delta["input_text"] == "Patient Somchai has fever"

def test_parse_input_plain_json():
    ctx = DummyContext()
    payload = {"resourceType": "Patient", "id": "1"}
    event = parse_input(ctx, payload)
    assert event.actions.state_delta["task_type"] == "json_to_human"
    assert event.actions.state_delta["raw_input"] == payload

def test_parse_input_base64_pubsub():
    ctx = DummyContext()
    inner_payload = {"resourceType": "Patient", "id": "th-patient-1"}
    inner_json = json.dumps(inner_payload)
    encoded = base64.b64encode(inner_json.encode("utf-8")).decode("utf-8")
    pubsub_msg = {"data": encoded}
    
    event = parse_input(ctx, pubsub_msg)
    assert event.actions.state_delta["task_type"] == "json_to_human"
    assert event.actions.state_delta["raw_input"] == inner_payload
