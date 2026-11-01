# GII fixtures (T2.2)

Real norms of the pinned Gesetze-im-Internet files (`data/sources.yaml`, downloaded 2026-10-31), kept
byte-exact: the XML declaration and `DOCTYPE` line, the `<dokumente>` element with its real `builddate`,
and a selection of complete `<norm>` elements. No wording was edited; only the Inhaltsübersicht of `bgb_sample.xml` was cut to its first 12
entries, and the files were re-serialised by lxml, which writes `&quot;` in text as `"` (two places in the
header norm of `bgb_sample.xml`).

| File | Law | Norms |
| --- | --- | --- |
| `kschg_1.xml` | KSchG | law header, § 1 |
| `arbzg_3.xml` | ArbZG | law header, § 3 |
| `aktg_95.xml` | AktG | law header, § 95 (a table) |
| `bgb_sample.xml` | BGB | header, Inhaltsübersicht (cut), § 14 (footnotes), § 612a, § 622 (lists), `(XXXX) §§ 3 bis 6`, § 10 (weggefallen) |
| `egbgb_sample.xml` | EGBGB (`jurabk` `BGBEG`) | header, Art 1, Art 246a § 1, `Art 27 bis 37`, Anlage 1 |
| `kwg_53ca.xml` | KWG (`jurabk` `KredWG` in the header) | header, § 53ca (two-letter suffix), § 25a |
| `aktg_159.xml` | AktG | header, § 159 (text `-`), § 95 |
| `betrvg_122.xml` | BetrVG | header, § 122 and § 132 (only parenthesised lines), § 1 |

Licence: official works, § 5 Abs. 1 UrhG ("Gesetzestexte: Bundesministerium der Justiz / juris GmbH,
www.gesetze-im-internet.de. Amtliche Werke gemäß § 5 UrhG."; `DATA_LICENSES.md` section 3).
