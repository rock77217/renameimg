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

function rmFile() {
    execCmd "rm '${1}'"
}

function mvFile() {
    chkDir "$(dirname "${2}")"
    execCmd "mv '${1}' '${2}'"
}

function chkDir() {
    [[ ! -d ${1} ]] && execCmd "mkdir -p ${1}"
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

function ErrExit() {
    echo "[ERROR]   $1"
    exit 1
}