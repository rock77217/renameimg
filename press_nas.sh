#!/bin/bash

. ./bin/util.sh

declare -r bashName=$(basename "${0}" | cut -d '.' -f 1)
declare -r tmpDir=/tmp/${bashName}
declare -r logFile=${tmpDir}/$(date +"%Y%m%d_%H%M%S").log
declare -r nowDir=$(pwd)
declare cfgDryRun=false
declare cfgJustRetouch=false
declare cfgSkipRename=false  # 新增：跳過重命名的選項
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

# 資源控制相關變數
declare -r MAX_LOAD_AVERAGE=2.0
declare -r MIN_FREE_MEMORY_MB=1024  # 保留1GB空閒記憶體
declare -r FFMPEG_MEMORY_LIMIT_MB=2048  # FFmpeg最大使用2GB記憶體
declare -r MAX_RETRY=3  # 新增：最大重試次數

# 檢查必要的工具是否安裝
command -v ffmpeg >/dev/null 2>&1 || { echo >&2 "ffmpeg is not installed. Aborting."; exit 1; }
command -v ffprobe >/dev/null 2>&1 || { echo >&2 "ffprobe is not installed. Aborting."; exit 1; }
command -v awk >/dev/null 2>&1 || { echo >&2 "需要 awk 但未安裝。"; exit 1; }
command -v sed >/dev/null 2>&1 || { echo >&2 "需要 sed 但未安裝。"; exit 1; }
command -v free >/dev/null 2>&1 || { echo >&2 "需要 free 但未安裝。"; exit 1; }

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
    echo "Usage: ./${bashName} -s source/path [-t target/path] [-z \"Time/Zone\"] [-d] [-r] [-n] [-f]"
    echo "  -d: Dry run"
    echo "  -r: Just retouch timestamps"
    echo "  -n: Skip rename (use original filename)"
    echo "  -f: Force use file time"
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

    # 根據是否跳過重命名來決定目標文件路徑
    if ${cfgSkipRename}; then
        if [[ "${targetDir}" != "" ]]; then
            if [[ "${relativePath}" != "" ]]; then
                target="${targetDir}${relativePath}/${pureName}.mp4"
            else
                target="${targetDir}/${pureName}.mp4"
            fi
        else
            target="${filePath}/${pureName}.mp4"
        fi
    else
        timestampFileDate=$(timestamp2FileDate "${minDate}")
        if [[ $? -ne 0 ]]; then
            echo "[ERROR] Failed to convert timestamp to file date for $1" >&2
            return 1
        fi

        if [[ "${targetDir}" != "" ]]; then
            if [[ "${relativePath}" != "" ]]; then
                target="${targetDir}${relativePath}/${prefix}${timestampFileDate}.mp4"
            else
                target="${targetDir}/${prefix}${timestampFileDate}.mp4"
            fi
        else
            target="${filePath}/${prefix}${timestampFileDate}.mp4"
        fi
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
        
        # 添加重試邏輯
        local retry_count=0
        local success=false
        
        while [[ ${retry_count} -lt ${MAX_RETRY} && ${success} == false ]]; do
            if process_with_resource_check "${tmpPath}" "${target}"; then
                success=true
            else
                ((retry_count++))
                echo "FFmpeg failed. Attempt ${retry_count} of ${MAX_RETRY}"
                rm -f "${target}"  # 清除失敗的輸出檔
                if [[ ${retry_count} -eq ${MAX_RETRY} ]]; then
                    echo "[ERROR] Failed to process file after ${MAX_RETRY} attempts: ${1}"
                    mvFile "${tmpPath}" "${1}"  # 還原原始檔
                    return 1
                fi
                sleep 1  # 短暫延遲後重試
            fi
        done
        
        if [[ ${success} == true ]]; then
            reTouchTime "${cDate}" "${mDate}" "${minDate}" "${target}"
            rmFile "${tmpPath}"
        fi
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

function check_system_resources() {
    # 檢查系統負載
    local load_average=$(cat /proc/loadavg | awk '{print $1}')
    # 將系統負載和最大負載值轉換為整數進行比較（乘以100去除小數點）
    local load_int=$(echo $load_average | awk '{printf "%.0f", $1 * 100}')
    local max_load_int=$(echo $MAX_LOAD_AVERAGE | awk '{printf "%.0f", $1 * 100}')
    
    if [ $load_int -gt $max_load_int ]; then
        echo "系統負載過高 ($load_average)，等待中..."
        return 1
    fi

    # 檢查可用記憶體
    local free_memory_mb=$(free -m | awk '/^Mem:/ {print $7}')
    if [ $free_memory_mb -lt $MIN_FREE_MEMORY_MB ]; then
        echo "可用記憶體不足 ($free_memory_mb MB)，等待中..."
        return 1
    fi

    return 0
}

function process_with_resource_check() {
    local input_file="$1"
    local output_file="$2"
    
    while ! check_system_resources; do
        sleep 30
    done

    pressMp4 "${input_file}" "${output_file}"
    return $?
}

function pressMp4() {
    execCmd "ffmpeg -i '${1}' \
        -c:v libx264 \
        -preset slow \
        -profile:v high \
        -crf 30 \
        -threads 2 \
        -bufsize 8M \
        -maxrate 8M \
        -coder 1 \
        -pix_fmt yuv420p \
        -movflags +faststart \
        -g 30 \
        -bf 2 \
        -c:a aac \
        -b:a 128k \
        -profile:a aac_low \
        -err_detect ignore_err \
        '${2}'"
    return $?
}

while getopts 'drs:t:z:fn' OPT; do
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
        n)
            cfgSkipRename=true  # 新增跳過重命名的選項
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