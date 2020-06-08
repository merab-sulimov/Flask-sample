#!/usr/bin/env bash
for i in $*;
do
    params=" $params $i"
done

SIMPLEFLASK_CONFIG="config.ProductionConfig" python manage.py $params