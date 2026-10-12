# Research report: turnover\_forward\_return\_v1\_synthetic

> SYNTHETIC ONLY. This archived Phase 4 example has a date-labelled data version,
> not a verified dataset content hash. It is unregistered and makes no claim about real HK shares.

- Experiment ID: unavailable (standalone, unregistered result)
- Source: summary.json (`summary.json`)
- Status field: `WORTH\_FURTHER\_RESEARCH` (exploratory classification, **not** evidence of an investable strategy)
- Exploratory: true

## Question and method

- Research question/name: turnover\_forward\_return\_v1\_synthetic
- Variable and thresholds (`variable`): {"name": "turnover\_rate", "thresholds": \[0.1, 0.3, 0.5, 0.7, 0.9\], "unit": "ratio"}
- Forward periods (`forward_periods`): \[1, 2, 3, 5, 10, 20\]
- Return definition (`return_definition`): {"dividend": "excluded", "entry": "close", "exit": "close", "type": "price\_return"}
- Event mode (`event_mode`): daily
- Date range (`date_range`): {"end": null, "start": null}
- Universe (`universe_definition`): {"mode": "observed\_price\_universe"}
- Data version (`data_version`): HK\_DAILY\_2026\_09\_24
- Tested combinations (`tested_combinations`): 30

## Recorded statistics

Every value below is copied from `summary_statistics` in the saved result; missing cells are shown as unavailable.

| threshold | forward_period | sample_count | valid_sample_count | mean | median | win_rate | ci_lower | ci_upper |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.1 | 1 | 36 | 35 | 0.0011485714285714163 | 0.0011799999999999589 | 1.0 | 0.000982857142857136 | 0.001311571428571417 |
| 0.1 | 2 | 36 | 34 | 0.002290924988235237 | 0.002261274399999902 | 1.0 | 0.001955118314705844 | 0.0026030933852940648 |
| 0.1 | 3 | 36 | 33 | 0.003426258566402844 | 0.0035441688312318753 | 1.0 | 0.0029737823346328543 | 0.0038758880456620753 |
| 0.1 | 5 | 36 | 31 | 0.005672231757874511 | 0.005912083463195605 | 1.0 | 0.0049745573948140965 | 0.006368568953432828 |
| 0.1 | 10 | 36 | 26 | 0.011087966131735042 | 0.011356006615328207 | 1.0 | 0.009922312314017908 | 0.012136206230556983 |
| 0.1 | 20 | 36 | 18 | 0.02079943499631863 | 0.020799434996318533 | 1.0 | unavailable | unavailable |
| 0.3 | 1 | 28 | 27 | 0.001331851851851827 | 0.0013799999999999368 | 1.0 | 0.001161481481481467 | 0.0014911111111111017 |
| 0.3 | 2 | 28 | 26 | 0.0026387953230768446 | 0.002661766399999821 | 1.0 | 0.002292382726922991 | 0.0029317006461537683 |
| 0.3 | 3 | 28 | 25 | 0.003917471398092714 | 0.003944031497792322 | 1.0 | 0.003428409598481524 | 0.0043585434423335555 |
| 0.3 | 5 | 28 | 23 | 0.006373735654192655 | 0.006416354792699641 | 1.0 | 0.005630183404095759 | 0.007094253137987276 |
| 0.3 | 10 | 28 | 18 | 0.011641070049408064 | 0.01236788770894981 | 1.0 | unavailable | unavailable |
| 0.3 | 20 | 28 | 14 | 0.020799434996318644 | 0.020799434996318644 | 1.0 | unavailable | unavailable |
| 0.5 | 1 | 20 | 19 | 0.0015010526315789175 | 0.0015799999999999148 | 1.0 | unavailable | unavailable |
| 0.5 | 2 | 20 | 18 | 0.002940050844444375 | 0.00306233839999992 | 1.0 | unavailable | unavailable |
| 0.5 | 3 | 20 | 17 | 0.00430535849317076 | 0.0044465644269919835 | 1.0 | unavailable | unavailable |
| 0.5 | 5 | 20 | 15 | 0.00675287003420942 | 0.0074218862195876145 | 1.0 | unavailable | unavailable |
| 0.5 | 10 | 20 | 10 | 0.009844993452532869 | 0.009840559727229636 | 1.0 | unavailable | unavailable |
| 0.5 | 20 | 20 | 10 | 0.02079943499631869 | 0.020799434996318755 | 1.0 | unavailable | unavailable |
| 0.7 | 1 | 12 | 11 | 0.001625454545454536 | 0.0017799999999998928 | 1.0 | unavailable | unavailable |
| 0.7 | 2 | 12 | 10 | 0.0030825599999999786 | 0.0034629903999996436 | 1.0 | unavailable | unavailable |
| 0.7 | 3 | 12 | 9 | 0.004313530341738659 | 0.00504846192483166 | 1.0 | unavailable | unavailable |
| 0.7 | 5 | 12 | 7 | 0.005700698429929992 | 0.005912083463195605 | 1.0 | unavailable | unavailable |
| 0.7 | 10 | 12 | 6 | 0.007826746745080215 | 0.00782527237703956 | 1.0 | unavailable | unavailable |
| 0.7 | 20 | 12 | 6 | 0.020799434996318755 | 0.020799434996318755 | 1.0 | unavailable | unavailable |
| 0.9 | 1 | 4 | 3 | 0.0013466666666667553 | 0.001980000000000093 | 1.0 | unavailable | unavailable |
| 0.9 | 2 | 4 | 2 | 0.0011600864000002042 | 0.0011600864000002042 | 1.0 | unavailable | unavailable |
| 0.9 | 3 | 4 | 2 | 0.0013903082162722846 | 0.0013903082162722846 | 1.0 | unavailable | unavailable |
| 0.9 | 5 | 4 | 2 | 0.0021514243968674407 | 0.0021514243968674407 | 1.0 | unavailable | unavailable |
| 0.9 | 10 | 4 | 2 | 0.005814408130971449 | 0.005814408130971449 | 1.0 | unavailable | unavailable |
| 0.9 | 20 | 4 | 2 | 0.020799434996318755 | 0.020799434996318755 | 1.0 | unavailable | unavailable |

## Recorded relationship analysis

The following JSON is copied from `relationship_analysis`; overlapping events and multiple comparisons can weaken the evidence.

```json
{
  "holding_period_relationships": [
    {
      "pattern": "increasing",
      "spearman_p": null,
      "spearman_rho": 1.0,
      "threshold": 0.1
    },
    {
      "pattern": "increasing",
      "spearman_p": null,
      "spearman_rho": 1.0,
      "threshold": 0.3
    },
    {
      "pattern": "increasing",
      "spearman_p": null,
      "spearman_rho": 1.0,
      "threshold": 0.5
    },
    {
      "pattern": "increasing",
      "spearman_p": null,
      "spearman_rho": 1.0,
      "threshold": 0.7
    },
    {
      "pattern": "non_monotonic",
      "spearman_p": 0.002258739632219342,
      "spearman_rho": 0.942857142857143,
      "threshold": 0.9
    }
  ],
  "overlapping_thresholds": true,
  "threshold_return_relationships": [
    {
      "holding_period": 1,
      "pattern": "non_monotonic",
      "spearman_mean_p": 0.21999246028704111,
      "spearman_mean_rho": 0.7,
      "spearman_median_p": 0.0,
      "spearman_median_rho": 0.9999999999999999
    },
    {
      "holding_period": 2,
      "pattern": "no_clear_pattern",
      "spearman_mean_p": 1.0,
      "spearman_mean_rho": 0.0,
      "spearman_median_p": 1.0,
      "spearman_median_rho": 0.0
    },
    {
      "holding_period": 3,
      "pattern": "no_clear_pattern",
      "spearman_mean_p": 1.0,
      "spearman_mean_rho": 0.0,
      "spearman_median_p": 1.0,
      "spearman_median_rho": 0.0
    },
    {
      "holding_period": 5,
      "pattern": "non_monotonic",
      "spearman_mean_p": 0.6615843235713763,
      "spearman_mean_rho": -0.3,
      "spearman_median_p": 0.4799771519209477,
      "spearman_median_rho": -0.46169025843831935
    },
    {
      "holding_period": 10,
      "pattern": "non_monotonic",
      "spearman_mean_p": 0.03733947666846804,
      "spearman_mean_rho": -0.8999999999999998,
      "spearman_median_p": 0.03733947666846804,
      "spearman_median_rho": -0.8999999999999998
    },
    {
      "holding_period": 20,
      "pattern": "increasing",
      "spearman_mean_p": 0.0020662413982424077,
      "spearman_mean_rho": 0.9746794344808963,
      "spearman_median_p": 0.04119034493345186,
      "spearman_median_rho": 0.8944271909999159
    }
  ],
  "thresholds_are_nested": true
}
```

## Limits and warnings

- historical listing/delisting information is unavailable; results may contain survivorship bias
- exploratory research: multiple thresholds/periods were tested simultaneously; findings need independent validation
- return is price\_return; dividends are excluded
- Baseline, out-of-sample testing, costs, risk, ML and news are unavailable in this research artifact unless separately linked to registered experiments.
- The summary is a research observation and does not authorize an order.

## Reproducibility

Inspect the source `summary.json`, `config.yaml`, and the Experiment Registry (when an experiment ID exists).
