# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for workflow helper functions.

These tests validate pure-function logic in the workflow module without
hitting any LLM or external service. They run fast and offline.
"""

import base64
import json

from medical_record_agents.workflow import (
    _extract_details_from_resume,
    determine_task,
    parse_input,
    route_completeness,
    route_json_completeness,
)


class DummyContext:
    """Minimal stand-in for google.adk.agents.context.Context."""

    def __init__(self, state: dict | None = None):
        self.state = state or {}


# ---------------------------------------------------------------------------
# parse_input
# ---------------------------------------------------------------------------


class TestParseInput:
    """Tests for parse_input() routing logic."""

    def test_plain_thai_text_routes_human_to_json(self):
        ctx = DummyContext()
        event = parse_input(ctx, "คนไข้ชายปวดหัวมาหลายวันแล้ว")
        assert event.actions.state_delta["task_type"] == "human_to_json"
        assert event.actions.state_delta["input_text"] == "คนไข้ชายปวดหัวมาหลายวันแล้ว"

    def test_english_text_routes_human_to_json(self):
        ctx = DummyContext()
        event = parse_input(ctx, "Patient Somchai has fever")
        assert event.actions.state_delta["task_type"] == "human_to_json"
        assert event.actions.state_delta["input_text"] == "Patient Somchai has fever"

    def test_dict_routes_json_to_human(self):
        ctx = DummyContext()
        payload = {"resourceType": "Patient", "id": "1"}
        event = parse_input(ctx, payload)
        assert event.actions.state_delta["task_type"] == "json_to_human"
        assert event.actions.state_delta["raw_input"] == payload

    def test_json_string_routes_json_to_human(self):
        ctx = DummyContext()
        payload = '{"resourceType": "Patient", "id": "th-patient-1"}'
        event = parse_input(ctx, payload)
        assert event.actions.state_delta["task_type"] == "json_to_human"
        assert event.actions.state_delta["raw_input"]["resourceType"] == "Patient"

    def test_base64_pubsub_message_decoded(self):
        ctx = DummyContext()
        inner_payload = {"resourceType": "Patient", "id": "th-patient-1"}
        inner_json = json.dumps(inner_payload)
        encoded = base64.b64encode(inner_json.encode("utf-8")).decode("utf-8")
        pubsub_msg = {"data": encoded}

        event = parse_input(ctx, pubsub_msg)
        assert event.actions.state_delta["task_type"] == "json_to_human"
        assert event.actions.state_delta["raw_input"] == inner_payload

    def test_empty_string_routes_human_to_json(self):
        ctx = DummyContext()
        event = parse_input(ctx, "")
        assert event.actions.state_delta["task_type"] == "human_to_json"


# ---------------------------------------------------------------------------
# determine_task
# ---------------------------------------------------------------------------


class TestDetermineTask:
    """Tests for determine_task() routing."""

    def test_routes_human_to_json(self):
        ctx = DummyContext(state={"task_type": "human_to_json"})
        event = determine_task(ctx, "some input")
        assert event.actions.route == "human_to_json"

    def test_routes_json_to_human(self):
        ctx = DummyContext(state={"task_type": "json_to_human"})
        event = determine_task(ctx, {"resourceType": "Patient"})
        assert event.actions.route == "json_to_human"


# ---------------------------------------------------------------------------
# route_completeness / route_json_completeness
# ---------------------------------------------------------------------------


class TestRouteCompleteness:
    """Tests for completeness routing decisions."""

    def test_complete_above_threshold_routes_complete(self):
        ctx = DummyContext()
        result = {"is_complete": True, "score": 85, "missing_details": ""}
        event = route_completeness(ctx, result)
        assert event.actions.route == "complete"
        assert ctx.state["completeness_score"] == 85

    def test_incomplete_below_threshold_routes_vague(self):
        ctx = DummyContext()
        result = {
            "is_complete": False,
            "score": 30,
            "missing_details": "ขาดข้อมูลอายุผู้ป่วย",
        }
        event = route_completeness(ctx, result)
        assert event.actions.route == "vague"
        assert ctx.state["completeness_score"] == 30
        assert ctx.state["missing_details"] == "ขาดข้อมูลอายุผู้ป่วย"

    def test_complete_but_below_threshold_routes_vague(self):
        """Even if LLM says is_complete=True, a low score still routes vague."""
        ctx = DummyContext()
        result = {"is_complete": True, "score": 50, "missing_details": "some details"}
        event = route_completeness(ctx, result)
        assert event.actions.route == "vague"

    def test_json_complete_above_threshold_routes_complete(self):
        ctx = DummyContext(state={"raw_input": {"resourceType": "Patient"}})
        result = {"is_complete": True, "score": 90, "missing_details": ""}
        event = route_json_completeness(ctx, result)
        assert event.actions.route == "complete"

    def test_json_incomplete_routes_vague(self):
        ctx = DummyContext(state={"raw_input": {"resourceType": "Patient"}})
        result = {
            "is_complete": False,
            "score": 20,
            "missing_details": "ขาดข้อมูลผู้ป่วย",
        }
        event = route_json_completeness(ctx, result)
        assert event.actions.route == "vague"


# ---------------------------------------------------------------------------
# _extract_details_from_resume
# ---------------------------------------------------------------------------


class TestExtractDetailsFromResume:
    """Tests for _extract_details_from_resume() helper."""

    def test_dict_with_result_key(self):
        assert (
            _extract_details_from_resume({"result": "อายุ 30 ปี"}) == "อายุ 30 ปี"
        )

    def test_dict_with_response_key(self):
        assert (
            _extract_details_from_resume({"response": "อายุ 30 ปี"}) == "อายุ 30 ปี"
        )

    def test_dict_with_other_key(self):
        """Falls back to first value if neither 'result' nor 'response' present."""
        result = _extract_details_from_resume({"text": "อายุ 30 ปี"})
        assert result == "อายุ 30 ปี"

    def test_plain_string(self):
        assert _extract_details_from_resume("plain text") == "plain text"

    def test_empty_dict_returns_string(self):
        result = _extract_details_from_resume({})
        assert isinstance(result, str)
