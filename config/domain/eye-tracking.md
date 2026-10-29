# Eye tracking: checklist

**Data and acquisition**
- Report the device (model, sampling rate, mono or binocular), the calibration procedure and the accuracy/precision achieved (degrees), the viewing distance and the screen geometry.
- Report the task paradigm: free viewing, visual search, reading, antisaccade, smooth pursuit or VR. Paradigms are not interchangeable across studies.
- Report the data-quality criteria: track loss %, minimum valid samples per trial, and the participants or trials excluded and why.

**Preprocessing**
- State the event-detection algorithm (I-VT, I-DT, adaptive) and its thresholds, plus blink handling, interpolation and filtering.
- Fit any parameters estimated from the data on training subjects only.

**Splits and leakage**
- Split at the subject level. Trials or scanpaths from one person never appear in both train and test.
- Watch for the same stimulus in train and test when the claim is generalization to new stimuli.
- Watch for session effects: when one person recorded several sessions, keep them in the same fold.

**Features and models**
- Fixation/saccade statistics, scanpath similarity (MultiMatch, ScanMatch), AOI dwell, pupil (account for luminance), and learned scanpath embeddings: say which, and why.
- Baselines include a demographic-only model (age, education) when predicting a clinical status.

**Reporting**
- Report the per-subject aggregation, the class balance, CIs, and the effect of device or site when there are several.
