# Specification: Ambient Thai Medical Record Agent

## 1. System Overview
The Ambient Thai Medical Record Agent is a software assistant built with the Google Agent Development Kit (ADK 2.0). It processes incoming medical records and converts them to standardized health formats (HL7 FHIR, TMT, TMLT, SNOMED CT, ICD-10), or translates standardized JSON back into human-readable text.

---

## 2. Input Handling
Input arrives as a JSON event. The agent must support extraction from a `"data"` key which can be formatted in two ways:
*   **Base64 Encoded**: As received in live Google Cloud Pub/Sub subscriptions.
*   **Plain JSON**: For local development and testing.

---

## 3. Core Behaviors

### A. Translation: Human Text to Medical Standards (JSON)
*   **Standard Selection**: Detect which standards (HL7 FHIR, SNOMED CT, ICD-10, LOINC, TMT, TMLT) are appropriate for the clinical text.
*   **Prioritization**: If the incoming text mentions specific standards, prioritize those first.
*   **Conversion**: The clinical text can be converted and split into one or more standards represented as structured JSON payloads.
*   **Completeness Guardrail**: If the input is too vague or lacks sufficient clinical details (e.g. missing drug names, dosage, or patient ID), the agent must prompt the doctor for the missing details. 
*   **Human-in-the-Loop (HITL)**: Use ADK 2.0's `RequestInput` to pause execution, query the doctor, and resume once the requested details are supplied.

### B. Translation: Medical Standards (JSON) to Human Text
*   If the input is already a JSON payload conforming to the standards in `docs/standards.md`, the agent converts it back into natural language.
*   **Language**: Default to English, unless the user requests a specific language (e.g., Thai).

---

## 4. Architecture Requirements
*   **ADK version**: ADK 2.0 graph workflow. No 1.x `SequentialAgent`/`LlmAgent` composites.
*   **Models and Configuration**: Configurable model name (`gemini-3.1-flash-lite`) and validation thresholds in a config module/file.
*   **Directory Structure**: The workflow agent and any sub-agents live under `medical_record_agents/`.
