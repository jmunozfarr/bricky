import { Group } from "three";

import {
  isPlaybackEntryVisible,
  PlaybackVisibilityEntry,
} from "./hierarchicalPlayback";

const occurrenceNamePattern = /^__bricky_occ_(\d+)\.ldr$/;
const nodeNamePattern = /^__bricky_node_(\d+)\.ldr$/;

export interface ManifestOccurrence {
  occurrenceId: string;
  parentOccurrenceId: string | null;
  attachmentStep: number | null;
  traversalPosition: number;
  definitionName: string;
}

export interface ManifestPart {
  instructionNodeId: string;
  occurrenceId: string;
  localStep: number;
  traversalPosition: number;
}

export interface InstructionSourceManifest {
  version: number;
  rootOccurrenceId: string;
  occurrences: Map<string, ManifestOccurrence>;
  parts: Map<string, ManifestPart>;
  rootWrapped: boolean;
}

export interface SceneIndexEntry extends PlaybackVisibilityEntry {
  definitionName: string;
  instructionNodeId: string | null;
  traversalPosition: number;
  group: Group;
}

export interface InstructionSceneIndex {
  rootOccurrenceId: string;
  entries: SceneIndexEntry[];
  objectCount: number;
}

export class InstructionSceneIndexError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InstructionSceneIndexError";
  }
}

function decodeName(value: string): string {
  const padded = value.padEnd(Math.ceil(value.length / 4) * 4, "=");
  try {
    const binary = atob(padded.replaceAll("-", "+").replaceAll("_", "/"));
    return new TextDecoder().decode(
      Uint8Array.from(binary, (character) => character.charCodeAt(0)),
    );
  } catch {
    throw new InstructionSceneIndexError("Derived source contains an invalid definition name.");
  }
}

export function parseInstructionSourceManifest(text: string): InstructionSourceManifest {
  let version: number | null = null;
  let rootOccurrenceId: string | null = null;
  const occurrences = new Map<string, ManifestOccurrence>();
  const parts = new Map<string, ManifestPart>();
  let rootWrapped = false;

  for (const line of text.split(/\r?\n/)) {
    const tokens = line.trim().split(/\s+/);
    if (tokens.slice(0, 3).join(" ") === "0 !BRICKY DERIVED_SOURCE") {
      version = Number(tokens[3]);
    } else if (tokens.slice(0, 3).join(" ") === "0 !BRICKY ROOT") {
      rootOccurrenceId = tokens[3] ?? null;
    } else if (tokens.slice(0, 3).join(" ") === "0 !BRICKY ROOT_WRAPPED") {
      rootWrapped = tokens[3] === "1";
    } else if (tokens.slice(0, 3).join(" ") === "0 !BRICKY OCCURRENCE") {
      const [occurrenceId, parent, attachment, traversal, encodedName] = tokens.slice(3);
      if (!occurrenceId || !parent || !attachment || !traversal || !encodedName) {
        throw new InstructionSceneIndexError("Derived source occurrence metadata is incomplete.");
      }
      if (occurrences.has(occurrenceId)) {
        throw new InstructionSceneIndexError(`Occurrence ${occurrenceId} appears twice in the manifest.`);
      }
      const attachmentStep = Number(attachment);
      const traversalPosition = Number(traversal);
      if (
        !Number.isInteger(attachmentStep) ||
        attachmentStep < 0 ||
        !Number.isInteger(traversalPosition) ||
        traversalPosition < 1
      ) {
        throw new InstructionSceneIndexError("Derived source occurrence metadata is invalid.");
      }
      occurrences.set(occurrenceId, {
        occurrenceId,
        parentOccurrenceId: parent === "-" ? null : parent,
        attachmentStep: attachmentStep || null,
        traversalPosition,
        definitionName: decodeName(encodedName),
      });
    } else if (tokens.slice(0, 3).join(" ") === "0 !BRICKY PART") {
      const [instructionNodeId, occurrenceId, step, traversal] = tokens.slice(3);
      if (!instructionNodeId || !occurrenceId || !step || !traversal) {
        throw new InstructionSceneIndexError("Derived source part metadata is incomplete.");
      }
      if (parts.has(instructionNodeId)) {
        throw new InstructionSceneIndexError(`Part ${instructionNodeId} appears twice in the manifest.`);
      }
      const localStep = Number(step);
      const traversalPosition = Number(traversal);
      if (
        !Number.isInteger(localStep) ||
        localStep < 1 ||
        !Number.isInteger(traversalPosition) ||
        traversalPosition < 1
      ) {
        throw new InstructionSceneIndexError("Derived source part metadata is invalid.");
      }
      parts.set(instructionNodeId, {
        instructionNodeId,
        occurrenceId,
        localStep,
        traversalPosition,
      });
    }
  }
  if ((version !== 1 && version !== 2) || rootOccurrenceId === null || !occurrences.has(rootOccurrenceId)) {
    throw new InstructionSceneIndexError("Derived source manifest is missing or unsupported.");
  }
  return { version, rootOccurrenceId, occurrences, parts, rootWrapped };
}

function occurrenceIdFromGroupName(name: string): string | null {
  const match = occurrenceNamePattern.exec(name);
  return match ? `occ-${match[1]}` : null;
}

function nodeIdFromGroupName(name: string): string | null {
  const match = nodeNamePattern.exec(name);
  return match ? `node-${match[1]}` : null;
}

export function createInstructionSceneIndex(
  model: Group,
  manifest: InstructionSourceManifest,
): InstructionSceneIndex {
  const entries: SceneIndexEntry[] = [];
  const mappedOccurrences = new Set<string>();
  const mappedParts = new Set<string>();
  let objectCount = 0;

  const addOccurrence = (group: Group, occurrenceId: string) => {
    if (mappedOccurrences.has(occurrenceId)) {
      throw new InstructionSceneIndexError(`Occurrence ${occurrenceId} mapped more than once.`);
    }
    const occurrence = manifest.occurrences.get(occurrenceId);
    if (!occurrence) {
      throw new InstructionSceneIndexError(`Scene contains unknown occurrence ${occurrenceId}.`);
    }
    mappedOccurrences.add(occurrenceId);
    entries.push({
      kind: "occurrence",
      occurrenceId,
      parentOccurrenceId: occurrence.parentOccurrenceId,
      localStep: null,
      attachmentStep: occurrence.attachmentStep,
      definitionName: occurrence.definitionName,
      instructionNodeId: null,
      traversalPosition: occurrence.traversalPosition,
      group,
    });
  };

  model.traverse((object) => {
    objectCount += 1;
    if (!(object instanceof Group)) return;
    const occurrenceId = occurrenceIdFromGroupName(object.name);
    if (occurrenceId !== null) {
      addOccurrence(object, occurrenceId);
      return;
    }
    const instructionNodeId = nodeIdFromGroupName(object.name);
    if (instructionNodeId === null) return;
    if (mappedParts.has(instructionNodeId)) {
      throw new InstructionSceneIndexError(`Part ${instructionNodeId} mapped more than once.`);
    }
    const part = manifest.parts.get(instructionNodeId);
    const owner = part ? manifest.occurrences.get(part.occurrenceId) : null;
    if (!part || !owner) {
      throw new InstructionSceneIndexError(`Scene contains unknown part ${instructionNodeId}.`);
    }
    mappedParts.add(instructionNodeId);
    entries.push({
      kind: "part",
      occurrenceId: part.occurrenceId,
      parentOccurrenceId: part.occurrenceId,
      localStep: part.localStep,
      attachmentStep: null,
      definitionName: owner.definitionName,
      instructionNodeId,
      traversalPosition: part.traversalPosition,
      group: object,
    });
  });

  if (!manifest.rootWrapped && !mappedOccurrences.has(manifest.rootOccurrenceId)) {
    addOccurrence(model, manifest.rootOccurrenceId);
  }

  if (mappedOccurrences.size !== manifest.occurrences.size) {
    throw new InstructionSceneIndexError(
      `Not every occurrence mapped to a scene group (${[...mappedOccurrences].join(", ") || "none"}).`,
    );
  }
  if (mappedParts.size !== manifest.parts.size) {
    throw new InstructionSceneIndexError("Not every local part mapped to a scene group.");
  }
  entries.sort((left, right) => left.traversalPosition - right.traversalPosition);
  return { rootOccurrenceId: manifest.rootOccurrenceId, entries, objectCount };
}

export function applyInstructionSceneVisibility(
  model: Group,
  index: InstructionSceneIndex,
  activeOccurrenceId: string,
  currentStep: number,
): void {
  model.traverse((object) => {
    if (object instanceof Group) object.visible = true;
  });
  for (const entry of index.entries) {
    entry.group.visible = isPlaybackEntryVisible(
      entry,
      activeOccurrenceId,
      currentStep,
    );
  }
}
