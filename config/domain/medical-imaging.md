# Medical imaging AI: checklist

**Data**
- Report the source, the inclusion/exclusion criteria, scanner vendors and field strengths, acquisition protocols, sites and dates.
- State how the ground truth was defined (who annotated, inter-rater agreement, reference standard) and the label noise.
- State the ethics approval or IRB, the consent, de-identification and data-use agreement. Treat DICOM headers and faces in head MRI as PHI.

**Splits and leakage**
- Split at the patient level, never at the image or slice level. Keep all scans of one patient in one fold, and keep longitudinal visits together.
- Fit intensity normalization, registration templates and feature selection on training data only.
- Watch for site or scanner confounded with label (the model learns the scanner). Check with site-stratified results and leave-site-out validation.
- Check for near-duplicate images across splits.

**Evaluation**
- Use an external test set whenever possible. Report internal and external performance separately.
- Report AUROC/AUPRC with 95% CIs, sensitivity and specificity at a pre-specified operating point, and calibration (ECE, calibration plot).
- Report subgroup performance (sex, age band, site, disease stage).
- For segmentation: Dice and HD95 per structure, with the distribution, not only the mean.

**Reporting standards**
- CLAIM (Checklist for AI in Medical Imaging)
- STARD-AI for diagnostic accuracy
- TRIPOD+AI for prediction models
