# Gold-set confusion report

Generated from `data/gold/gold.csv` (human truth) x `evals/gold_predictions.csv` (workhorse `pred_*`, judge `judge_*`), joined on `id`. n=54.

Three comparisons per axis:

- **workhorse vs human** -- the classifier's real accuracy (the product number).
- **judge vs human** -- can the judge stand in for a human labeler? (gates scaling the eval past the hand-labeled set).
- **workhorse vs judge** -- do the two models agree, where no human label exists?

Read a matrix: rows = truth, columns = prediction, the diagonal is correct. A row reads as recall (of the truly-X, how many were caught); a column reads as precision (of those called X, how many were right).

## Category

### workhorse vs human -- 94.4% (51/54)

```
rows = truth, columns = prediction
predicted    industry  operations  policy  procurement  technology
true                                                              
industry            5           0       0            0           0
operations          0          20       1            0           1
policy              0           0       6            0           0
procurement         0           1       0            7           0
technology          0           0       0            0          13
```

per-label (precision / recall / f1 / support):

```
             precision  recall     f1  support
label                                         
industry         1.000   1.000  1.000        5
operations       0.952   0.909  0.930       22
policy           0.857   1.000  0.923        6
procurement      1.000   0.875  0.933        8
technology       0.929   1.000  0.963       13
```
macro-F1: 0.950

disagreements (3):
- true=operations pred=policy x1 [g053]
- true=operations pred=technology x1 [g013]
- true=procurement pred=operations x1 [g020]

### judge vs human -- 94.4% (51/54)

```
rows = truth, columns = prediction
predicted    industry  operations  policy  procurement  technology
true                                                              
industry            5           0       0            0           0
operations          0          21       1            0           0
policy              0           0       6            0           0
procurement         1           0       0            7           0
technology          0           1       0            0          12
```

per-label (precision / recall / f1 / support):

```
             precision  recall     f1  support
label                                         
industry         0.833   1.000  0.909        5
operations       0.955   0.955  0.955       22
policy           0.857   1.000  0.923        6
procurement      1.000   0.875  0.933        8
technology       1.000   0.923  0.960       13
```
macro-F1: 0.936

disagreements (3):
- true=operations pred=policy x1 [g053]
- true=procurement pred=industry x1 [g020]
- true=technology pred=operations x1 [g007]

### workhorse vs judge -- 94.4% (51/54)

```
rows = truth, columns = prediction
predicted    industry  operations  policy  procurement  technology
true                                                              
industry            5           0       0            0           0
operations          1          20       0            0           0
policy              0           0       7            0           0
procurement         0           0       0            7           0
technology          0           2       0            0          12
```

disagreements (3):
- true=technology pred=operations x2 [g007, g013]
- true=operations pred=industry x1 [g020]

## Operational domain

### workhorse vs human -- 92.6% (50/54)

```
rows = truth, columns = prediction
predicted  air  cyber  land  multi  sea  space
true                                          
air         14      0     1      0    0      0
cyber        0      5     0      1    0      0
land         0      0    11      0    0      0
multi        0      0     1      9    0      0
sea          0      0     0      1    8      0
space        0      0     0      0    0      3
```

per-label (precision / recall / f1 / support):

```
       precision  recall     f1  support
label                                   
air        1.000   0.933  0.966       15
cyber      1.000   0.833  0.909        6
land       0.846   1.000  0.917       11
multi      0.818   0.900  0.857       10
sea        1.000   0.889  0.941        9
space      1.000   1.000  1.000        3
```
macro-F1: 0.932

disagreements (4):
- true=air pred=land x1 [g021]
- true=cyber pred=multi x1 [g056]
- true=multi pred=land x1 [g053]
- true=sea pred=multi x1 [g043]

### judge vs human -- 94.4% (51/54)

```
rows = truth, columns = prediction
predicted  air  cyber  land  multi  sea  space
true                                          
air         13      0     1      1    0      0
cyber        0      6     0      0    0      0
land         0      0    10      1    0      0
multi        0      0     0     10    0      0
sea          0      0     0      0    9      0
space        0      0     0      0    0      3
```

per-label (precision / recall / f1 / support):

```
       precision  recall     f1  support
label                                   
air        1.000   0.867  0.929       15
cyber      1.000   1.000  1.000        6
land       0.909   0.909  0.909       11
multi      0.833   1.000  0.909       10
sea        1.000   1.000  1.000        9
space      1.000   1.000  1.000        3
```
macro-F1: 0.958

disagreements (3):
- true=air pred=land x1 [g021]
- true=air pred=multi x1 [g033]
- true=land pred=multi x1 [g041]

### workhorse vs judge -- 90.7% (49/54)

```
rows = truth, columns = prediction
predicted  air  cyber  land  multi  sea  space
true                                          
air         13      0     0      1    0      0
cyber        0      5     0      0    0      0
land         0      0    11      2    0      0
multi        0      1     0      9    1      0
sea          0      0     0      0    8      0
space        0      0     0      0    0      3
```

disagreements (5):
- true=land pred=multi x2 [g041, g053]
- true=air pred=multi x1 [g033]
- true=multi pred=cyber x1 [g056]
- true=multi pred=sea x1 [g043]
