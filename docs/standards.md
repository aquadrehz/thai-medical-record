# Medical Record Standards

Among the medical standards, **HL7 FHIR** (Fast Healthcare Interoperability Resources) is the overall digital standard used to structure, store, and exchange a patient's electronic medical record. 

While the other standards define the vocabulary used inside the record, HL7 FHIR acts as the actual **blueprint or container** for the data.

---

## 1. Roles & Classification

### 🌍 Global Standards
These are developed by international organizations and are used by hospitals and tech companies globally. Thailand adopts them to align with international care:

*   **HL7 FHIR**: The international standard for data transfer and structuring patient medical records.
*   **SNOMED CT**: The premier international clinical terminology standard used globally for diagnosing, mapping symptoms, and procedures.
*   **ICD-10 / ICD-11**: The World Health Organization's (WHO) universal classification system for tracking diseases and hospital discharges.
*   **LOINC**: An international standard used universally for identifying medical laboratory observations and test results.

### 🇹🇭 Thai-Only Standards
These were custom-built by the **Thai Health Information Standards Development Center (THIS)** and the **Ministry of Public Health**. They are designed specifically to handle local regulations, localized medication naming, and national health insurance (like the 30-Baht Universal Coverage) reimbursement claims:

*   **TMT (Thai Medicines Terminology)**: Specific entirely to Thailand. It catalogs every brand, packaging, and generic drug distributed within the country to manage local hospital inventories and insurance claims.
*   **TMLT (Thai Medical Laboratory Terminology)**: A localized code system mapping Thai lab tests, closely linked with Thailand's Comptroller General's Department and National Health Security Office (NHSO) registries (adapted partially from LOINC concepts but configured strictly for Thai hospital billing).

---

## 2. Standard Data Examples

The following examples demonstrate how each of the core standards is represented in actual hospital data payloads.

### 1. HL7 FHIR (The Interoperability Standard)
HL7 FHIR structures health data into highly readable JSON formats called "Resources". When a Thai hospital shares a patient's core demographics with another facility via a platform like Health Link, the data payload looks like this:

```json
{
  "resourceType": "Patient",
  "id": "th-patient-999",
  "identifier": [
    {
      "system": "https://www.dopa.go.th", 
      "value": "1100100XXXXXX" 
    }
  ],
  "name": [
    {
      "use": "official",
      "text": "นายสมชาย ดีใจ",
      "family": "ดีใจ",
      "given": ["สมชาย"]
    }
  ],
  "gender": "male",
  "birthDate": "1985-05-12"
}
```

### 2. TMT (Thai Medicines Terminology)
TMT assigns a universal code to every drug configuration in Thailand. Instead of hospitals typing out custom text names (which can cause typos and dosing errors), they use the specific TMT code for automated prescriptions and insurance claims.

**Example Drug**: Paracetamol 500mg tablet
*   **TMT ID**: 227144 (Unique identifier for the specific package/brand instance)
*   **Standard Concept Name**: Paracetamol 500 mg oral tablet

A medical order system transmits it like this:
```json
{
  "system": "https://tmt.this.or.th",
  "code": "227144",
  "display": "Paracetamol 500 mg oral tablet"
}
```

### 3. SNOMED CT (Clinical Terminology)
SNOMED CT provides a unique numeric concept ID for every clinical finding, symptom, or procedure, ensuring that terms mean exactly the same thing regardless of the local language or language register used by the doctor.

*   **Clinical Finding**: Type 2 Diabetes Mellitus
*   **SNOMED CT Concept ID**: 44054006

```json
{
  "system": "http://snomed.info/sct",
  "code": "44054006",
  "display": "Type 2 diabetes mellitus (disorder)"
}
```

### 4. ICD-10 / ICD-11 (International Classification of Diseases)
While SNOMED CT is used during active clinical charting, ICD is used universally at discharge for statistical reporting and hospital billing.

*   **Condition**: Acute appendicitis with generalized peritonitis
*   **ICD-10 Code**: K35.2

When the hospital submits an e-Claim data sheet to the National Health Security Office (NHSO) for reimbursement, the coding maps out seamlessly:
```xml
<Diagnosis>
    <DiagType>1</DiagType> <!-- Primary Diagnosis -->
    <DiagCode>K352</DiagCode>
</Diagnosis>
```

### 5. LOINC / TMLT (Laboratory Results)
When a Thai hospital processes a lab result, LOINC and the localized TMLT standardized codes define exactly what was measured, how, and from what specimen.

*   **Test**: Fasting Blood Glucose (Plasma/Serum)
*   **LOINC Code**: 1558-1

```json
{
  "code": {
    "system": "http://loinc.org",
    "code": "1558-1",
    "display": "Fasting glucose [Mass/volume] in Blood"
  },
  "valueQuantity": {
    "value": 98,
    "unit": "mg/dL",
    "system": "http://unitsofmeasure.org",
    "code": "mg/dL"
  },
  "status": "final"
}
```

---

## 3. Hybrid Usage Examples: Embedding Local Standards in FHIR

When a Thai hospital exports or transmits medical records, the structure remains universally standard (FHIR), but the codes inside the coding arrays point specifically to the official Thai registries.

### 1. Medication Record Example using TMT (FHIR `MedicationRequest`)
This example shows a FHIR `MedicationRequest` (a prescription). The `medicationCodeableConcept` uses the Thai Medicines Terminology (TMT) system URL to uniquely identify a specific brand or generic drug configuration distributed in Thailand.

```json
{
  "resourceType": "MedicationRequest",
  "id": "th-medrx-001",
  "status": "active",
  "intent": "order",
  "subject": {
    "reference": "Patient/th-patient-999",
    "display": "นายสมชาย ดีใจ"
  },
  "authoredOn": "2026-07-06T10:15:00+07:00",
  "medicationCodeableConcept": {
    "coding": [
      {
        "system": "https://tmt.this.or.th",
        "code": "227144",
        "display": "Paracetamol 500 mg oral tablet"
      }
    ],
    "text": "พาราเซตามอล 500 มิลลิกรัม"
  },
  "dosageInstruction": [
    {
      "text": "รับประทานครั้งละ 1 เม็ด ทุก 4-6 ชั่วโมง เมื่อมีอาการปวดหรือไข้",
      "timing": {
        "repeat": {
          "frequency": 1,
          "period": 4,
          "periodMax": 6,
          "periodUnit": "h"
        }
      }
    }
  ]
}
```

### 2. Lab Result Example using TMLT (FHIR `Observation`)
This example shows a FHIR `Observation` resource representing a laboratory test result. The code block uses the Thai Medical Laboratory Terminology (TMLT) system URL to define a specific lab panel configuration mandated by Thai healthcare data centers.

```json
{
  "resourceType": "Observation",
  "id": "th-lab-002",
  "status": "final",
  "category": [
    {
      "coding": [
        {
          "system": "http://terminology.hl7.org/CodeSystem/observation-category",
          "code": "laboratory",
          "display": "Laboratory"
        }
      ]
    }
  ],
  "code": {
    "coding": [
      {
        "system": "https://tmlt.this.or.th",
        "code": "320101", 
        "display": "Glucose, Fasting (Plasma/Serum)"
      }
    ],
    "text": "ระดับน้ำตาลในเลือดหลังอดอาหาร"
  },
  "subject": {
    "reference": "Patient/th-patient-999"
  },
  "effectiveDateTime": "2026-07-06T07:30:00+07:00",
  "valueQuantity": {
    "value": 98,
    "unit": "mg/dL",
    "system": "http://unitsofmeasure.org",
    "code": "mg/dL"
  },
  "referenceRange": [
    {
      "low": {
        "value": 70,
        "unit": "mg/dL"
      },
      "high": {
        "value": 99,
        "unit": "mg/dL"
      }
    }
  ]
}
```

---

## 4. Why This Matters

By pairing the global FHIR wrapper with localized terminology ([https://tmt.this.or.th](https://tmt.this.or.th) and [https://tmlt.this.or.th](https://tmlt.this.or.th)), any certified software system in Thailand can read this file, immediately populate the patient's local profile, and safely parse exact drug interactions or lab history without human translation.
