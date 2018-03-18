#!/bin/bash

rootDir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cfgDryRun=false
. ./bin/util.sh

renameDir=/Volumes/Untitled/DCIM/103ND750
films=(`ls ${renameDir}/*.[Jj][Pp][Gg]`)
declare -r prefix="IMG_"

renameByCreate() {
    fileName=$(basename $1)
    dirName=$(dirname $1)
    ext=${fileName##*.}
    ext=`echo "${ext}" | tr [:upper:] [:lower:]`
    createTime=$(GetFileInfo -d $1)
    newFileName=$(date -j -f '%d/%m/%Y %H:%M:%S' "${createTime}" +"${prefix}%Y%m%d_%H%M%S.${ext}")
    cd ${dirName}
    execCmd "mv ${fileName} ${newFileName}"
}

for film in "${films[@]}"; do
    renameByCreate ${film}
done