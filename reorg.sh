#!/bin/bash

. ./bin/util.sh
declare -r bashName=`basename ${0} | cut -d '.' -f 1`
declare -r tmpDir=/tmp/${bashName}
declare -r logFile=${tmpDir}/$(date +"%Y%m%d_%H%M%S").log
declare -r nowDir=`pwd`
declare cfgDryRun=false
declare -r threads=1
declare -r prefix="IMG_"
declare -r fileDateFmt="%Y%m%d_%H%M%S"
declare -r infoDateFmt="%m/%d/%Y %H:%M:%S"
declare -r linuxTouchFmt="%Y%m%d%H%M.%S"
declare -r nowOS=$(uname -s)
declare -r linuxOS="Linux"
declare -r macOS="Darwin"
declare targetDir=""
declare -a scanFiles

function init() {
    chkDir "${tmpDir}"

    if [[ "${nowOS}" != "${macOS}" ]] && [[ "${nowOS}" != "${linuxOS}" ]]; then
        ErrExit "Not support ${nowOS}"
    fi
    
    cd "${sourceDir}"
}

function usage() {
    ErrExit "Usage: ./${bashName} -s source/path [-t target/path] [-z \"Time/Zone\"]"
}

function loadFiles() {
    echo "Scan ${sourceDir}"
    oldIFS=$IFS
    IFS=$'\n'
    scanFiles=(`find ${sourceDir} -type f | sort`)
    IFS=$oldIFS

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
    relativePath=$(loadRelativePath "${sourceDir}" "${filePath}")

    cDate=`loadCreateTime "$1"`
    mDate=`loadModifyTime "$1"`
    fileDate=`loadFileDate ${pureName}`

    minDate=`getMinTimestamp ${cDate} ${mDate}`
    minDate=`getMinTimestamp ${minDate} ${fileDate}`
    #echo "Compare timestamp: $(timestamp2Date ${cDate} "${infoDateFmt}"), $(timestamp2Date ${mDate} "${infoDateFmt}"), $(timestamp2Date ${fileDate} "${infoDateFmt}")"
    #echo "Min timestamp: ${minDate}"
    if [[ "${targetDir}" != "" ]]; then
        if [[ "${relativePath}" != "" ]]; then
            target="${targetDir}${relativePath}/${prefix}$(timestamp2FileDate "${minDate}").${fileExt}"
        else
            target="${targetDir}/${prefix}$(timestamp2FileDate "${minDate}").${fileExt}"
        fi
    else
        target="${filePath}/${prefix}$(timestamp2FileDate "${minDate}").${fileExt}"
    fi
    
    fileInfo=$(file -b "${1}")
    isImg=$(echo "${fileInfo}" | grep "image data," | wc -l)
    if (( ${isImg} > 0 )); then
        if [[ "${1}" != "${target}" ]]; then
            target=$(checkNotExistsPath "$1" "${target}")
            mvFile "${1}" "${target}"
        fi
        reTouchTime "${cDate}" "${mDate}" "${minDate}" "${target}"
    elif [[ "${fileInfo}" =~ ^'ISO Media' ]]; then
        if $(isPressed "${1}"); then
            tmpPath=${filePath}/${pureName}_tmp.${fileExt}
            tmpPath=$(checkNotExistsPath "$1" "${tmpPath}")
            mvFile "${1}" "${tmpPath}"
            target=$(checkNotExistsPath "$1" "${target}")
            pressMp4 "${tmpPath}" "${target}"
            rmFile "${tmpPath}"
        elif [[ "${1}" != "${target}" ]]; then
            target=$(checkNotExistsPath "$1" "${target}")
            mvFile "${1}" "${target}"
        fi
        [[ "${minDate}" != "${cDate}" ]] && touchCreateTime ${minDate} "${target}"
        [[ "${minDate}" != "${mDate}" ]] && touchModifyTime ${minDate} "${target}"
    else
        echo "PASS"
    fi

    echo ""
}

function checkNotExistsPath() {
    renameCount=1
    sourcePath="${1}"
    sourceName=$(basename "${sourcePath}")
    targetFolder=$(dirname "${2}")
    targetName=$(basename "${2}")
    result="${2}"
    while [ -f "${result}" ]; do
        result="${targetFolder}/${targetName%.*}_${renameCount}.${targetName##*.}"
        [[ "${sourcePath}" == "${result}" ]] && break
        ((renameCount++))
    done
    echo "${result}"
}

function loadRelativePath() {
    [[ "${1}" != "${2}" ]] && echo "${t1}" | sed "s~${t2}~~g" 2> /dev/null
}

function isPressed() {
    profile=$(ffprobe -v quiet -show_streams "${1}" | grep "profile=Baseline")
    [[ "${profile}" != "" ]] && return 0 || return 1
}

function pressMp4() {
    execCmd "ffmpeg -i '${1}' -c:v libx264 -preset slow -profile:v high -crf 18 -coder 1 -pix_fmt yuv420p -movflags +faststart -g 30 -bf 2 -c:a aac -b:a 384k -profile:a aac_low '${2}'"
}

function loadCreateTime() {
    [[ "${nowOS}" == "${macOS}" ]] && tmp=`GetFileInfo -d "${1}"`
    [[ "${nowOS}" == "${linuxOS}" ]] && tmp=`stat "${1}" | grep Access | cut -c 9-`
    infoDate2Timestamp "${tmp}"
}

function loadModifyTime() {
    [[ "${nowOS}" == "${macOS}" ]] && tmp=`GetFileInfo -m "${1}"`
    [[ "${nowOS}" == "${linuxOS}" ]] && tmp=`stat "${1}" | grep Modify | cut -c 9-`
    infoDate2Timestamp "${tmp}"
}

function loadFileDate() {
    tmp=`echo "${1}" | grep -Eo "[0-9]{8}_[0-9]{6}"`
    fileDate2Timestamp "${tmp}"
}

function infoDate2Timestamp() {
    date2Timestamp "${1}" "${infoDateFmt}"
}

function fileDate2Timestamp() {
    date2Timestamp "${1}" "${fileDateFmt}"
}

function date2Timestamp() {
    [[ "${nowOS}" == "${macOS}" ]] && date -j -f "${2}" "${1}" +%s 2> /dev/null
    [[ "${nowOS}" == "${linuxOS}" ]] && date -d "${1}" +%s 2> /dev/null
}

function timestamp2InfoDate() {
    timestamp2Date "${1}" "${infoDateFmt}"
}

function timestamp2FileDate() {
    timestamp2Date "${1}" "${fileDateFmt}"
}

function timestamp2TouchDate() {
    timestamp2Date "${1}" "${linuxTouchFmt}"
}

function timestamp2Date() {
    if [[ "${mTZ}" != "" ]]; then
        [[ "${nowOS}" == "${macOS}" ]] && TZ=${mTZ} date -r ${1} +"${2}"
        [[ "${nowOS}" == "${linuxOS}" ]] && TZ=${mTZ} date --date=@${1} +"${2}"
    else
        [[ "${nowOS}" == "${macOS}" ]] && date -r ${1} +"${2}"
        [[ "${nowOS}" == "${linuxOS}" ]] && date --date=@${1} +"${2}"
    fi
}

function getMinTimestamp() {
    (( $# == 1 )) && echo "${1}" && return
    (( $1 >= $2 )) && echo "${2}" || echo "${1}"
}

function reTouchTime() {
    #1 cDate
    #2 mDate
    #3 minDate
    #4 target
    if [[ "${1}" != "${3}" ]] || [[ "${mTZ}" != "" ]]; then
        touchCreateTime ${3} "${4}"
    fi
    if [[ "${2}" != "${3}" ]] || [[ "${mTZ}" != "" ]]; then
        touchModifyTime ${3} "${4}"
    fi
}

function touchCreateTime() {
    if [[ "${nowOS}" == "${macOS}" ]]; then
        time=$(timestamp2InfoDate ${1})
        execCmd "SetFile -d '${time}' '${2}'"
    elif [[ "${nowOS}" == "${linuxOS}" ]]; then
        time=$(timestamp2TouchDate ${1})
        execCmd "touch -a -t ${time} '${2}'"
    fi
    
}

function touchModifyTime() {
    if [[ "${nowOS}" == "${macOS}" ]]; then
        time=$(timestamp2InfoDate ${1})
        execCmd "SetFile -m '${time}' '${2}'"
    elif [[ "${nowOS}" == "${linuxOS}" ]]; then
        time=$(timestamp2TouchDate ${1})
        execCmd "touch -m -t ${time} '${2}'"
    fi
}

while getopts 'ds:t:z:' OPT; do
    case ${OPT} in
        d)
            cfgDryRun=true
            ;;
        s)
            [[ "${OPTARG}" != "" ]] && [[ ! -d ${OPTARG} ]] && ErrExit "Source ${OPTARG} is not exists."
            declare -r sourceDir="$(cd "${OPTARG}" && pwd )"
            ;;
        t)
            targetDir="${OPTARG}"
            ;;
        z)
            declare mTZ="$OPTARG"
            ;;
        \?)
            usage
            ;;
    esac
done

(( $# < 1 )) && usage
init
loadFiles
cd ${nowDir}
