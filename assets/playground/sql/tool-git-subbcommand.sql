CREATE MATERIALIZED VIEW default.redis_json_git_subcommands_by_llm
(
    `llm` String,
    `subcommand` String,
    `count` UInt64
)
ENGINE = SummingMergeTree
ORDER BY (llm, subcommand)
SETTINGS index_granularity = 8192
POPULATE
AS SELECT
    llm,
    -- Filter out leading options (e.g. -C, --git-dir) and extract the first actual subcommand
    arrayElement(
        arrayFilter(
            x -> length(x) > 0 AND NOT startsWith(x, '-'),
            arraySlice(splitByChar(' ', trimBoth(part.state.input.command::text)), 2)
        ),
        1
    ) AS subcommand,
    count(*) AS count
FROM (
    SELECT
        content,
        coalesce(
            nullIf(
                arrayElement(
                    arrayFilter(x -> length(x) > 0, 
                        arrayMap(m -> m.info.modelID::text, 
                            content.hook_result.opencode_session_export.data.messages::Array(JSON)
                        )
                    ), 
                    1
                ), 
                ''
            ),
            'UNKNOWN_LLM'
        ) AS llm
    FROM "default"."redis_json"
)
ARRAY JOIN content.hook_result.opencode_session_export.data.messages::Array(JSON) AS message
ARRAY JOIN message.parts::Array(JSON) AS part
WHERE message.info.role = 'assistant' 
  AND part.type = 'tool'
  AND part.tool = 'bash'
  AND part.state.status = 'completed'
  AND arrayElement(splitByChar(' ', trimBoth(part.state.input.command::text)), 1) = 'git'
  AND length(subcommand) > 0
GROUP BY
    llm,
    subcommand;
