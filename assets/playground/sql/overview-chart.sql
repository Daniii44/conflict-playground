CREATE VIEW IF NOT EXISTS default.redis_json_overview_chart AS
SELECT
    group_label AS label,
    countIf(resolution_status = 'PROOF_EXACT_MATCH') / count(*) AS proof_exact_match,
    countIf(resolution_status = 'PROOF_EXACT_MATCH_SEMANTIC') / count(*) AS proof_exact_match_semantic,
    countIf(resolution_status = 'PROOF_EXACT_MATCH_NORMALIZED') / count(*) AS proof_exact_match_normalized,
    countIf(resolution_status = 'UNCLASSIFIED_DIVERGENCE') / count(*) AS unclassified_divergences,
    countIf(resolution_status = 'CONTRADICTION_RENAME_PRESENCE_MISMATCH') / count(*)
        AS contradiction_rename_presence_mismatch,
    countIf(resolution_status = 'CONTRADICTION_SCHESCH_GENERATED_TEST_FAILED') / count(*)
        AS contradiction_schesch_generated_test_failed,
    countIf(resolution_status = 'CONTRADICTION_SCHESCH_GENERATED_COMPILATION_FAILED') / count(*)
        AS contradiction_schesch_generated_compilation_failed,
    countIf(resolution_status = 'CONTRADICTION_SCHESCH_ORIGINAL_TEST_FAILED') / count(*)
        AS contradiction_schesch_original_test_failed,
    countIf(resolution_status = 'CONTRADICTION_SCHESCH_ORIGINAL_COMPILATION_FAILED') / count(*)
        AS contradiction_schesch_original_compilation_failed,
    countIf(resolution_status = 'CONTRADICTION_NONCANONICAL_FALLBACK') / count(*) AS contradiction_noncanonical_fallback,
    countIf(resolution_status = 'CONTRADICTION_GHOST_RESOLUTION') / count(*) AS contradiction_ghost_resolution,
    countIf(resolution_status = 'CONTRADICTION_SEMICANONICAL_DILUTION') / count(*) AS contradiction_semicanonical_dilution,
    countIf(resolution_status = 'CONTRADICTION_SEMICANONICAL_CONTRADICTION') / count(*) AS contradiction_semicanonical_contradiction,
    countIf(resolution_status = 'CONTRADICTION_CANONICAL_RESOLUTION_DIFFERS') / count(*) AS contradiction_canonical_resolution_differs,
    countIf(resolution_status = 'CONTRADICTION_AGENT_TIMEOUT') / count(*) AS contradiction_agent_timeout,
    countIf(resolution_status = 'CONTRADICTION_AGENT_ERROR') / count(*) AS contradiction_agent_error
FROM default.redis_json_overview_base
GROUP BY group_label
ORDER BY group_label
