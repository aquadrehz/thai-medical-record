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

"""Integration tests for the multi-turn medical record workflow.

These tests exercise the full ADK Workflow through the Runner using
InMemorySessionService (no server needed). They hit the real Gemini API
so they require valid GCP credentials.

Test scenarios mirror the Thai-language conversational flow:
  1. Vague input → suspension with completeness score
  2. Multi-turn accumulation → user provides missing details iteratively
  3. JSON input → routes to json_to_human pathway

Run with:
    uv run pytest tests/integration/test_workflow_multi_turn.py -v
"""

import asyncio
from typing import Any

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import app as adk_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_request_input(event: Any) -> Any | None:
    """Extract adk_request_input FunctionCall from an event, if present."""
    if hasattr(event, "content") and event.content and event.content.parts:
        for part in event.content.parts:
            if (
                hasattr(part, "function_call")
                and part.function_call
                and part.function_call.name == "adk_request_input"
            ):
                return part.function_call
    return None


def _extract_text_parts(events: list) -> list[str]:
    """Collect all text content from a list of ADK events."""
    texts: list[str] = []
    for ev in events:
        if ev.content and ev.content.parts:
            for part in ev.content.parts:
                if hasattr(part, "text") and part.text:
                    texts.append(part.text)
    return texts


async def _run_turn(
    runner: Runner,
    message: types.Content,
    user_id: str,
    session_id: str,
    invocation_id: str | None = None,
) -> list:
    """Run a single turn through the workflow and collect events."""
    events: list = []
    kwargs: dict[str, Any] = {
        "new_message": message,
        "user_id": user_id,
        "session_id": session_id,
    }
    if invocation_id:
        kwargs["invocation_id"] = invocation_id

    async for ev in runner.run_async(**kwargs):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner_and_session():
    """Create a fresh Runner + InMemorySession pair for each test."""
    session_service = InMemorySessionService()
    session = session_service.create_session_sync(
        user_id="test_user", app_name="app"
    )
    runner = Runner(app=adk_app, session_service=session_service)
    return runner, session_service, session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVagueInputSuspension:
    """Verify that vague Thai medical text triggers a suspension."""

    @pytest.mark.asyncio
    async def test_vague_input_suspends_with_score(self, runner_and_session):
        """
        Example: "คนไข้ชายปวดหัวมาหลายวันแล้ว" (male patient with headache
        for several days) should be too vague and trigger adk_request_input.
        """
        runner, session_service, session = runner_and_session

        message = types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="คนไข้ชายปวดหัวมาหลายวันแล้ว")
            ],
        )

        events = await _run_turn(
            runner, message, "test_user", session.id
        )

        # Should have at least one event
        assert events, "Expected at least one event from the workflow"

        # Find the suspension event
        req_input = None
        for ev in events:
            req = _get_request_input(ev)
            if req:
                req_input = req
                break

        assert req_input is not None, (
            "Expected adk_request_input suspension for vague input"
        )

        # Verify the interrupt ID follows the clarify_N pattern
        interrupt_id = req_input.args["interruptId"]
        assert interrupt_id.startswith("clarify_"), (
            f"Expected interrupt ID starting with 'clarify_', got '{interrupt_id}'"
        )

        # Verify the suspension message contains the completeness score (%)
        suspension_message = req_input.args["message"]
        assert "%" in suspension_message, (
            "Expected completeness score percentage in suspension message"
        )
        assert "100%" in suspension_message, (
            "Expected '/100%' denominator in suspension message"
        )

    @pytest.mark.asyncio
    async def test_vague_english_input_suspends(self, runner_and_session):
        """English vague input should also trigger suspension."""
        runner, session_service, session = runner_and_session

        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text="patient has headache")],
        )

        events = await _run_turn(
            runner, message, "test_user", session.id
        )
        assert events, "Expected at least one event"

        req_input = None
        for ev in events:
            req = _get_request_input(ev)
            if req:
                req_input = req
                break

        assert req_input is not None, (
            "Expected suspension for vague English input"
        )


class TestMultiTurnAccumulation:
    """Verify that the workflow accumulates data across turns."""

    @pytest.mark.asyncio
    async def test_turn1_suspends_and_state_preserved(self, runner_and_session):
        """
        Turn 1: Send vague input, verify suspension.
        After suspension, session state should contain completeness_score and
        loop_count.
        """
        runner, session_service, session = runner_and_session

        message = types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="คนไข้ชายปวดหัวมาหลายวันแล้ว")
            ],
        )

        events = await _run_turn(
            runner, message, "test_user", session.id
        )

        req_input = None
        for ev in events:
            req = _get_request_input(ev)
            if req:
                req_input = req
                break

        assert req_input is not None, "Turn 1 should suspend"
        interrupt_id = req_input.args["interruptId"]

        # Load session and verify state was updated
        session = session_service.get_session_sync(
            app_name="app", user_id="test_user", session_id=session.id
        )
        assert session.state.get("completeness_score", 0) > 0, (
            "Expected completeness_score > 0 after first assessment"
        )
        assert session.state.get("loop_count", 0) >= 1, (
            "Expected loop_count >= 1 after first suspension"
        )

    @pytest.mark.asyncio
    async def test_session_events_contain_assessor_output(
        self, runner_and_session
    ):
        """
        After Turn 1, session events should include output from the
        completeness_assessor agent.
        """
        runner, session_service, session = runner_and_session

        message = types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="คนไข้ชายปวดหัวมาหลายวันแล้ว")
            ],
        )

        await _run_turn(runner, message, "test_user", session.id)

        # Reload session to get events
        session = session_service.get_session_sync(
            app_name="app", user_id="test_user", session_id=session.id
        )

        assessor_events = [
            ev
            for ev in session.events
            if ev.author == "completeness_assessor"
        ]
        assert assessor_events, (
            "Expected at least one event from completeness_assessor"
        )


class TestJsonInputRouting:
    """Verify that JSON/dict input routes to the json_to_human pathway."""

    @pytest.mark.asyncio
    async def test_fhir_json_string_input(self, runner_and_session):
        """
        Sending a FHIR JSON string should route to json_to_human and
        trigger json_completeness_assessor.
        """
        runner, session_service, session = runner_and_session

        fhir_payload = {
            "resourceType": "Patient",
            "id": "thai-patient-001",
            "gender": "male",
            "name": [{"family": "สมชาย", "given": ["นาย"]}],
        }

        message = types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=json.dumps(fhir_payload, ensure_ascii=False))
            ],
        )

        events = await _run_turn(
            runner, message, "test_user", session.id
        )
        assert events, "Expected at least one event"

        # Reload session and check task_type
        session = session_service.get_session_sync(
            app_name="app", user_id="test_user", session_id=session.id
        )
        assert session.state.get("task_type") == "json_to_human", (
            f"Expected task_type='json_to_human', got '{session.state.get('task_type')}'"
        )


class TestCompletenessScoreInResponse:
    """Verify that completion percentage is visible to the user."""

    @pytest.mark.asyncio
    async def test_score_percentage_in_suspension_message(
        self, runner_and_session
    ):
        """
        The suspension message must include the score as a percentage
        so the user knows how much remains to complete.
        """
        runner, session_service, session = runner_and_session

        message = types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text="คนไข้ชายปวดหัวมาหลายวันแล้ว"
                )
            ],
        )

        events = await _run_turn(
            runner, message, "test_user", session.id
        )

        req_input = None
        for ev in events:
            req = _get_request_input(ev)
            if req:
                req_input = req
                break

        assert req_input is not None, "Expected suspension"

        msg = req_input.args["message"]
        # Should contain a pattern like "30% / 100%"
        assert "%" in msg, "Suspension message should contain '%' score"

        # Verify the score is a valid number before the '%'
        # Extract the score from "คะแนนความสมบูรณ์: XX%"
        import re

        score_match = re.search(r"(\d+)%", msg)
        assert score_match, "Expected a numeric score percentage in message"
        score_val = int(score_match.group(1))
        assert 0 <= score_val <= 100, (
            f"Score {score_val} should be between 0 and 100"
        )


# Need json import for TestJsonInputRouting
import json
