#!/bin/bash

state-clickhouse-ensure --skip-views
state-clickhouse-export
state-clickhouse-ensure --views-only
