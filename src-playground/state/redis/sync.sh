#!/bin/bash

state-redis-prune --all
state-redis-import $@
