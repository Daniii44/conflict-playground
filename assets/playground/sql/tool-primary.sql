CREATE MATERIALIZED VIEW default.redis_json_initial_bash_commands_by_llm
(
    `llm` String,
    `command` String,
    `count` UInt64
)
ENGINE = SummingMergeTree
ORDER BY (llm, command)
SETTINGS index_granularity = 8192
POPULATE AS SELECT
    llm,
    arrayElement(splitByChar(' ', part.state.input.command::text), 1) AS command,
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
GROUP BY
    llm,
    command;