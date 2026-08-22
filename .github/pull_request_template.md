## Summary

Describe the user-visible result and the technical boundary changed.

## Risk and compatibility

- Formats and target machines:
- Source-image and physical-disk safety:
- Geometry or metadata implications:
- GNOME accessibility implications:

## Verification

- [ ] Python regressions pass.
- [ ] Python compilation and launcher syntax checks pass.
- [ ] Corrupt, truncated, cancellation, and failure cases are covered where relevant.
- [ ] No private or copyrighted fixture has been added.
- [ ] Destructive operations require explicit confirmation and fail closed.

List exact commands and relevant real-hardware evidence:

## Engineering review

- [ ] User-controlled paths and subprocess arguments remain bounded and validated.
- [ ] Source images and unusual tracks are preserved.
- [ ] Changed controls remain keyboard-operable and clearly labelled.
- [ ] Documentation uses current terminology.
