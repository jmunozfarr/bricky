import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  UseQueryResult,
} from "@tanstack/react-query";

import {
  CatalogStatus,
  Category,
  getCatalogStatus,
  getCategories,
  getColors,
  getPart,
  LDrawColor,
  PartDetail,
  PartsPage,
  PartsQuery,
  searchParts,
  serializePartsQuery,
} from "../api/catalog";
import { fetchJson } from "../api/client";
import {
  deleteInventoryItem,
  getInventorySummary,
  getInventoryVariants,
  InventoryItem,
  InventoryPage,
  InventoryQuery,
  InventorySummary,
  searchInventory,
  serializeInventoryQuery,
  setInventoryQuantity,
} from "../api/inventory";
import {
  CoverageQuery,
  deleteModel,
  getBuildManifest,
  getModel,
  getModelCoverage,
  getInstructionGraph,
  getInstructionPlayback,
  getModelsReadinessSummary,
  listModels,
  ModelsQuery,
  serializeCoverageQuery,
  serializeModelsQuery,
  uploadModel,
} from "../api/models";

export interface HealthStatus {
  status: string;
  database: string;
}

export function useHealth(): UseQueryResult<HealthStatus> {
  return useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchJson<HealthStatus>("/api/health", signal),
  });
}

export function useCatalogStatus(): UseQueryResult<CatalogStatus> {
  return useQuery({
    queryKey: ["catalog", "status"],
    queryFn: ({ signal }) => getCatalogStatus(signal),
  });
}

export function useCategories(enabled = true): UseQueryResult<Category[]> {
  return useQuery({
    queryKey: ["catalog", "categories"],
    queryFn: ({ signal }) => getCategories(signal),
    enabled,
  });
}

export function useColors(): UseQueryResult<LDrawColor[]> {
  return useQuery({
    queryKey: ["catalog", "colors"],
    queryFn: ({ signal }) => getColors(signal),
  });
}

export function usePartsSearch(input: PartsQuery, enabled = true): UseQueryResult<PartsPage> {
  return useQuery({
    queryKey: ["catalog", "parts", serializePartsQuery(input)],
    queryFn: ({ signal }) => searchParts(input, signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function usePartDetail(partId: string | null): UseQueryResult<PartDetail> {
  return useQuery({
    queryKey: ["catalog", "part", partId],
    queryFn: ({ signal }) => getPart(partId ?? "", signal),
    enabled: partId !== null,
  });
}

export function useInventorySummary(): UseQueryResult<InventorySummary> {
  return useQuery({
    queryKey: ["inventory", "summary"],
    queryFn: ({ signal }) => getInventorySummary(signal),
  });
}

export function useInventorySearch(input: InventoryQuery): UseQueryResult<InventoryPage> {
  return useQuery({
    queryKey: ["inventory", "items", serializeInventoryQuery(input)],
    queryFn: ({ signal }) => searchInventory(input, signal),
    placeholderData: keepPreviousData,
  });
}

export function useInventoryVariants(partId: string | null): UseQueryResult<InventoryItem[]> {
  return useQuery({
    queryKey: ["inventory", "variants", partId],
    queryFn: ({ signal }) => getInventoryVariants(partId ?? "", signal),
    enabled: partId !== null,
  });
}

/** Everything inventory-dependent: counts, coverage, readiness. */
function useInvalidateInventoryDependents() {
  const client = useQueryClient();
  return async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["inventory"] }),
      client.invalidateQueries({ queryKey: ["models"] }),
    ]);
  };
}

export function useSetInventoryQuantity() {
  const invalidate = useInvalidateInventoryDependents();
  return useMutation({
    mutationFn: ({
      partId,
      colorCode,
      quantity,
    }: {
      partId: string;
      colorCode: number;
      quantity: number;
    }) => setInventoryQuantity(partId, colorCode, quantity),
    onSuccess: invalidate,
  });
}

export function useDeleteInventoryItem() {
  const invalidate = useInvalidateInventoryDependents();
  return useMutation({
    mutationFn: ({ partId, colorCode }: { partId: string; colorCode: number }) =>
      deleteInventoryItem(partId, colorCode),
    onSuccess: invalidate,
  });
}

export function useModelsList(input: ModelsQuery) {
  return useQuery({
    queryKey: ["models", "list", serializeModelsQuery(input)],
    queryFn: ({ signal }) => listModels(input, signal),
    placeholderData: keepPreviousData,
  });
}

export function useModelsReadiness() {
  return useQuery({
    queryKey: ["models", "readiness"],
    queryFn: ({ signal }) => getModelsReadinessSummary(signal),
  });
}

export function useModelDetail(modelId: string | null) {
  return useQuery({
    queryKey: ["models", "detail", modelId],
    queryFn: ({ signal }) => getModel(modelId ?? "", signal),
    enabled: modelId !== null,
  });
}

export function useModelCoverage(modelId: string | null, input: CoverageQuery) {
  return useQuery({
    queryKey: ["models", "coverage", modelId, serializeCoverageQuery(input)],
    queryFn: ({ signal }) => getModelCoverage(modelId ?? "", input, signal),
    enabled: modelId !== null,
    placeholderData: keepPreviousData,
  });
}

export function useInstructionPlayback(modelId: string | null) {
  return useQuery({
    queryKey: ["models", "playback", modelId],
    queryFn: ({ signal }) => getInstructionPlayback(modelId ?? "", signal),
    enabled: modelId !== null,
  });
}

export function useBuildManifest(modelId: string | null, occurrenceId: string | null) {
  return useQuery({
    queryKey: ["models", "manifest", modelId, occurrenceId],
    queryFn: ({ signal }) => getBuildManifest(modelId ?? "", occurrenceId ?? "", signal),
    enabled: modelId !== null && occurrenceId !== null,
    placeholderData: keepPreviousData,
  });
}

export function useInstructionGraph(modelId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["models", "graph", modelId],
    queryFn: ({ signal }) => getInstructionGraph(modelId ?? "", signal),
    enabled: enabled && modelId !== null,
  });
}

export function useUploadModel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ file, name }: { file: File; name: string }) => uploadModel(file, name),
    onSuccess: () => client.invalidateQueries({ queryKey: ["models"] }),
  });
}

export function useDeleteModel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (modelId: string) => deleteModel(modelId),
    onSuccess: () => client.invalidateQueries({ queryKey: ["models"] }),
  });
}
