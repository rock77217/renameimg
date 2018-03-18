#!/bin/bash

rootDir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cfgDryRun=true
. ./bin/util.sh

done_log=${rootDir}/done.list
dir_photo=/Volumes/home/photo

function replaceVideo() {
    videos=(`find ${dir_photo} -iname "*.mp4"`)

    for film in "${videos[@]}"; do
        fullname=`basename ${film}`
        path=`dirname ${film}`
        ext=${fullname##*.}
        name=${fullname%.*}
        
        
    done
}

function getFullname() {

}