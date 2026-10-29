# Representation learning and computer vision: checklist

- **Pretraining data:** source, size, and overlap with downstream test data (check for contamination). For medical data, keep subjects disjoint between pretraining and downstream test.
- **Protocol:** linear probe versus fine-tuning versus few-shot. Keep the same downstream splits and budgets across methods, and tune baselines with the same effort.
- **Augmentations:** list them. Medical images need plausible ones (no flips that change anatomy laterality when that matters).
- **Seeds and variance:** at least 3 seeds. Report mean ± std or a CI. Avoid claims from single runs.
- **Ablations:** one per component (loss term, augmentation, architecture piece, pretraining data size).
- **Compute:** GPU type, hours and batch size. Note whether gains hold at equal compute.
- **Embedding analysis:** quantitative probes before t-SNE/UMAP pictures. Pictures are illustrations, not evidence.
