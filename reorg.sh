#!/bin/bash

. ./bin/util.sh
declare -r rootName=`basename ${0} | cut -d '.' -f 1`
declare -r tmpDir=/tmp/${rootName}
declare -r logFile=${tmpDir}/$(date +"%Y%m%d_%H%M%S").log
declare -r nowDir=`pwd`
declare -r cfgDryRun=true
declare -r sourceDir="$1"
declare -r threads=1
declare -r prefix="IMG_"
declare -r fileDateFmt="%Y%m%d_%H%M%S"
declare -r infoDateFmt="%m/%d/%Y %H:%M:%S"
declare -r fileFormat="${prefix}${fileDateFmt}"
#declare TZ="Asia/Tokyo"
declare -a scanFiles
cd "${sourceDir}"
absSourceDir=""

function loadFiles() {
    absSourceDir="$(cd "${1}" && pwd )"
    echo "Scan ${absSourceDir}"
    oldIFS=$IFS
    IFS=$'\n'
    scanFiles=(`find ${absSourceDir} -type f`)
    IFS=$oldIFS

    if [[ -d ${tmpDir} ]]; then
        rm -rf ${tmpDir}
    fi
    mkdir -p ${tmpDir}

    for file in "${scanFiles[@]}"; do

        analysisFile "${file}"
        
        #while [ "$(jobs -p | wc -l)" == "${threads}" ];
        #do
        #    sleep 5
        #done
    done
    wait
}

function analysisFile() {
    echo "---------------------------------------------------------------------------------"
    echo "${1}"
    fileName=`basename "$1"`
    pureName=${fileName%.*}
    fileExt=${fileName##*.}
    filePath=`dirname "$1"`

    cDate=`loadCreateTime "$1"`
    mDate=`loadModifyTime "$1"`
    fileDate=`loadFileDate ${pureName}`

    minDate=`getMinTimestamp ${cDate} ${mDate}`
    minDate=`getMinTimestamp ${minDate} ${fileDate}`
    #echo "Compare timestamp: ${cDate}, ${mDate}, ${fileDate}"
    #echo "Min timestamp: ${minDate}"
    target="${filePath}/${prefix}$(timestamp2FileDate "${minDate}").${fileExt}"
    
    fileInfo=$(file -b "${1}")
    if [[ "${fileInfo}" =~ ^'JPEG ' ]]; then
        if [[ "${1}" != "${target}" ]]; then
            target=$(checkNotExistsPath "$1" "${target}")
            mvFile "${1}" "${target}"
        fi
        [[ "${minDate}" != "${cDate}" ]] && touchCreateTime ${minDate} "${target}"
        [[ "${minDate}" != "${mDate}" ]] && touchModifyTime ${minDate} "${target}"
    elif [[ "${fileInfo}" =~ ^'ISO Media' ]]; then
        if $(isPressed "${1}"); then
            tmpPath=${filePath}/${pureName}_tmp.${fileExt}
            tmpPath=$(checkNotExistsPath "$1" "${tmpPath}")
            mvFile "${1}" "${tmpPath}"
            target=$(checkNotExistsPath "$1" "${target}")
            pressMp4 "${tmpPath}" "${target}"
            [[ "${minDate}" != "${cDate}" ]] && touchCreateTime ${minDate} "${target}"
            [[ "${minDate}" != "${mDate}" ]] && touchModifyTime ${minDate} "${target}"
            rmFile "${tmpPath}"
        fi
    else
        echo "PASS"
    fi

    echo ""
}

function mvFile() {
    execCmd "mv '${1}' '${2}'"
}

function checkNotExistsPath() {
    renameCount=1
    sourcePath="${1}"
    sourceName=$(basename "${sourcePath}")
    targetDir=$(dirname "${2}")
    targetName=$(basename "${2}")
    result="${2}"
    while [ -f "${result}" ]; do
        result="${targetDir}/${targetName%.*}_${renameCount}.${targetName##*.}"
        [[ "${sourcePath}" == "${result}" ]] && break
        ((renameCount++))
    done
    echo "${result}"
}

function rmFile() {
    execCmd "rm '${1}'"
}

function isPressed() {
    profile=$(ffprobe -v quiet -show_streams "${1}" | grep "profile=Baseline")
    [[ "${profile}" != "" ]] && return 0 || return 1
}

function pressMp4() {
    execCmd "ffmpeg -i '${1}' -codec:v libx264 -crf 21 -bf 2 -flags +cgop -pix_fmt yuv420p -codec:a aac -strict -2 -b:a 384k -r:a 48000 -movflags faststart '${2}'"
}

function loadCreateTime() {
    tmp=`GetFileInfo -d "${1}"`
    infoDate2Timestamp "${tmp}"
}

function loadModifyTime() {
    tmp=`GetFileInfo -m "${1}"`
    infoDate2Timestamp "${tmp}"
}

function loadFileDate() {
    tmp=`echo "${1}" | grep -Eo "[0-9]{8}_[0-9]{6}"`
    fileDate2Timestamp "${tmp}"
}

function infoDate2Timestamp() {
    date -j -f "${infoDateFmt}" "${1}" +%s 2> /dev/null
}

function fileDate2Timestamp() {
    date -j -f "${fileDateFmt}" "${1}" +%s 2> /dev/null
}

function timestamp2InfoDate() {
    if [[ "${TZ}" != "" ]]; then
        TZ=${TZ} date -r ${1} +"${infoDateFmt}"
    else
        date -r ${1} +"${infoDateFmt}"
    fi
}

function timestamp2FileDate() {
    if [[ "${TZ}" != "" ]]; then
        TZ=${TZ} date -r ${1} +"${fileDateFmt}"
    else
        date -r ${1} +"${fileDateFmt}"
    fi
}

function getMinTimestamp() {
    (( $# == 1 )) && echo "${1}" && return
    (( $1 >= $2 )) && echo "${2}" || echo "${1}"
}

function touchCreateTime() {
    time=$(timestamp2InfoDate ${1})
    execCmd "SetFile -d '${time}' '${2}'"
}

function touchModifyTime() {
    time=$(timestamp2InfoDate ${1})
    execCmd "SetFile -m '${time}' '${2}'"
}

touch ${logFile}
[[ "$2" != "" ]] && TZ="$2"
loadFiles "${1}" | tee -i ${logFile}
cd ${nowDir}
