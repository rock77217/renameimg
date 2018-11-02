#!/bin/bash

declare -r rootDir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

function execCmd() {
    
    if ${cfgDryRun}; then
        echoFake "${1}"
    else
        echoExec "${1}"
        eval $1
        rt=$?
        [[ ${rt} != 0 ]] && exit
    fi
}

function echoExec() {
    echo "[EXEC]    $1"
}

function echoFake() {
    echo "[Fake]    $1"
}

function echoInfo() {
    echo "$1"
}