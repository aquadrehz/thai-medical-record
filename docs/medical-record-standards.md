# Medical Record Standards

Among the medical standards, **HL7 FHIR** (Fast Healthcare Interoperability Resources) is the overall digital standard used to structure, store, and exchange a patient's electronic medical record. 

While the other standards define the vocabulary used inside the record, HL7 FHIR acts as the actual **blueprint or container** for the data.

---

## 1. Roles & Classification

### 🌍 Global Standards
These are developed by international organizations and are used by hospitals and tech companies globally. Thailand adopts them to align with international care:

*   **HL7 FHIR**: The international standard for data transfer and structuring patient medical records.
*   **SNOMED CT**: The premier international clinical terminology standard used globally for diagnosing, mapping symptoms, and procedures.
*   **ICD-10 / ICD-11**: The World Who Organization's (WHO) universal classification system for tracking diseases and hospital discharges.
*   **LOINC**: An international standard used universally for identifying medical laboratory observations and test results.

### 🇹🇭 Thai-Only Standards
These were custom-built by the **Thai Health Information Standards Development Center (THIS)** and the **Ministry of Public Health**. They are designed specifically to handle local regulations, localized medication naming, and national health insurance (like the 30-Baht Universal Coverage) reimbursement claims:

*   **TMT (Thai Medicines Terminology)**: Specific entirely to Thailand. It catalogs every brand, packaging, and generic drug distributed within the country to manage local hospital inventories and insurance claims.
*   **TMLT (Thai Medical Laboratory Terminology)**: A localized code system mapping Thai lab tests, closely linked with Thailand's Comptroller General's Department and National Health Security Office (NHSO) billing registries (adapted partially from LOINC concepts but configured strictly for Thai hospital billing).

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
