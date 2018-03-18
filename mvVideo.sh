#!/bin/bash

rootDir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cfgDryRun=false
. ./bin/util.sh

fromDir=/Volumes/Ryan/private/M4ROOT/CLIP
toDir=/Volumes/Untitled
declare -a videos
declare -r VIDEO_EXT="[Mm][Pp]4"
declare -r os=`uname`
declare -r prefix="IMG_"
declare -r fileDateFormat="${prefix}%Y%m%d_%H%M%S"
declare -r touchDateFormat="%Y%m%d%H%M.%S"

function convertVideo() {
    # $1 is fromDir
    # $2 is toDir
    videos=(`ls ${fromDir}/*.${VIDEO_EXT}`)
    
    for film in "${videos[@]}"; do
        name=`basename ${film}`
        newName=`getNewName ${film}`
        outPath=${toDir}/${newName}
        echoInfo "File name: ${name}"
        
        filmPath=${fromDir}/${film}

        fileCreateTime=`loadCreateTime ${film}`

        echoInfo "File converting..."
        execCmd "ffmpeg -i ${film} -codec:v libx264 -crf 21 -bf 2 -flags +cgop -pix_fmt yuv420p -codec:a aac -strict -2 -b:a 384k -r:a 48000 -movflags faststart ${outPath}"
        echoInfo "Output file at ${outPath}"
        
        #change the “date created” 
        execCmd "touchCreateTime '${fileCreateTime}' ${outPath}"
        #change the “date modified”
        execCmd "touchModifyTime '${fileCreateTime}' ${outPath}"
        #touch -mt ${filmMTime} ${outPath}
    done
}

function getNewName() {
    date -r $(stat -f %B $1) "+${fileDateFormat}.${1##*.}"
}

function loadCreateTime() {
    GetFileInfo -d ${1}
}

function loadModifyTime() {
    GetFileInfo -m ${1}
}

function touchCreateTime() {
    SetFile -d "${1}" ${2}
}

function touchModifyTime() {
    SetFile -m "${1}" ${2}
}

function getFormatedDate() {
    date -r ${1} +${touchDateFormat}
}

function dateFileName2date() {
    fileName=`basename $1`
    fileName=${fileName%.*}
    date -j -f "${fileDateFormat}" "${fileName}" "+${touchDateFormat}"
}

function retouchFromName() {
    createDate=`dateFileName2date $1`
    touch -t ${createDate} ${1}
}

convertVideo
#touchFile