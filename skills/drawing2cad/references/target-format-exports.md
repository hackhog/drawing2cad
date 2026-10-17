# Optional final exports for NX and SOLIDWORKS

This reference assesses target formats and adapter effort. It does not implement an export tool.
Use it when the request includes another CAD format after the verified STEP AP242 master.
The skill continues to use only drawing2cad-mcp.

## Sequence and source authority

Use this sequence:

1. Create and review the controlling technical drawing.
2. Build and verify the parametric model.
3. Export AP242 and complete the required reconstruction, change, and PMI tests.
4. Create the requested target-format derivative from that verified master.
5. Reopen the derivative in the specified target version and verify the requested claims.

STEP remains the master. A derivative is an additional delivery artifact.
Keep the master unchanged and record its hash in the derivative manifest.
Do not make upstream modeling depend on an optional final-format adapter.
If the derivative fails, report its failure separately from the master status.

For a claim of STEP-only reconstruction, the worker can use only STEP as the source of model content.
The worker can decode the supported construction profile into neutral data before it calls the target API.
Do not supply a hidden model contract, source CAD file, or prior session to replace missing STEP data.
Unsupported operations, relations, or PMI types must produce explicit failures.

A change made later in NX or SOLIDWORKS creates a new candidate.
It does not update the master automatically.
Require a controlled drawing revision and the applicable round-trip tests before master replacement.

## Deliverable levels

| Delivery | Expected use | Construction and PMI limits |
|---|---|---|
| Existing AP242 opened in NX or SOLIDWORKS | Geometry exchange and supported PMI inspection. | A standard import does not establish native construction history. Verify PMI type and association coverage. |
| Parasolid `.x_t` or `.x_b` | Optional geometry exchange through a compatible licensed writer. | Do not claim transferable feature history or the required AP242 PMI package from a geometry-only profile. Pin the Parasolid version. |
| NX `.prt` or SOLIDWORKS `.sldprt` with an imported body | Convenient native container for imported geometry. | Native file extension does not establish sketches, driving parameters, or editable feature history. |
| Native file with reconstructed features | Native sketches, constraints, expressions, extrusions, cuts, bores, and fillets within a declared profile. | Requires a separate target adapter and actual parameter-change tests. |
| Native file with native PMI | Target-native dimension and annotation objects associated with the rebuilt geometry. | Editable annotations and driving dimensions remain separate claims. Verify both when required. |

Saving an imported body as a native file does not meet the editable-construction requirement.
Direct face editing and feature recognition can help users. They do not prove recovery of the declared construction graph.
SOLIDWORKS documents loss of feature history for ordinary neutral geometry exchange.
See [SOLIDWORKS file compatibility](https://blogs.solidworks.com/products/solidworks/solidworks-backwards-compatibility/).

## Target-specific findings

### NX

Siemens documents bidirectional AP242 geometry exchange, semantic and graphical part PMI, and command-line translation.
The cited white paper describes edition 1. Verify the selected release and edition separately.
See the [Siemens standards white paper](https://www.plm.automation.siemens.com/media/global/fr/Siemens%20PLM%20Realizing%20a%20Digital%20Enterprise%20driven%20by%20Standards_tcm55-62124.pdf).

NX can convert supported imported PMI into editable native PMI.
This conversion does not establish driving geometry parameters or reconstructed features.
See [Convert Imported PMI](https://blogs.sw.siemens.com/designcenter/converting-imported-product-manufacturing-information-within-siemens-nx/).

Use an NX Open adapter to construct native features from the decoded graph.
Confirm author, runtime, feature, and translator entitlements for the selected deployment.
Siemens documents batch execution and add-on interfaces. These documents do not certify every operation on every server platform.
See [NX programming and customization](https://www.plm.automation.siemens.com/en_us/Images/4988_tcm1023-4564.pdf)
and [NX add-on modules](https://static.sw.cdn.siemens.com/siemens-disw-assets/public/1q2lFS1n8i2eRYhE17952p/en-US/Siemens%20SW%20NX%20Mach%20Series%20add%20on%20modules%20Fact%20Sheet.pdf).

### SOLIDWORKS

SOLIDWORKS 2026 describes imported AP242 PMI as semantic, noneditable annotations.
The API can query semantic data. Imported PMI is not automatically an editable native dimension.
See [Import PMI](https://help.solidworks.com/2026/english/SolidWorks/sldworks/c_import_pmi.htm).

Use the full modeling API to create native features and save the part.
Document Manager can access document data without a SOLIDWORKS installation.
Its documented access functions do not establish a replacement feature-modeling engine.
See the [API application overview](https://help.solidworks.com/2025/english/api/sldworksapiprogguide/GettingStarted/SolidWorks_API_Standalone_and_Add-in_Applications_Overview.htm)
and [Document Manager capabilities](https://help.solidworks.com/2024/english/api/swdocmgrapi/GettingStarted-swdocmgrapi.html).

The published system requirements distinguish SOLIDWORKS client products from server products such as PDM and the license manager.
An invisible application or supported virtual machine does not prove a session-free modeling worker.
Do not promise Linux Docker execution or a supported Windows service without release-specific evidence.
See [SOLIDWORKS system requirements](https://www.solidworks.com/support/system-requirements).

### Translation SDKs

A format listed as readable is not necessarily writable.
For example, HOOPS Exchange lists NX and SOLIDWORKS as read-only formats.
Its general CAD support does not supply a native feature writer for these targets.
See the [HOOPS format matrix](https://www.techsoft3d.com/developers/products/hoops-exchange/).

## Preliminary effort estimate

These ranges are engineering estimates, not vendor statements or delivery commitments.
One person-week is five working days for one developer with CAD API experience.
Estimate the optional adapters after the common drawing, AP242, decoder, and validation services exist.
That common implementation is additional work.

Assume one target release, available licenses, and simple single mechanical parts.
The feature profile covers rectangular or circular sketches, extrusions, cuts, bores, constant-radius fillets, simple relations, and nominal PMI.
Exclude assemblies, sheet metal, freeform surfaces, arbitrary feature inference, and general GD&T.
Exclude procurement time, license fees, and support for multiple CAD releases.

| Incremental work | Preliminary effort | Main uncertainty |
|---|---|---|
| Verify existing AP242 import in one target | 3-10 person-days per target | Required PMI types, target settings, units, and import differences. |
| Automate NX import and save an imported-body `.prt` | 1-2 person-weeks | Batch setup, entitlements, error handling, and reopen tests. |
| Automate SOLIDWORKS import and save an imported-body `.sldprt` | 2-4 person-weeks | Application lifetime, source links, unattended execution, and reopen tests. |
| NX native feature reconstruction pilot | 6-12 person-weeks | Feature mapping, constraints, topology references, simple PMI, and change tests. |
| SOLIDWORKS native feature reconstruction pilot | 8-16 person-weeks | Feature mapping, rebuild behavior, native PMI, and execution dependencies. |
| Production qualification after a successful pilot | 4-8 additional person-weeks per target | Isolation, cancellation, recovery, repeated runs, deployment, and regression coverage. |

Each pilot estimate includes its import/save path. Do not add the imported-body estimate to the feature pilot estimate.
Production qualification is additional. These ranges do not cover creation of a general STEP feature-inference engine.
If the master lacks supported construction data, reassess the plan before implementation.
If a session-free runtime is unavailable, no effort allowance makes that deployment satisfy the headless requirement.

## Adapter acceptance

Record target product, exact version, adapter revision, execution mode, master hash, and output hashes.
Record geometry, construction, parameter relations, semantic PMI, graphical PMI, and review markers separately.

1. Reopen the native file in a fresh target session.
2. Verify units, solid count, geometry, and required PMI against the master.
3. Confirm native feature types and dimension mappings within the supported profile.
4. Change a driving parameter and measure its dependent effects.
5. Save, close, and reopen the changed file.
6. Verify the change and affected PMI associations again.
7. Record unsupported data and any required source-file links.
8. Test all required operations without a GUI session before a headless production claim.

Native technical drawings, such as `.slddrw`, need a separate drafting adapter and estimate.
They are not included in the model export ranges.

First investigate NX batch execution and the required feature subset.
Keep SOLIDWORKS as an optional target until its required runtime passes the same headless acceptance.
This sequence is a planning recommendation. No native exporter has been implemented or benchmarked here.
