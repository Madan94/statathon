# Large test datasets (local only)

These files exceed GitHub's size limits and are **not** in the repo.
Place them in this folder locally to run the full pre-anomaly test suite:

| File | ~Size |
|------|-------|
| `LEVEL - 05 ( Sec 5  6).csv` | 974 MB |
| `CPERV1.TXT` | 408 MB |
| `LEVEL - 06 (Section 7).csv` | 123 MB |
| `LEVEL - 08 (Section 8_1).csv` | 116 MB |
| `LEVEL - 02 (Section 3).csv` | 104 MB |
| `CHHV1.TXT` | 57 MB |

Run tests (smaller files still work without these):

```bash
python scripts/test_pre_anomaly_all_datasets.py --max-rows 200
```
