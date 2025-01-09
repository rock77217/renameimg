#!/bin/bash

declare -r rootDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 通用命令執行函數：支援dry-run模式並提供回傳碼檢查
function execCmd() {
    if ${cfgDryRun}; then
        echoFake "${1}"
        return 0
    else
        echoExec "${1}"
        eval "$1"
        local rt=$?
        if [[ ${rt} != 0 ]]; then
            echo "[ERROR] Command failed with exit code ${rt}: ${1}"
            return ${rt}  # 改為 return 而不是 exit
        fi
        return 0
    fi
}

# 刪除檔案的函數
function rmFile() {
    if [[ -f "${1}" ]]; then
        execCmd "rm '${1}'"
    else
        echoInfo "File not found: ${1}"
    fi
}

# 移動檔案並確保目標目錄存在
function mvFile() {
    chkDir "$(dirname "${2}")"
    execCmd "mv '${1}' '${2}'"
}

# 檢查並建立目錄
function chkDir() {
    if [[ ! -d ${1} ]]; then
        execCmd "mkdir -p '${1}'"
    fi
}

# 檢查必要工具是否已安裝
function checkTool() {
    for tool in "$@"; do
        if ! command -v "${tool}" &> /dev/null; then
            ErrExit "${tool} is not installed. Please install it to continue."
        fi
    done
}

# 顯示執行中的指令
function echoExec() {
    echo "[EXEC]    $1"
}

# 顯示模擬指令（dry-run模式）
function echoFake() {
    echo "[Fake]    $1"
}

# 通用資訊顯示
function echoInfo() {
    echo "[INFO]    $1"
}

# 錯誤訊息並退出
function ErrExit() {
    echo "[ERROR]   $1"
    exit 1
}

# 取得檔案創建時間
function loadCreateTime() {
    local filePath="$1"
    
    if [[ "${nowOS}" == "${macOS}" ]]; then
        # macOS 使用 GetFileInfo 來獲取創建時間
        local createTime=$(GetFileInfo -d "${filePath}")
        date2Timestamp "${createTime}" "%m/%d/%Y %H:%M:%S"
    else
        # 優先嘗試獲取創建時間 (Birth)，如果無效則使用修改時間 (Modify)
        local cTime=$(stat -c %W "${filePath}" 2>/dev/null)
        
        # 如果創建時間為 0 或 -1，則使用修改時間
        if [[ "$cTime" == "0" || "$cTime" == "-1" ]]; then
            cTime=$(stat -c %Y "${filePath}")
        fi
        
        echo "$cTime"
    fi
}

# 取得檔案修改時間
function loadModifyTime() {
    local filePath="$1"
    if [[ "${nowOS}" == "${macOS}" ]]; then
        # macOS 使用 GetFileInfo
        local modifyTime=$(GetFileInfo -m "${filePath}")
        date2Timestamp "${modifyTime}" "%m/%d/%Y %H:%M:%S"
    else
        # Linux 使用 stat 取得修改時間
        stat -c %Y "${filePath}"
    fi
}

# 將日期字串轉換為 Unix 時間戳
function date2Timestamp() {
    local dateString="$1"
    local dateFormat="$2"
    if [[ "${nowOS}" == "${macOS}" ]]; then
        date -j -f "${dateFormat}" "${dateString}" +"%s" 2>/dev/null
    else
        date -d "${dateString}" +"%s" 2>/dev/null
    fi
}

# 取得檔案名稱中的日期
function loadFileDate() {
    local dateStr=$(echo "${1}" | grep -Eo "[0-9]{8}_[0-9]{6}")
    if [[ -z "$dateStr" ]]; then
        echo ""
    else
        date2Timestamp "${dateStr}" "${fileDateFmt}"
    fi
}

# 取得較小的時間戳
function getMinTimestamp() {
    local ts1="$1"
    local ts2="$2"

    if [[ -z "$ts1" ]]; then
        echo "$ts2"
        return 0
    fi

    if [[ -z "$ts2" ]]; then
        echo "$ts1"
        return 0
    fi

    if [[ ! "$ts1" =~ ^[0-9]+$ ]] || [[ ! "$ts2" =~ ^[0-9]+$ ]]; then
        echo "[ERROR] Invalid timestamp provided to getMinTimestamp: $ts1, $ts2" >&2
        return 1
    fi

    if (( ts1 >= ts2 )); then
        echo "$ts2"
    else
        echo "$ts1"
    fi
}

# 將時間戳轉換為指定格式的日期（給檔案使用）
function timestamp2FileDate() {
    local timestamp="$1"
    if [[ ! "$timestamp" =~ ^[0-9]+$ ]]; then
        echo "[ERROR] Invalid timestamp for timestamp2FileDate: $timestamp" >&2
        return 1
    fi
    if [[ "${nowOS}" == "Darwin" ]]; then
        # macOS 用法
        date -r "${timestamp}" +"${fileDateFmt}"
    else
        # Linux 用法
        date -d "@${timestamp}" +"${fileDateFmt}"
    fi
}

# 設置檔案的創建時間
function touchCreateTime() {
    local timestamp="$1"
    local filePath="$2"

    if [[ -n "${timestamp}" && "${timestamp}" =~ ^[0-9]+$ ]]; then
        if [[ "${nowOS}" == "Darwin" ]]; then
            # macOS 用法
            local time=$(date -r "${timestamp}" +"${infoDateFmt}")
            execCmd "SetFile -d '${time}' '${filePath}'"
        else
            # Linux 用法
            local time=$(date -d "@${timestamp}" +"${linuxTouchFmt}")
            execCmd "touch -a -t ${time} '${filePath}'"
        fi
    else
        echo "[WARNING] Invalid timestamp in touchCreateTime for file ${filePath}. Skipping." >&2
    fi
}

# 設置檔案的修改時間
function touchModifyTime() {
    local timestamp="$1"
    local filePath="$2"

    if [[ -n "${timestamp}" && "${timestamp}" =~ ^[0-9]+$ ]]; then
        if [[ "${nowOS}" == "Darwin" ]]; then
            # macOS 用法
            local time=$(date -r "${timestamp}" +"${infoDateFmt}")
            execCmd "SetFile -m '${time}' '${filePath}'"
        else
            # Linux 用法
            local time=$(date -d "@${timestamp}" +"${linuxTouchFmt}")
            execCmd "touch -m -t ${time} '${filePath}'"
        fi
    else
        echo "[WARNING] Invalid timestamp in touchModifyTime for file ${filePath}. Skipping." >&2
    fi
}

function reTouchTime() {
    local cDate="$1"
    local mDate="$2"
    local minDate="$3"
    local target="$4"

    # 檢查 minDate 是否為有效的時間戳
    if [[ -n "${minDate}" && "${minDate}" =~ ^[0-9]+$ ]]; then
        # 如果 cDate 無效，使用 minDate
        if [[ -z "${cDate}" || ! "${cDate}" =~ ^[0-9]+$ ]]; then
            cDate="${minDate}"
        fi
        # 如果 mDate 無效，使用 minDate
        if [[ -z "${mDate}" || ! "${mDate}" =~ ^[0-9]+$ ]]; then
            mDate="${minDate}"
        fi

        # 更新文件的創建和修改時間
        touchCreateTime "${cDate}" "${target}"
        touchModifyTime "${mDate}" "${target}"
    else
        echo "[WARNING] Invalid minDate for reTouchTime on file ${target}. Skipping touch operations." >&2
    fi
}