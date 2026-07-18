# Gold-set confusion report

Generated from `data/gold/gold.csv` (human truth) x `evals/gold_predictions_v3.csv` (workhorse `pred_*`, judge `judge_*`), joined on `id`. n=54.

Three comparisons per axis:

- **workhorse vs human** -- the classifier's real accuracy (the product number).
- **judge vs human** -- can the judge stand in for a human labeler? (gates scaling the eval past the hand-labeled set).
- **workhorse vs judge** -- do the two models agree, where no human label exists?

Read a matrix: rows = truth, columns = prediction, the diagonal is correct. A row reads as recall (of the truly-X, how many were caught); a column reads as precision (of those called X, how many were right).

## Category

### workhorse vs human -- 92.6% (50/54)

```
rows = truth, columns = prediction
predicted    industry  operations  policy  procurement  technology
true                                                              
industry            5           0       0            0           0
operations          0          20       2            0           0
policy              0           0       6            0           0
procurement         1           0       0            7           0
technology          0           0       0            1          12
```

per-label (precision / recall / f1 / support):

```
             precision  recall     f1  support
label                                         
industry         0.833   1.000  0.909        5
operations       1.000   0.909  0.952       22
policy           0.750   1.000  0.857        6
procurement      0.875   0.875  0.875        8
technology       1.000   0.923  0.960       13
```
macro-F1: 0.911

disagreements (4):
- true=operations pred=policy x2 [g013, g053]
- true=procurement pred=industry x1 [g020]
- true=technology pred=procurement x1 [g038]

### judge vs human -- 92.6% (50/54)

```
rows = truth, columns = prediction
predicted    industry  operations  policy  procurement  technology
true                                                              
industry            5           0       0            0           0
operations          0          20       2            0           0
policy              0           0       6            0           0
procurement         1           0       0            7           0
technology          0           0       1            0          12
```

per-label (precision / recall / f1 / support):

```
             precision  recall     f1  support
label                                         
industry         0.833   1.000  0.909        5
operations       1.000   0.909  0.952       22
policy           0.667   1.000  0.800        6
procurement      1.000   0.875  0.933        8
technology       1.000   0.923  0.960       13
```
macro-F1: 0.911

disagreements (4):
- true=operations pred=policy x2 [g013, g053]
- true=procurement pred=industry x1 [g020]
- true=technology pred=policy x1 [g011]

### workhorse vs judge -- 96.3% (52/54)

```
rows = truth, columns = prediction
predicted    industry  operations  policy  procurement  technology
true                                                              
industry            6           0       0            0           0
operations          0          20       0            0           0
policy              0           0       8            0           0
procurement         0           0       0            7           1
technology          0           0       1            0          11
```

disagreements (2):
- true=procurement pred=technology x1 [g038]
- true=technology pred=policy x1 [g011]

## Operational domain

### workhorse vs human -- 92.6% (50/54)

```
rows = truth, columns = prediction
predicted  air  cyber  land  multi  sea  space
true                                          
air         14      0     1      0    0      0
cyber        0      5     0      1    0      0
land         0      0    11      0    0      0
multi        1      0     0      9    0      0
sea          0      0     0      1    8      0
space        0      0     0      0    0      3
```

per-label (precision / recall / f1 / support):

```
       precision  recall     f1  support
label                                   
air        0.933   0.933  0.933       15
cyber      1.000   0.833  0.909        6
land       0.917   1.000  0.957       11
multi      0.818   0.900  0.857       10
sea        1.000   0.889  0.941        9
space      1.000   1.000  1.000        3
```
macro-F1: 0.933

disagreements (4):
- true=air pred=land x1 [g021]
- true=cyber pred=multi x1 [g056]
- true=multi pred=air x1 [g034]
- true=sea pred=multi x1 [g043]

### judge vs human -- 98.1% (53/54)

```
rows = truth, columns = prediction
predicted  air  cyber  land  multi  sea  space
true                                          
air         15      0     0      0    0      0
cyber        0      6     0      0    0      0
land         0      0    11      0    0      0
multi        0      0     0     10    0      0
sea          0      0     0      1    8      0
space        0      0     0      0    0      3
```

per-label (precision / recall / f1 / support):

```
       precision  recall     f1  support
label                                   
air        1.000   1.000  1.000       15
cyber      1.000   1.000  1.000        6
land       1.000   1.000  1.000       11
multi      0.909   1.000  0.952       10
sea        1.000   0.889  0.941        9
space      1.000   1.000  1.000        3
```
macro-F1: 0.982

disagreements (1):
- true=sea pred=multi x1 [g043]

### workhorse vs judge -- 94.4% (51/54)

```
rows = truth, columns = prediction
predicted  air  cyber  land  multi  sea  space
true                                          
air         14      0     0      1    0      0
cyber        0      5     0      0    0      0
land         1      0    11      0    0      0
multi        0      1     0     10    0      0
sea          0      0     0      0    8      0
space        0      0     0      0    0      3
```

disagreements (3):
- true=air pred=multi x1 [g034]
- true=land pred=air x1 [g021]
- true=multi pred=cyber x1 [g056]

## Region

### workhorse vs human -- 87.0% (47/54)

```
rows = truth, columns = prediction
predicted     africa  americas  europe  global  indo-pacific  middle-east
true                                                                     
africa             2         0       0       0             0            0
americas           0        22       0       0             0            0
europe             0         0       1       0             0            0
global             0         6       0      12             1            0
indo-pacific       0         0       0       0             5            0
middle-east        0         0       0       0             0            5
```

per-label (precision / recall / f1 / support):

```
              precision  recall     f1  support
label                                          
africa            1.000   1.000  1.000        2
americas          0.786   1.000  0.880       22
europe            1.000   1.000  1.000        1
global            1.000   0.632  0.774       19
indo-pacific      0.833   1.000  0.909        5
middle-east       1.000   1.000  1.000        5
```
macro-F1: 0.927

disagreements (7):
- true=global pred=americas x6 [g017, g019, g026, g047, g048, g054]
- true=global pred=indo-pacific x1 [g013]

### judge vs human -- 100.0% (54/54)

```
rows = truth, columns = prediction
predicted     africa  americas  europe  global  indo-pacific  middle-east
true                                                                     
africa             2         0       0       0             0            0
americas           0        22       0       0             0            0
europe             0         0       1       0             0            0
global             0         0       0      19             0            0
indo-pacific       0         0       0       0             5            0
middle-east        0         0       0       0             0            5
```

per-label (precision / recall / f1 / support):

```
              precision  recall   f1  support
label                                        
africa              1.0     1.0  1.0        2
americas            1.0     1.0  1.0       22
europe              1.0     1.0  1.0        1
global              1.0     1.0  1.0       19
indo-pacific        1.0     1.0  1.0        5
middle-east         1.0     1.0  1.0        5
```
macro-F1: 1.000

disagreements (0):
- none

### workhorse vs judge -- 87.0% (47/54)

```
rows = truth, columns = prediction
predicted     africa  americas  europe  global  indo-pacific  middle-east
true                                                                     
africa             2         0       0       0             0            0
americas           0        22       0       6             0            0
europe             0         0       1       0             0            0
global             0         0       0      12             0            0
indo-pacific       0         0       0       1             5            0
middle-east        0         0       0       0             0            5
```

disagreements (7):
- true=americas pred=global x6 [g017, g019, g026, g047, g048, g054]
- true=indo-pacific pred=global x1 [g013]
