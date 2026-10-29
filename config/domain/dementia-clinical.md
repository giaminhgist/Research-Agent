# Dementia diagnosis: checklist

**Cohorts and labels**
- Name the cohort (ADNI, OASIS, AIBL, NACC, UK Biobank, local) and its diagnostic criteria (NIA-AA, DSM-5, Petersen MCI). Report clinical versus biomarker-defined labels (amyloid/tau PET, CSF).
- Define the classes precisely: CN, SCD, MCI (amnestic or non-amnestic), AD dementia, other dementias. State the time window for "converters" (MCI→AD) and how stable versus progressive MCI is defined.
- Address the confounders: age, sex, education (cognitive reserve), APOE ε4, comorbidities and medication. Show that the model does not just predict age.

**Leakage specific to dementia**
- Longitudinal visits of one participant stay in the same fold.
- Features derived from the diagnosis itself (MMSE/CDR used to define labels) must not be inputs when the claim is "beyond cognitive tests".
- Hyperparameters must not be tuned on the conversion test set.

**Evaluation and claims**
- Report class-balanced metrics, CIs, and calibration. Report decision-curve analysis for clinical utility claims.
- Compare against clinically used baselines: cognitive scores (MMSE, MoCA), demographics, hippocampal volume.
- Generalization claims need an external cohort. Screening claims need the intended population's prevalence.
- Write about patients respectfully. Avoid overclaiming "early diagnosis" without longitudinal evidence.
