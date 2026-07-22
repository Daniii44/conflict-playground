from __future__ import annotations

import requests


CLICKHOUSE_URL = "http://clickhouse:8123"
CLICKHOUSE_DB = "default"
CLICKHOUSE_USER = "default"
CLICKHOUSE_PASSWORD = "dev-dynha9-fenvYc-daqmeh"
CLICKHOUSE_TABLE = "redis_json"
CLICKHOUSE_OVERVIEW_BASE_VIEW = "redis_json_overview_base"
CLICKHOUSE_OVERVIEW_CHART_VIEW = "redis_json_overview_chart"
CLICKHOUSE_OVERVIEW_TABLE_VIEW = "redis_json_overview_table"


def run_query(query: str) -> requests.Response:
    response = requests.post(
        f"{CLICKHOUSE_URL}/?query={query}",
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
    )
    response.raise_for_status()
    return response


def create_table_query() -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} (
        key String,
        conflict_identifier String,
        repo String,
        merge_hash String,
        conflict_timestamp String,
        content JSON,
        INDEX idx_conflict_identifier conflict_identifier TYPE bloom_filter GRANULARITY 1,
        INDEX idx_repo repo TYPE bloom_filter GRANULARITY 1,
        INDEX idx_merge_hash merge_hash TYPE bloom_filter GRANULARITY 1,
        INDEX idx_conflict_timestamp conflict_timestamp TYPE bloom_filter GRANULARITY 1
    )
    ENGINE = ReplacingMergeTree
    ORDER BY (repo, merge_hash, conflict_timestamp, key)
    """


def overview_base_view_query() -> str:
    return f"""
    CREATE VIEW IF NOT EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_OVERVIEW_BASE_VIEW} AS
    WITH
    tilt_allocation AS (
        SELECT
            repo,
            merge_hash,
            any(nullIf(content.subdataset::text, '')) AS subdataset
        FROM {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE}
        WHERE startsWith(key, 'dataset:tilt:')
        GROUP BY repo, merge_hash
    ),
    resolution_dimensions AS (
        SELECT
            key AS resolution_key,
            conflict_identifier,
            repo,
            merge_hash,
            conflict_timestamp,
            coalesce(nullIf(any(ta.subdataset), ''), 'UNKNOWN_SUBDATASET') AS subdataset,
            coalesce(
                nullIf(singleValueOrNull(nullIf(message.info.modelID::text, '')), ''),
                'UNKNOWN_LLM'
            ) AS llm,
            multiIf(
                coalesce(nullIf(any(ta.subdataset), ''), 'UNKNOWN_SUBDATASET') != 'UNKNOWN_SUBDATASET'
                    AND coalesce(
                        nullIf(singleValueOrNull(nullIf(message.info.modelID::text, '')), ''),
                        'UNKNOWN_LLM'
                    ) != 'UNKNOWN_LLM',
                concat(
                    coalesce(nullIf(any(ta.subdataset), ''), 'UNKNOWN_SUBDATASET'),
                    ' | ',
                    coalesce(
                        nullIf(singleValueOrNull(nullIf(message.info.modelID::text, '')), ''),
                        'UNKNOWN_LLM'
                    )
                ),
                coalesce(nullIf(any(ta.subdataset), ''), 'UNKNOWN_SUBDATASET') != 'UNKNOWN_SUBDATASET',
                coalesce(nullIf(any(ta.subdataset), ''), 'UNKNOWN_SUBDATASET'),
                coalesce(
                    nullIf(singleValueOrNull(nullIf(message.info.modelID::text, '')), ''),
                    'UNKNOWN_LLM'
                )
            ) AS group_label
        FROM {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} AS r
        LEFT JOIN tilt_allocation AS ta
            ON ta.repo = r.repo
           AND ta.merge_hash = r.merge_hash
        LEFT ARRAY JOIN r.content.hook_result.opencode_session_export.data.messages::Array(JSON) AS message
        WHERE startsWith(key, 'resolution:conflict:')
        GROUP BY
            key,
            conflict_identifier,
            repo,
            merge_hash,
            conflict_timestamp
    ),
    base_merges AS (
        SELECT
            rd.repo,
            rd.merge_hash,
            rd.subdataset,
            rd.llm,
            rd.group_label,
            count() AS total_resolutions,
            max(rd.conflict_timestamp) AS latest_conflict_timestamp,
            max(CASE WHEN r.content.proposed_resolution.error LIKE 'Error: opencode timed out%' THEN 1 ELSE 0 END)
                AS contradiction_agent_timeout,
            CASE
                WHEN max(CASE WHEN r.content.proposed_resolution.error LIKE 'Error: opencode timed out%' THEN 1 ELSE 0 END) = 1 THEN 0
                ELSE max(CASE WHEN r.content.proposed_resolution.error IS NOT NULL THEN 1 ELSE 0 END)
            END AS contradiction_agent_error
        FROM {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} AS r
        INNER JOIN resolution_dimensions AS rd
            ON rd.resolution_key = r.key
        GROUP BY
            rd.repo,
            rd.merge_hash,
            rd.subdataset,
            rd.llm,
            rd.group_label
    ),
    core_metrics AS (
        SELECT
            rd.repo,
            rd.merge_hash,
            rd.subdataset,
            rd.llm,
            rd.group_label,
            countDistinct(e.key) AS total_evaluations,
            min(CASE WHEN e.key != '' AND e.content.incomplete_merge = 1 THEN 1 ELSE 0 END)
                AS contradiction_is_incomplete_merge,
            min(CASE WHEN e.key != '' AND e.content.perfect_match != 0 THEN 1 ELSE 0 END)
                AS proof_is_exact_match
        FROM {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} AS e
        INNER JOIN resolution_dimensions AS rd
            ON rd.conflict_identifier = e.conflict_identifier
        WHERE startsWith(e.key, 'evaluation:merge:core:')
        GROUP BY
            rd.repo,
            rd.merge_hash,
            rd.subdataset,
            rd.llm,
            rd.group_label
    ),
    diff_metrics AS (
        SELECT
            rd.repo,
            rd.merge_hash,
            rd.subdataset,
            rd.llm,
            rd.group_label,
            min(
                CASE
                    WHEN e.content.proposed_to_actual_resolution_diffs.ignore_all_space.ignore_blank_lines.exact_match::boolean
                    THEN 1
                    ELSE 0
                END
            ) AS proof_is_exact_match_normalized
        FROM {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} AS e
        INNER JOIN resolution_dimensions AS rd
            ON rd.conflict_identifier = e.conflict_identifier
        WHERE startsWith(e.key, 'evaluation:merge:diff:')
        GROUP BY
            rd.repo,
            rd.merge_hash,
            rd.subdataset,
            rd.llm,
            rd.group_label
    ),
    schesch_metrics AS (
        SELECT
            rd.repo,
            rd.merge_hash,
            rd.subdataset,
            rd.llm,
            rd.group_label,
            max(
                CASE
                    WHEN e.content.proposed.timed_out = false
                     AND e.content.proposed.compilation_failed::boolean
                    THEN 1
                    ELSE 0
                END
            ) AS contradiction_proposed_compilation_failed,
            max(
                CASE
                    WHEN e.content.proposed.timed_out = false
                     AND e.content.proposed.test_execution_failed::boolean
                    THEN 1
                    ELSE 0
                END
            ) AS contradiction_proposed_test_failed
        FROM {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} AS e
        INNER JOIN resolution_dimensions AS rd
            ON rd.conflict_identifier = e.conflict_identifier
        WHERE startsWith(e.key, 'evaluation:merge:schesch-original:')
           OR startsWith(e.key, 'evaluation:merge:schesch-generated:')
        GROUP BY
            rd.repo,
            rd.merge_hash,
            rd.subdataset,
            rd.llm,
            rd.group_label
    ),
    classification_metrics AS (
        SELECT
            class_source.repo,
            class_source.merge_hash,
            class_source.subdataset,
            class_source.llm,
            class_source.group_label,
            max(
                class_source.agent_classification NOT LIKE '%CONTEXT_CHANGED%'
                AND class_source.human_classification NOT LIKE '%CONTEXT_CHANGED%'
                AND class_source.canonical_diff_exists
            ) AS contradiction_canonical_resolution_differs,
            max(
                class_source.agent_classification NOT LIKE '%CONTEXT_CHANGED%'
                AND class_source.human_classification NOT LIKE '%CONTEXT_CHANGED%'
                AND class_source.contradiction_exists
            ) AS contradiction_semicanonical_contradiction,
            max(
                class_source.agent_classification NOT LIKE '%CONTEXT_CHANGED%'
                AND class_source.human_classification NOT LIKE '%CONTEXT_CHANGED%'
                AND class_source.dilution_exists
            ) AS contradiction_semicanonical_dilution,
            max(
                class_source.agent_classification NOT LIKE '%CONTEXT_CHANGED%'
                AND class_source.human_classification NOT LIKE '%CONTEXT_CHANGED%'
                AND class_source.ghost_exists
            ) AS contradiction_ghost_resolution,
            max(
                class_source.agent_classification NOT LIKE '%CONTEXT_CHANGED%'
                AND class_source.human_classification NOT LIKE '%CONTEXT_CHANGED%'
                AND class_source.fallback_exists
            ) AS contradiction_noncanonical_fallback
        FROM (
            SELECT
                rd.repo,
                rd.merge_hash,
                rd.subdataset,
                rd.llm,
                rd.group_label,
                arrayStringConcat(logical_conflict.agent_classifications, '\n') AS agent_classification,
                arrayStringConcat(logical_conflict.human_classifications, '\n') AS human_classification,
                CAST(
                    arrayZip(logical_conflict.agent_classifications, logical_conflict.human_classifications),
                    'Array(Tuple(String, String))'
                ) AS zipped,
                arrayExists(
                    t -> (
                        t.1 IN ('CHUNK_CANONICAL_OURS', 'CHUNK_CANONICAL_THEIRS', 'CHUNK_CANONICAL_BASE')
                        AND t.2 IN ('CHUNK_CANONICAL_OURS', 'CHUNK_CANONICAL_THEIRS', 'CHUNK_CANONICAL_BASE')
                        AND t.1 != t.2
                    ),
                    zipped
                ) AS canonical_diff_exists,
                arrayExists(
                    t -> (
                        (t.1 = 'CHUNK_CANONICAL_OURS' AND t.2 = 'CHUNK_SEMICANONICAL_BASETHEIRS')
                        OR (t.2 = 'CHUNK_CANONICAL_OURS' AND t.1 = 'CHUNK_SEMICANONICAL_BASETHEIRS')
                        OR (t.1 = 'CHUNK_CANONICAL_THEIRS' AND t.2 = 'CHUNK_SEMICANONICAL_OURSBASE')
                        OR (t.2 = 'CHUNK_CANONICAL_THEIRS' AND t.1 = 'CHUNK_SEMICANONICAL_OURSBASE')
                        OR (t.1 = 'CHUNK_CANONICAL_BASE' AND t.2 = 'CHUNK_SEMICANONICAL_OURSTHEIRS')
                        OR (t.2 = 'CHUNK_CANONICAL_BASE' AND t.1 = 'CHUNK_SEMICANONICAL_OURSTHEIRS')
                    ),
                    zipped
                ) AS contradiction_exists,
                arrayExists(
                    t -> (
                        (t.1 LIKE 'CHUNK_SEMICANONICAL_%'
                            AND t.1 != 'CHUNK_SEMICANONICAL_OURSBASETHEIRS'
                            AND t.2 = 'CHUNK_SEMICANONICAL_OURSBASETHEIRS')
                        OR (t.2 LIKE 'CHUNK_SEMICANONICAL_%'
                            AND t.2 != 'CHUNK_SEMICANONICAL_OURSBASETHEIRS'
                            AND t.1 = 'CHUNK_SEMICANONICAL_OURSBASETHEIRS')
                    ),
                    zipped
                ) AS dilution_exists,
                arrayExists(
                    t -> (
                        t.1 LIKE 'CHUNK_%CANONICAL%'
                        AND t.1 != 'CHUNK_SEMICANONICAL_EMPTY'
                        AND t.2 = 'CHUNK_SEMICANONICAL_EMPTY'
                    ),
                    zipped
                ) AS ghost_exists,
                arrayExists(
                    t -> (
                        t.1 LIKE 'CHUNK_%CANONICAL%'
                        AND t.1 != 'CHUNK_NONCANONICAL'
                        AND t.2 = 'CHUNK_NONCANONICAL'
                    ),
                    zipped
                ) AS fallback_exists
            FROM {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} AS e
            INNER JOIN resolution_dimensions AS rd
                ON rd.conflict_identifier = e.conflict_identifier
            ARRAY JOIN e.content.logical_conflicts::Array(JSON) AS logical_conflict
            WHERE startsWith(e.key, 'evaluation:merge:classification:')
        ) AS class_source
        GROUP BY
            class_source.repo,
            class_source.merge_hash,
            class_source.subdataset,
            class_source.llm,
            class_source.group_label
    )
    SELECT
        b.repo,
        b.merge_hash,
        b.subdataset,
        b.llm,
        b.group_label,
        b.latest_conflict_timestamp,
        b.total_resolutions,
        coalesce(m.total_evaluations, 0) AS total_evaluations,
        coalesce(m.proof_is_exact_match, 0) AS proof_is_exact_match,
        coalesce(d.proof_is_exact_match_normalized, 0) AS proof_is_exact_match_normalized,
        coalesce(b.contradiction_agent_error, 0) AS contradiction_agent_error,
        coalesce(b.contradiction_agent_timeout, 0) AS contradiction_agent_timeout,
        coalesce(m.contradiction_is_incomplete_merge, 0) AS contradiction_is_incomplete_merge,
        coalesce(s.contradiction_proposed_compilation_failed, 0) AS contradiction_proposed_compilation_failed,
        coalesce(s.contradiction_proposed_test_failed, 0) AS contradiction_proposed_test_failed,
        coalesce(c.contradiction_canonical_resolution_differs, 0) AS contradiction_canonical_resolution_differs,
        coalesce(c.contradiction_semicanonical_contradiction, 0) AS contradiction_semicanonical_contradiction,
        coalesce(c.contradiction_semicanonical_dilution, 0) AS contradiction_semicanonical_dilution,
        coalesce(c.contradiction_ghost_resolution, 0) AS contradiction_ghost_resolution,
        coalesce(c.contradiction_noncanonical_fallback, 0) AS contradiction_noncanonical_fallback,
        CASE
            WHEN coalesce(b.contradiction_agent_error, 0) = 1 THEN 'CONTRADICTION_AGENT_ERROR'
            WHEN coalesce(b.contradiction_agent_timeout, 0) = 1 THEN 'CONTRADICTION_AGENT_TIMEOUT'
            WHEN coalesce(m.contradiction_is_incomplete_merge, 0) = 1 THEN 'CONTRADICTION_IS_INCOMPLETE_MERGE'
            WHEN coalesce(s.contradiction_proposed_compilation_failed, 0) = 1 THEN 'CONTRADICTION_PROPOSED_COMPILATION_FAILED'
            WHEN coalesce(s.contradiction_proposed_test_failed, 0) = 1 THEN 'CONTRADICTION_PROPOSED_TEST_FAILED'
            WHEN coalesce(c.contradiction_canonical_resolution_differs, 0) = 1 THEN 'CONTRADICTION_CANONICAL_RESOLUTION_DIFFERS'
            WHEN coalesce(c.contradiction_semicanonical_contradiction, 0) = 1 THEN 'CONTRADICTION_SEMICANONICAL_CONTRADICTION'
            WHEN coalesce(c.contradiction_semicanonical_dilution, 0) = 1 THEN 'CONTRADICTION_SEMICANONICAL_DILUTION'
            WHEN coalesce(c.contradiction_ghost_resolution, 0) = 1 THEN 'CONTRADICTION_GHOST_RESOLUTION'
            WHEN coalesce(c.contradiction_noncanonical_fallback, 0) = 1 THEN 'CONTRADICTION_NONCANONICAL_FALLBACK'
            WHEN coalesce(m.proof_is_exact_match, 0) = 1 THEN 'PROOF_IS_EXACT_MATCH'
            WHEN coalesce(d.proof_is_exact_match_normalized, 0) = 1 THEN 'PROOF_IS_EXACT_MATCH_NORMALIZED'
            ELSE 'UNCLASSIFIED_DIVERGENCE'
        END AS resolution_status
    FROM base_merges AS b
    LEFT JOIN core_metrics AS m
        ON m.repo = b.repo
       AND m.merge_hash = b.merge_hash
       AND m.subdataset = b.subdataset
       AND m.llm = b.llm
       AND m.group_label = b.group_label
    LEFT JOIN diff_metrics AS d
        ON d.repo = b.repo
       AND d.merge_hash = b.merge_hash
       AND d.subdataset = b.subdataset
       AND d.llm = b.llm
       AND d.group_label = b.group_label
    LEFT JOIN schesch_metrics AS s
        ON s.repo = b.repo
       AND s.merge_hash = b.merge_hash
       AND s.subdataset = b.subdataset
       AND s.llm = b.llm
       AND s.group_label = b.group_label
    LEFT JOIN classification_metrics AS c
        ON c.repo = b.repo
       AND c.merge_hash = b.merge_hash
       AND c.subdataset = b.subdataset
       AND c.llm = b.llm
       AND c.group_label = b.group_label
    """


def overview_chart_view_query() -> str:
    return f"""
    CREATE VIEW IF NOT EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_OVERVIEW_CHART_VIEW} AS
    SELECT
        group_label AS label,
        countIf(resolution_status = 'PROOF_IS_EXACT_MATCH') / count(*) AS proof_is_exact_match,
        countIf(resolution_status = 'PROOF_IS_EXACT_MATCH_NORMALIZED') / count(*) AS proof_is_exact_match_normalized,
        countIf(resolution_status = 'UNCLASSIFIED_DIVERGENCE') / count(*) AS unclassified_divergences,
        countIf(resolution_status = 'CONTRADICTION_NONCANONICAL_FALLBACK') / count(*) AS contradiction_noncanonical_fallback,
        countIf(resolution_status = 'CONTRADICTION_GHOST_RESOLUTION') / count(*) AS contradiction_ghost_resolution,
        countIf(resolution_status = 'CONTRADICTION_SEMICANONICAL_DILUTION') / count(*) AS contradiction_semicanonical_dilution,
        countIf(resolution_status = 'CONTRADICTION_SEMICANONICAL_CONTRADICTION') / count(*) AS contradiction_semicanonical_contradiction,
        countIf(resolution_status = 'CONTRADICTION_CANONICAL_RESOLUTION_DIFFERS') / count(*) AS contradiction_canonical_resolution_differs,
        countIf(resolution_status = 'CONTRADICTION_PROPOSED_TEST_FAILED') / count(*) AS contradiction_proposed_test_failed,
        countIf(resolution_status = 'CONTRADICTION_PROPOSED_COMPILATION_FAILED') / count(*) AS contradiction_proposed_compilation_failed,
        countIf(resolution_status = 'CONTRADICTION_IS_INCOMPLETE_MERGE') / count(*) AS contradiction_is_incomplete_merge,
        countIf(resolution_status = 'CONTRADICTION_AGENT_TIMEOUT') / count(*) AS contradiction_agent_timeout,
        countIf(resolution_status = 'CONTRADICTION_AGENT_ERROR') / count(*) AS contradiction_agent_error
    FROM {CLICKHOUSE_DB}.{CLICKHOUSE_OVERVIEW_BASE_VIEW}
    GROUP BY group_label
    ORDER BY group_label
    """


def overview_table_view_query() -> str:
    return f"""
    CREATE VIEW IF NOT EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_OVERVIEW_TABLE_VIEW} AS
    SELECT
        repo,
        merge_hash,
        latest_conflict_timestamp AS conflict_timestamp,
        subdataset,
        llm,
        group_label AS label,
        total_resolutions,
        total_evaluations,
        'Show Details' AS details,
        proof_is_exact_match,
        proof_is_exact_match_normalized,
        contradiction_agent_error,
        contradiction_agent_timeout,
        contradiction_is_incomplete_merge,
        contradiction_proposed_compilation_failed,
        contradiction_proposed_test_failed,
        contradiction_canonical_resolution_differs,
        contradiction_semicanonical_contradiction,
        contradiction_semicanonical_dilution,
        contradiction_ghost_resolution,
        contradiction_noncanonical_fallback,
        resolution_status
    FROM {CLICKHOUSE_DB}.{CLICKHOUSE_OVERVIEW_BASE_VIEW}
    ORDER BY
        proof_is_exact_match DESC,
        proof_is_exact_match_normalized DESC,
        contradiction_agent_error DESC,
        contradiction_agent_timeout DESC,
        contradiction_is_incomplete_merge DESC,
        contradiction_proposed_compilation_failed DESC,
        contradiction_proposed_test_failed DESC,
        contradiction_canonical_resolution_differs DESC,
        contradiction_semicanonical_contradiction DESC,
        contradiction_semicanonical_dilution DESC,
        contradiction_ghost_resolution DESC,
        contradiction_noncanonical_fallback DESC,
        repo,
        merge_hash,
        group_label
    """


def drop_table_query() -> str:
    return f"DROP TABLE IF EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE}"


def drop_view_query(view_name: str) -> str:
    return f"DROP VIEW IF EXISTS {CLICKHOUSE_DB}.{view_name}"


def create_table() -> None:
    run_query(create_table_query())


def drop_table() -> None:
    run_query(drop_table_query())


def create_views() -> None:
    for query in (
        overview_base_view_query(),
        overview_chart_view_query(),
        overview_table_view_query(),
    ):
        run_query(query)


def drop_views() -> None:
    for view_name in (
        CLICKHOUSE_OVERVIEW_TABLE_VIEW,
        CLICKHOUSE_OVERVIEW_CHART_VIEW,
        CLICKHOUSE_OVERVIEW_BASE_VIEW,
    ):
        run_query(drop_view_query(view_name))
