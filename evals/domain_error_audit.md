# Domain-axis disagreement audit -- no viable clause (2026-08-23)

**Method.** The 42 operational_domain disagreements between the shipped classifier
(prompt b0202d06...) and the frozen Opus judge key at effective n=595 were scored by
three independent Opus analysts (rubric adjudication, textual mechanism, multi-boundary
rule search), then merged under a majority rule: a row counts as a model error only when
at least 2 of 3 lenses agree. Data: the committed region_clause_*candidate.csv arms and
scale_*predictions*.csv keys -- no API call was made for this audit.

**The pre-set viability bar:** a clause target needs >= 15 majority model-error rows
sharing one decidable rule, because the n=595 McNemar design has ~0.9 power at a +3%
net effect and only ~0.5 at +2% (src/mcnemar_power.py). The bar was fixed before the
analysis ran.

**Verdict: no cluster reaches the bar.** No clause to write. The 42 domain disagreements hold only 23 majority model errors, and they split across seven mechanisms of which the largest carries six rows -- far below the 15 rows a decidable McNemar experiment at n=595 needs. The best cluster is air-and-missile-defense-is-air (s145, s481, s478, s479, s485, s258): the model labels ground-owned air-defense units by the owning service instead of the threat they engage, the rubric already states the rule, and the clause cannot lose a row on this set. It still tops out at six. The second cluster, organizational-jointness-is-not-multi, also carries six, and the two cannot be merged because they contradict each other on whether a unit name decides the domain. The answer key is also unstable in the two clusters that would otherwise be biggest: s370 and s371 are the same snippet with opposite key labels, s478/s479 conflict with s468 on the same battalion type, and s308 conflicts with s351. The honest next step is to re-adjudicate the domain key, not to write a prompt clause.

## The cluster map

### air-and-missile-defense-is-air

- rows: s145, s481, s478, s479, s485, s258, s147, s468, s496
- majority model errors (6): s145, s481, s478, s479, s485, s258
- majority judge errors: (none)
- the rule a clause would state: When the subject is a unit, system, or program whose named mission is to detect, track, or engage aircraft, missiles, or UAS -- Air Defense Artillery, Patriot, Avenger, Stinger, SHORAD, counter-UAS, integrated air and missile defense -- label air, even when a ground service owns and operates it and even when the described activity is a ceremony, a movement, or routine training.

Nine of 42 rows, six majority model errors. All six are land->air or multi->air where the model followed the owning ground service ('PEO Land Systems', 'Soldiers', 'Army National Guard') or the word 'Joint' in a command name, instead of the threat the system engages. The rubric already carries the clause 'an airstrike, close-air-support mission, or air-and-missile-defense story is air', so this is a strengthening, not a new rule, and it stays lexical and decidable at classification time. On this 42-row set the clause cannot lose a row: the three rows where the key says land or multi (s147, s468, s496) are already predicted air. Two properties cap it. First, the ceiling is six fixed rows against a bar of 15. Second, the answer key is internally inconsistent here: s478 and s479 (ADA change of command, ADA movement) are keyed air while s468 (ADA annual training) is keyed land, on equally generic activity. A clause that ships the s478/s479 reading is graded wrong on s468 by the same ruler.

### organizational-jointness-is-not-multi

- rows: s191, s426, s423, s448, s455, s203, s421, s438, s187
- majority model errors (6): s191, s426, s423, s448, s455, s203
- majority judge errors: (none)
- the rule a clause would state: The word 'joint' or 'combined' inside an organization, task-force, base, or program-office name, and a list of participating services or service-member nouns ('Sailors and Marines', 'Army and Air'), are naming and composition, not evidence of two domains: label the medium in which the described activity happens, and use multi only when the snippet states the joint character of the activity itself or places different participants in different media.

Nine rows, six majority model errors, and the second-largest cluster. Five are multi->specific over-use (s191 tents in a field, s426 detention ashore, s423 defueling a fixed fuel farm, s448 and s455 an ARG/MEU getting underway, which the existing amphibious bullet already assigns to sea). s203 is the inverse: the model followed 'Ordnance Companies' to land while the text said 'participated in a joint forces training exercise', which is the activity-level wording the rubric already names as a multi trigger, so the second half of the rule is what reaches it. Three problems. It is six rows, not 15. The key applies the same fallacy on its own side in s421 and s438, which no clause can score. And it directly contradicts the air-and-missile-defense cluster, which says a unit name does decide the domain -- so the two biggest clusters cannot be merged into one rule even to reach 12 rows.

### owning-institution-anchors-a-domainless-story

- rows: s295, s252, s246, s351, s259, s288, s308, s138
- majority model errors (4): s295, s252, s246, s351
- majority judge errors: s308
- the rule a clause would state: An enumeration of programs, research areas, threats, or weapon types inside a visit, laboratory-portfolio, or overview story is background breadth, not a joint operation: do not use multi for it, and take the domain of the host organization or of the dominant items in the list.

Eight rows, four majority model errors, all multi->specific over-use where the model read a comma list as domain spanning (Dahlgren's ODIN and long-range fires, Arnold's aeropropulsion and space systems, the Navy Nurse Corps). The key resolves these by the owning institution -- NSWC Dahlgren to sea, Secretary of the Air Force to air, Navy Nurse Corps to sea. That rule is nowhere in the prompt and it is the exact inverse of the adopted region clause, which says a US institution is not an American theater. The asymmetry is defensible (a theater is a place, a domain is a competence) but adopting it needs its own ADR, not a clause. The key also contradicts itself inside the cluster: s308 (Air Mobility Command STEM outreach) is keyed multi while s351 (Navy Nurse Corps) is keyed sea, on the same shape.

### capability-versus-its-carrier

- rows: s074, s516, s297, s056, s301
- majority model errors (2): s074, s516
- majority judge errors: s056
- the rule a clause would state: A platform that carries, delivers, launches, or hosts something takes the label only when the movement itself is the story: when the carried capability, payload, or mission is the grammatical subject of the main verb and the platform sits in a prepositional phrase ('aboard', 'via', 'mounted on', 'in the realm of'), label the capability's domain.

Five rows, two majority model errors. s074 is the clean case in one direction (a C-5M airlift squadron delivering a satellite is air; the model labeled the cargo) and s516 in the other (an EC-47Q whose subject is electronic-warfare collection is cyber; the model labeled the platform). The rubric already owns half this ground with its cyber-versus-host-platform bullet, and the proposed rule only generalizes it beyond cyber. Too small to measure at two rows, and the remaining three are contested: s056 is a majority judge error where the model applied the existing cyber bullet correctly, and s297 is a live collision between the cyber bullet and the owning-institution anchor that any ADR touching cluster 3 would have to resolve first.

### multi-as-the-no-domain-catch-all

- rows: s367, s151, s549, s541, s400, s371, s370
- majority model errors (2): s367, s151
- majority judge errors: s400, s541, s371, s370
- the rule a clause would state: When the snippet describes no activity in any physical medium -- a policy statement, an acquisition rule, force-structure numbers, a medical or education programme, an academic talk -- label multi, which is the domain-neutral catch-all in the same way global is the region catch-all.

Seven rows and the structural root of the axis, but the worst clause target in the set: two majority model errors against four majority judge errors. The rubric defines multi only as 'spanning more than one domain', so a story that spans zero domains has nowhere legal to go, and the key resolves these rows by no rule at all -- multi in s367, s151, s549, land in s541, s400, s370, multi in s371. The proof that no clause can score here is the s370/s371 pair: the same Dover AFB media-filming snippet appears twice, the key labels one land and one multi, and the model labels them the opposite way round. Exactly one of the two key labels must be wrong whatever the clause says. This cluster needs the key re-adjudicated before any measurement, not a prompt clause.

### missile-classified-by-its-employment

- rows: s248, s126
- majority model errors (2): s248, s126
- majority judge errors: (none)
- the rule a clause would state: Classify a missile or rocket by how it is employed, not by the noun: a weapon that flies through the atmosphere against air, ballistic, or distant strategic targets is air, and a surface-to-surface artillery rocket fired by a ground fires unit is land.

Two rows, both majority model errors, and they point in opposite directions: s248 is land->air (an Army hypersonic missile) and s126 is air->land (Army ER GMLRS rockets). The underlying defect is the rubric line 'air: aircraft, missiles, UAVs', which over-pulls every surface-to-surface weapon into air on the strength of one noun. The key does not settle the question either -- it calls one Army surface-launched weapon air and the other land -- so the rule above cannot be graded against it without relabeling first. Two rows regardless, which is far below any decidable design.

### air-fires-inside-a-ground-action

- rows: s235, s230
- majority model errors (1): s235
- majority judge errors: (none)
- the rule a clause would state: Label multi when the snippet describes a ground-force action with its own verb (arrest, detain, patrol, clear, return fire) and an air-delivered fires event; label air when the only described action is the strike itself.

Two rows, one majority model error. s235 (an airstrike supporting a ground arrest that produced detentions) matches the rubric's own worked example 'Coalition aircraft conduct airstrike on insurgent position during ground firefight -> multi' almost verbatim, which suggests the 'air action over a ground setting is still air' bullet over-fires against its own example. That is a real internal tension worth an amendment, but it is one row on this ruler. s230 names no aircraft at all ('precision guided munitions' can be ground-launched), so its air half is inferred, and no lens majority calls it either way.

## What this audit is evidence FOR

The domain axis bottleneck is the RULER, not only the model. Ten-plus rows are majority
judge errors, and the key contradicts itself inside its own labels: s370/s371 are the
same snippet keyed land and multi; s478/s479 (ADA ceremony/movement, keyed air) conflict
with s468 (ADA annual training, keyed land); s308 conflicts with s351 on the same shape.
The rubric also has a structural gap the key resolves by no rule at all: multi is defined
only as spanning MORE than one domain, so a story spanning zero domains (policy text,
force-structure numbers, a medical programme) has no legal label. Any future domain-axis
work starts with re-adjudicating the key and closing the zero-domain gap -- a measurement
against this key at these margins scores the key noise, not the model.

Full lens-level outputs are in the session workflow journal (not committed); this file is
the durable record. See decisions/verdicts.md for the dated row.
