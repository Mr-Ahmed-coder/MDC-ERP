"""ICD-10 quick-pick list — common diagnoses for a Somali diagnostic center.

Used as an HTML <datalist>: the doctor can pick a suggestion or type any
other valid ICD-10 code freely.
"""

ICD10_COMMON = [
    ('A01.0', 'Typhoid fever'),
    ('A06.0', 'Acute amoebic dysentery'),
    ('A09',   'Infectious gastroenteritis'),
    ('A15.0', 'Tuberculosis of lung'),
    ('A16.2', 'Pulmonary TB (unconfirmed)'),
    ('B50.9', 'Plasmodium falciparum malaria'),
    ('B54',   'Malaria, unspecified'),
    ('B15.9', 'Hepatitis A'),
    ('B18.1', 'Chronic hepatitis B'),
    ('B20',   'HIV disease'),
    ('D50.9', 'Iron deficiency anaemia'),
    ('E11.9', 'Type 2 diabetes mellitus'),
    ('E86',   'Dehydration'),
    ('E43',   'Severe malnutrition'),
    ('G40.9', 'Epilepsy, unspecified'),
    ('I10',   'Essential hypertension'),
    ('I50.9', 'Heart failure'),
    ('I64',   'Stroke, unspecified'),
    ('J00',   'Acute nasopharyngitis (common cold)'),
    ('J02.9', 'Acute pharyngitis'),
    ('J18.9', 'Pneumonia, unspecified'),
    ('J45.9', 'Asthma, unspecified'),
    ('K21.9', 'GERD'),
    ('K29.7', 'Gastritis'),
    ('K35.8', 'Acute appendicitis'),
    ('K59.0', 'Constipation'),
    ('L02.9', 'Cutaneous abscess'),
    ('M54.5', 'Low back pain'),
    ('M79.1', 'Myalgia'),
    ('N39.0', 'Urinary tract infection'),
    ('N20.0', 'Kidney stone'),
    ('O80',   'Normal delivery'),
    ('R10.4', 'Abdominal pain'),
    ('R50.9', 'Fever, unspecified'),
    ('R51',   'Headache'),
    ('R05',   'Cough'),
    ('R11',   'Nausea and vomiting'),
    ('S06.0', 'Concussion'),
    ('T14.9', 'Injury, unspecified'),
    ('Z00.0', 'General medical examination'),
]


def icd10_datalist_options():
    """(value, label) pairs for the datalist field type."""
    return [(code, f'{code} — {name}') for code, name in ICD10_COMMON]
