#!/bin/bash

docker compose up --build -d conflict-playground
docker exec -it conflict-playground bash src/entrypoint.sh