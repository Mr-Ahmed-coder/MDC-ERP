"""Common ICD-10 diagnosis codes for the Consultation module.

A curated list of frequent primary-care and diagnostic-center codes.
Doctors can also type any other valid code freely — the field is a
datalist (suggestions), not a closed list.
"""

ICD10_COMMON = [
    # Infectious / parasitic
    ('A01.0', 'Typhoid fever'),
    ('A06.0', 'Acute amoebic dysentery'),
    ('A09',   'Infectious gastroenteritis and colitis'),
    ('A16.2', 'Pulmonary tuberculosis'),
    ('B50.9', 'Plasmodium falciparum malaria, unspecified'),
    ('B54',   'Malaria, unspecified'),
    ('B15.9', 'Hepatitis A without hepatic coma'),
    ('B18.1', 'Chronic viral hepatitis B'),
    ('B20',   'HIV disease'),
    ('B37.3', 'Candidiasis of vulva and vagina'),
    ('B76.9', 'Hookworm disease, unspecified'),
    ('B77.9', 'Ascariasis, unspecified'),
    ('B86',   'Scabies'),
    # Blood / endocrine
    ('D50.9', 'Iron deficiency anaemia, unspecified'),
    ('D64.9', 'Anaemia, unspecified'),
    ('E03.9', 'Hypothyroidism, unspecified'),
    ('E05.9', 'Thyrotoxicosis (hyperthyroidism), unspecified'),
    ('E10.9', 'Type 1 diabetes mellitus without complications'),
    ('E11.9', 'Type 2 diabetes mellitus without complications'),
    ('E46',   'Protein-energy malnutrition, unspecified'),
    ('E66.9', 'Obesity, unspecified'),
    ('E78.5', 'Hyperlipidaemia, unspecified'),
    # Mental / neuro
    ('F32.9', 'Depressive episode, unspecified'),
    ('F41.9', 'Anxiety disorder, unspecified'),
    ('G40.9', 'Epilepsy, unspecified'),
    ('G43.9', 'Migraine, unspecified'),
    ('R51',   'Headache'),
    # Eye / ear
    ('H10.9', 'Conjunctivitis, unspecified'),
    ('H66.9', 'Otitis media, unspecified'),
    # Circulatory
    ('I10',   'Essential (primary) hypertension'),
    ('I25.9', 'Chronic ischaemic heart disease, unspecified'),
    ('I50.9', 'Heart failure, unspecified'),
    ('I64',   'Stroke, not specified as haemorrhage or infarction'),
    ('I84',   'Haemorrhoids'),
    # Respiratory
    ('J00',   'Acute nasopharyngitis (common cold)'),
    ('J02.9', 'Acute pharyngitis, unspecified'),
    ('J03.9', 'Acute tonsillitis, unspecified'),
    ('J06.9', 'Acute upper respiratory infection, unspecified'),
    ('J18.9', 'Pneumonia, unspecified'),
    ('J20.9', 'Acute bronchitis, unspecified'),
    ('J45.9', 'Asthma, unspecified'),
    ('J44.9', 'Chronic obstructive pulmonary disease, unspecified'),
    # Digestive
    ('K02.9', 'Dental caries, unspecified'),
    ('K21.9', 'Gastro-oesophageal reflux disease'),
    ('K25.9', 'Gastric ulcer, unspecified'),
    ('K29.7', 'Gastritis, unspecified'),
    ('K30',   'Functional dyspepsia'),
    ('K35.8', 'Acute appendicitis'),
    ('K52.9', 'Noninfective gastroenteritis and colitis'),
    ('K59.0', 'Constipation'),
    ('K80.2', 'Calculus of gallbladder without cholecystitis'),
    # Skin
    ('L02.9', 'Cutaneous abscess, furuncle and carbuncle'),
    ('L20.9', 'Atopic dermatitis, unspecified'),
    ('L30.9', 'Dermatitis, unspecified'),
    ('L50.9', 'Urticaria, unspecified'),
    # Musculoskeletal
    ('M25.5', 'Pain in joint'),
    ('M54.5', 'Low back pain'),
    ('M79.1', 'Myalgia'),
    ('M10.9', 'Gout, unspecified'),
    # Genitourinary
    ('N20.0', 'Calculus of kidney'),
    ('N30.9', 'Cystitis, unspecified'),
    ('N39.0', 'Urinary tract infection, site not specified'),
    ('N40',   'Benign prostatic hyperplasia'),
    ('N76.0', 'Acute vaginitis'),
    ('N91.2', 'Amenorrhoea, unspecified'),
    # Pregnancy
    ('O26.9', 'Pregnancy-related condition, unspecified'),
    ('Z32.1', 'Pregnancy confirmed'),
    ('Z34.9', 'Supervision of normal pregnancy, unspecified'),
    # Symptoms / findings
    ('R05',   'Cough'),
    ('R10.4', 'Other and unspecified abdominal pain'),
    ('R11',   'Nausea and vomiting'),
    ('R42',   'Dizziness and giddiness'),
    ('R50.9', 'Fever, unspecified'),
    ('R53',   'Malaise and fatigue'),
    ('R55',   'Syncope and collapse'),
    ('R73.9', 'Hyperglycaemia, unspecified'),
    # Injury / external
    ('S09.9', 'Head injury, unspecified'),
    ('T14.9', 'Injury, unspecified'),
    ('T78.4', 'Allergy, unspecified'),
    ('W54',   'Bitten or struck by dog'),
    # Encounters
    ('Z00.0', 'General medical examination'),
    ('Z01.7', 'Laboratory examination'),
]


def icd_options():
    """Datalist options: 'CODE — Description'."""
    return [f"{c} — {d}" for c, d in ICD10_COMMON]
