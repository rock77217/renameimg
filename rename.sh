#!/bin/bash

rootDir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
nowDir=`pwd`
cfgDryRun=false
. ./bin/util.sh

sourceDir="$1"
targetDir="$2"
cd "${sourceDir}"
films=(`ls *.[Jj][Pp][Gg]`)
declare -r prefix="IMG_"

renameByCreate() {
    fileName=$(basename $1)
    dirName=$(dirname $1)
    ext=${fileName##*.}
    ext=`echo "${ext}" | tr [:upper:] [:lower:]`
    createTime=$(GetFileInfo -d $1)
    newFileName=$(date -j -f '%m/%d/%Y %H:%M:%S' "${createTime}" +"${prefix}%Y%m%d_%H%M%S.${ext}")
    cd ${dirName}
    execCmd "mv ${sourceDir}/${fileName} ${targetDir}/${newFileName}"
    #change the “date created” 
    execCmd "touchCreateTime '${createTime}' ${targetDir}/${newFileName}"
    #change the “date modified”
    execCmd "touchModifyTime '${createTime}' ${targetDir}/${newFileName}"
}

function touchCreateTime() {
    SetFile -d "${1}" ${2}
}

function touchModifyTime() {
    SetFile -m "${1}" ${2}
}

for film in "${films[@]}"; do
    renameByCreate "${film}"
done

cd ${nowDir}
