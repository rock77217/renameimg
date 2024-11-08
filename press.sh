#!/bin/bash

# 引入外部工具函數（如果有必要）
. ./bin/util.sh

declare -r bashName=$(basename "${0}" | cut -d '.' -f 1)
declare -r tmpDir=/tmp/${bashName}
declare -r logFile=${tmpDir}/$(date +"%Y%m%d_%H%M%S").log
declare -r nowDir=$(pwd)
declare cfgDryRun=false
declare cfgJustRetouch=false
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

# 檢查必要的工具是否安裝
command -v ffmpeg >/dev/null 2>&1 || { echo >&2 "ffmpeg is not installed. Aborting."; exit 1; }
command -v ffprobe >/dev/null 2>&1 || { echo >&2 "ffprobe is not installed. Aborting."; exit 1; }

function init() {
    # 檢查並創建臨時目錄
    mkdir -p "${tmpDir}"

    if [[ "${nowOS}" != "${macOS}" && "${nowOS}" != "${linuxOS}" ]]; then
        echo "Not supported OS: ${nowOS}"
        exit 1
    fi

    # 檢查 sourceDir 是否存在
    if [[ -z "${sourceDir}" ]]; then
        echo "Source directory not specified or does not exist."
        usage
    fi

    cd "${sourceDir}"
}

function usage() {
    echo "Usage: ./${bashName} -s source/path [-t target/path] [-z \"Time/Zone\"] [-d] [-r]"
    exit 1
}

function loadFiles() {
    echo "Scanning ${sourceDir} for video files..."
    oldIFS=$IFS
    IFS=$'\n'
    scanFiles=($(find "${sourceDir}" -type f \( -iname "*.mp4" -o -iname "*.mov" -o -iname "*.avi" -o -iname "*.mkv" -o -iname "*.mts" -o -iname "*.m4v" \) | sort))
    IFS=$oldIFS

    for file in "${scanFiles[@]}"; do
        analysisFile "${file}"
    done
}

function analysisFile() {
    echo "---------------------------------------------------------------------------------"
    echo "Processing file: ${1}"
    fileName=$(basename "$1")
    pureName=${fileName%.*}
    fileExt=${fileName##*.}
    filePath=$(dirname "$1")
    relativePath=$(loadRelativePath "${sourceDir}" "${filePath}")

    cDate=$(loadCreateTime "$1")
    mDate=$(loadModifyTime "$1")
    fileDate=$(loadFileDate "${pureName}")

    # 驗證時間戳
    if [[ ! "$cDate" =~ ^[0-9]+$ ]]; then
        cDate=""
    fi
    if [[ ! "$mDate" =~ ^[0-9]+$ ]]; then
        mDate=""
    fi
    if [[ ! "$fileDate" =~ ^[0-9]+$ ]]; then
        fileDate=""
    fi

    if [[ ${forceFileTime} ]]; then
        minDate=${fileDate}
    else
        minDate=$(getMinTimestamp "${cDate}" "${mDate}")
        if [[ $? -ne 0 ]]; then
            echo "[ERROR] Failed to get minimum timestamp for $1" >&2
            return 1
        fi
        minDate=$(getMinTimestamp "${minDate}" "${fileDate}")
        if [[ $? -ne 0 ]]; then
            echo "[ERROR] Failed to get minimum timestamp for $1" >&2
            return 1
        fi
    fi

    # 如果 minDate 無效，設為當前時間戳
    if [[ -z "$minDate" || ! "$minDate" =~ ^[0-9]+$ ]]; then
        minDate=$(date +%s)
    fi

    timestampFileDate=$(timestamp2FileDate "${minDate}")
    if [[ $? -ne 0 ]]; then
        echo "[ERROR] Failed to convert timestamp to file date for $1" >&2
        return 1
    fi

    # 構建目標文件路徑
    if [[ "${targetDir}" != "" ]]; then
        if [[ "${relativePath}" != "" ]]; then
            target="${targetDir}${relativePath}/${prefix}${timestampFileDate}.mp4"
        else
            target="${targetDir}/${prefix}${timestampFileDate}.mp4"
        fi
    else
        target="${filePath}/${prefix}${timestampFileDate}.mp4"
    fi

    if ${cfgJustRetouch}; then
        reTouchTime "${cDate}" "${mDate}" "${minDate}" "${target}"
        return
    fi

    if isProcessed "${1}"; then
        echo "Already processed: ${1}"
        if [[ "${1}" != "${target}" ]]; then
            target=$(checkNotExistsPath "$1" "${target}")
            [[ "${1}" != "${target}" ]] && mvFile "${1}" "${target}"
            reTouchTime "${cDate}" "${mDate}" "${minDate}" "${target}"
        fi
    else
        tmpPath="${filePath}/${pureName}_tmp.${fileExt}"
        tmpPath=$(checkNotExistsPath "$1" "${tmpPath}")
        mvFile "${1}" "${tmpPath}"
        target=$(checkNotExistsPath "$1" "${target}")
        pressMp4 "${tmpPath}" "${target}"
        reTouchTime "${cDate}" "${mDate}" "${minDate}" "${target}"
        rmFile "${tmpPath}"
    fi
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
    echo "${2}" | sed "s~${1}~~g" 2> /dev/null
}

function isProcessed() {
    vcodec=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,profile -of csv=p=0 "${1}" | head -n1 | cut -d',' -f1)
    vprofile=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,profile -of csv=p=0 "${1}" | head -n1 | cut -d',' -f2)
    acodec=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "${1}")

    if [[ "${vcodec}" == "h264" && "${vprofile}" == "High" && "${acodec}" == "aac" ]]; then
        return 0  # 已經處理過
    else
        return 1  # 需要處理
    fi
}

function pressMp4() {
    # execCmd "ffmpeg -i '${1}' -c:v libx264 -preset slow -profile:v high -crf 18 -coder 1 -pix_fmt yuv420p -movflags +faststart -g 30 -bf 2 -c:a aac -b:a 384k -profile:a aac_low '${2}'"
    execCmd "ffmpeg -i '${1}' -c:v libx264 -preset slow -profile:v high -crf 30 -coder 1 -pix_fmt yuv420p -movflags +faststart -g 30 -bf 2 -c:a aac -b:a 128k -profile:a aac_low '${2}'"
}

# 以下略過其他函數因為大致保持不變

while getopts 'drs:t:z:f' OPT; do
    case ${OPT} in
        d)
            cfgDryRun=true
            ;;
        r)
            cfgJustRetouch=true
            ;;
        s)
            [[ "${OPTARG}" != "" ]] && [[ ! -d ${OPTARG} ]] && echo "Source ${OPTARG} does not exist." && exit 1
            declare -r sourceDir="$(cd "${OPTARG}" && pwd)"
            ;;
        t)
            targetDir="${OPTARG}"
            ;;
        z)
            declare mTZ="${OPTARG}"
            ;;
        f)
            declare -r forceFileTime=true
            ;;
        \?)
            usage
            ;;
    esac
done

# 檢查 sourceDir 是否設置
if [[ -z "${sourceDir}" ]]; then
    usage
fi

init
loadFiles
cd "${nowDir}"