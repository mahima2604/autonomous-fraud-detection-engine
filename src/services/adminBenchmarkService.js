// adminBenchmarkService.js
// Client API service for fetching reproducible IEEE-CIS benchmark evaluations.

import { apiRequest } from './api';

export function getBenchmarkEvaluation(forceRefresh = false) {
  const query = forceRefresh ? '?force_refresh=true' : '';
  return apiRequest(`/admin/benchmark/evaluation${query}`);
}
