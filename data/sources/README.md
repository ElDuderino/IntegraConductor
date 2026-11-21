# Bundled source data

| File | Role | SHA-256 |
|---|---|---|
| `roland-integra-7-full.txt` | Primary import source | `0aabf41e92e5d2bdcb312896b6f08c16f6b14c97504266093dedf97476b92dca` |
| `roland-integra-7.txt` | Comparison source (marked *incomplete* upstream) | `21ff1340cc377c7a960431263bc57b55357198c87307ba36b9146e0b4a835098` |
| `LICENSE-integra7-cubase.txt` | Upstream license (Apache-2.0) | |

Both scripts are unmodified copies from <https://github.com/odashi/integra7-cubase>
at commit `b919bea1abb25723e6ccd970d9e17f68c7e0d668`, retrieved 2026-11-20.
Copyright belongs to their authors (odashi; `roland-integra-7-full.txt` credits
Michael Long). They are redistributed under the Apache License 2.0.

The files are stored byte-for-byte (CRLF line endings, UTF-8 with a few
non-ASCII characters); `.gitattributes` disables line-ending conversion for
them so the hashes above stay valid. Do not edit them: corrections belong in
the importer, where they are recorded as issues.

To refresh from upstream:

```bash
base=https://raw.githubusercontent.com/odashi/integra7-cubase/master
curl -fsSL -o data/sources/roland-integra-7-full.txt "$base/roland-integra-7-full.txt"
curl -fsSL -o data/sources/roland-integra-7.txt "$base/roland-integra-7.txt"
sha256sum data/sources/*.txt      # update the table above
integra7 patches import && integra7 patches audit
```
