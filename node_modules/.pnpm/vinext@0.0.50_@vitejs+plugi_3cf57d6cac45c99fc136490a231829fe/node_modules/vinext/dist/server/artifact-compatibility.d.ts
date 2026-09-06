//#region src/server/artifact-compatibility.d.ts
declare const ARTIFACT_COMPATIBILITY_SCHEMA_VERSION = 1;
declare const APP_ELEMENTS_SCHEMA_VERSION = 1;
declare const RSC_PAYLOAD_SCHEMA_VERSION = 1;
type ArtifactCompatibilityEnvelope = Readonly<{
  schemaVersion: typeof ARTIFACT_COMPATIBILITY_SCHEMA_VERSION;
  graphVersion: string | null;
  deploymentVersion: string | null;
  appElementsSchemaVersion: typeof APP_ELEMENTS_SCHEMA_VERSION;
  rscPayloadSchemaVersion: typeof RSC_PAYLOAD_SCHEMA_VERSION;
  rootBoundaryId: string | null;
  renderEpoch: string | null;
}>;
type ArtifactCompatibilityEnvelopeInput = Readonly<{
  graphVersion?: string | null;
  deploymentVersion?: string | null;
  rootBoundaryId?: string | null;
  renderEpoch?: string | null;
}>;
type ArtifactCompatibilityFallback = "renderFresh";
type ArtifactCompatibilityUnknownReason = "graphVersionUnknown" | "deploymentVersionUnknown" | "rootBoundaryIdUnknown" | "renderEpochUnknown";
type ArtifactCompatibilityIncompatibleReason = "appElementsSchemaVersionMismatch" | "deploymentVersionMismatch" | "graphVersionMismatch" | "renderEpochMismatch" | "rootBoundaryIdMismatch" | "rscPayloadSchemaVersionMismatch" | "schemaVersionMismatch";
type ArtifactCompatibilityDecision = Readonly<{
  kind: "compatible";
} | {
  kind: "unknown";
  fallback: ArtifactCompatibilityFallback;
  reason: ArtifactCompatibilityUnknownReason;
} | {
  kind: "incompatible";
  fallback: ArtifactCompatibilityFallback;
  reason: ArtifactCompatibilityIncompatibleReason;
}>;
type ArtifactCompatibilityGraphVersionInput = Readonly<{
  routePattern: string;
  rootBoundaryId: string | null;
}>;
declare function createArtifactCompatibilityEnvelope(input?: ArtifactCompatibilityEnvelopeInput): ArtifactCompatibilityEnvelope;
declare function createArtifactCompatibilityGraphVersion(input: ArtifactCompatibilityGraphVersionInput): string;
declare function parseArtifactCompatibilityEnvelope(value: unknown): ArtifactCompatibilityEnvelope | null;
declare function evaluateArtifactCompatibility(current: ArtifactCompatibilityEnvelope, candidate: ArtifactCompatibilityEnvelope): ArtifactCompatibilityDecision;
//#endregion
export { APP_ELEMENTS_SCHEMA_VERSION, ARTIFACT_COMPATIBILITY_SCHEMA_VERSION, ArtifactCompatibilityEnvelope, RSC_PAYLOAD_SCHEMA_VERSION, createArtifactCompatibilityEnvelope, createArtifactCompatibilityGraphVersion, evaluateArtifactCompatibility, parseArtifactCompatibilityEnvelope };
//# sourceMappingURL=artifact-compatibility.d.ts.map