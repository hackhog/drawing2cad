# Independent AP242 inspection

The Linux image builds a fixed STEPcode revision and its AP242 schema library.
The maintained `reader.cc` adapter reads the STEP file with that library. It does
not use OCCT or the drawing2cad Part 21 parser. The Python worker applies Landlock,
seccomp, and resource limits before it replaces itself with the fixed executable.
There is no child process, network request, GUI, or unrestricted fallback.

## Reproducible build

| Item | Value |
| --- | --- |
| STEPcode revision | `24783b448511b8f6bce2829286a3f00015430236` |
| Source archive SHA-256 | `8fec5d2d3899dfd9de70adc8c0b7e779a75032368087819a8572aabc59ec0ff1` |
| EXPRESS file | `data/ap242/242_mim_lf.exp` |
| EXPRESS SHA-256 | `32ced62e799a50cc857966ab6702adcbc5b0da00be290f232dcea275652059cf` |
| Schema document identifier in the source | ISO TC184/SC4/WG12 N11521 |
| C++ generator API | `SC_EXP2CXX_API_VERSION=2` |
| Installed executable | `/usr/local/bin/drawing2cad-stepcode` |

The Dockerfile builds the static `sdai_ap242-static` target first. It then builds
`reader_sdai_ap242`. This keeps the schema compilation in a separate cache layer.
The image retains STEPcode's `COPYING`, `AUTHORS`, and `INTENT.md` files. STEPcode
and its generated library use the upstream 3-clause BSD terms.

## Tested inspection scope

The reader uses strict `ReadExchangeFile` and `VerifyInstances`. It checks the
schema name and reports parser severity, entity counts, schema hash, input hash,
and diagnostics. An error, an incomplete required attribute, an unknown entity,
or a wrong reference type cannot receive a passed schema-read result.

The reader also supplies a bounded inventory of typed PMI and product attributes.
`adapters/stepcode_pmi.py` checks that inventory against the resolved build contract.
It does not parse STEP bytes. The supported graph profile checks:

- One diameter or linear-distance representation for each nominal dimension.
- A positive finite nominal value and the expected identifier, kind, and value.
- Millimetre units shared with the BREP representation context.
- Product links from each shape aspect to the BREP product.
- Face references that belong to the closed shell of the product solid.
- Distinct faces for a linear dimension.
- Rejection of tolerance, datum, and other unsupported PMI types.

The graph check rejects an incomplete inventory. The inventory limit is 96,000
bytes. Construction payloads and descriptive evidence text are not copied into
the inventory. Global entity counts remain complete when the inventory limit is
reached. Inputs remain subject to the worker's 32 MiB file limit, time limit,
memory limit, and output limit.

Names support apostrophes, escaped backslashes, and STEP X, X2, and X4 character
encoding. Other legacy character-page escapes are rejected. If the file has no
nominal dimensions, the report states a zero count and does not claim a product
graph check for absent dimensions.

This encoding support applies to the independent reader. The current part schema
restricts generated product names to `^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$`.
The encoding tests modify separate diagnostic STEP copies; they do not establish
end-to-end construction or export support for names outside that pattern.

## Claims that remain separate

A passed result is not full AP242 conformity. STEPcode does not evaluate all
EXPRESS WHERE, UNIQUE, inverse-cardinality, or global rules in this adapter.
The reader matches the schema name; it does not certify the file's edition or
ASN.1 identifier against the schema document. The latest included schema is not
an edition-specific proof for the OCCT writer's AP242 identifier.

The nominal graph check does not measure the referenced faces or establish that
the nominal value matches their geometry. It does not inspect rendered PMI,
readability, complete GD&T, or target-CAD behavior. These results stay separate
from fresh-worker geometry validation and visual inspection.

## Primary sources

- [STEPcode source and license](https://github.com/stepcode/stepcode/tree/24783b448511b8f6bce2829286a3f00015430236)
- [Build instructions](https://github.com/stepcode/stepcode/blob/24783b448511b8f6bce2829286a3f00015430236/INSTALL)
- [Included schema documentation](https://stepcode.github.io/docs/included_schemas/)
- [Pinned AP242 EXPRESS schema](https://github.com/stepcode/stepcode/blob/24783b448511b8f6bce2829286a3f00015430236/data/ap242/242_mim_lf.exp)

The NIST STEP File Analyzer remains an optional external acceptance tool. Its
Windows and Excel requirements cannot be required by this headless Linux service.
