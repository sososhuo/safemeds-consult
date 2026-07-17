# SafeMeds RAG Ablation Evaluation

- Test cases: 32 (儿童 8, 成人 8, 孕妇 8, 老年人 8)
- Metrics: high-risk accuracy, evidence recall hit rate, Unknown rate, fallback rate
- Note: LLM answer generation is mocked as successful to isolate retrieval and risk workflow differences.

| Variant | High-risk accuracy | Evidence recall hit rate | Unknown rate | Fallback rate | Risk distribution |
| --- | ---: | ---: | ---: | ---: | --- |
| Baseline A: Chroma only | 53.1% | 6.2% | 0.0% | 0.0% | High: 17, Medium: 11, Low: 4 |
| Baseline B: Chroma + BM25 | 78.1% | 100.0% | 0.0% | 0.0% | High: 25, Low: 2, Medium: 5 |
| Current: Chroma + BM25 + rules + KG | 75.0% | 100.0% | 3.1% | 0.0% | High: 24, Unknown: 1, Medium: 5, Low: 2 |

## Group Breakdown

### Baseline A: Chroma only

| Group | High-risk accuracy | Evidence recall hit rate | Unknown rate |
| --- | ---: | ---: | ---: |
| 儿童 | 100.0% | 0.0% | 0.0% |
| 成人 | 37.5% | 0.0% | 0.0% |
| 孕妇 | 62.5% | 12.5% | 0.0% |
| 老年人 | 12.5% | 12.5% | 0.0% |

### Baseline B: Chroma + BM25

| Group | High-risk accuracy | Evidence recall hit rate | Unknown rate |
| --- | ---: | ---: | ---: |
| 儿童 | 100.0% | 100.0% | 0.0% |
| 成人 | 75.0% | 100.0% | 0.0% |
| 孕妇 | 100.0% | 100.0% | 0.0% |
| 老年人 | 37.5% | 100.0% | 0.0% |

### Current: Chroma + BM25 + rules + KG

| Group | High-risk accuracy | Evidence recall hit rate | Unknown rate |
| --- | ---: | ---: | ---: |
| 儿童 | 75.0% | 100.0% | 12.5% |
| 成人 | 62.5% | 100.0% | 0.0% |
| 孕妇 | 100.0% | 100.0% | 0.0% |
| 老年人 | 62.5% | 100.0% | 0.0% |
