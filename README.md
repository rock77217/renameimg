# renameimg

依拍攝日期重新命名 NAS 上的照片與影片，並把影片壓縮成 HEVC。

## 安裝

```sh
brew install uv exiftool ffmpeg   # Linux 用套件管理員安裝相同工具
```

## 使用

```sh
# 先用 -n 看會做什麼（不會變更任何檔案）
uv run renameimg run /Volumes/photo/2023 -n

# 改名並壓縮影片
uv run renameimg run /Volumes/photo/2023
```

| 子命令 | 說明 |
| --- | --- |
| `run` | 改名、調整時間、壓縮影片 |
| `rename` | 只改名與調整時間，不壓縮 |
| `compress` | 只壓縮影片，保留原檔名 |
| `retouch` | 只把檔案時間設為拍攝日期 |

常用選項：`-n` 試跑、`-t 目錄` 輸出到其他位置（保留子資料夾結構）、`-z Asia/Tokyo` 指定時區（預設 `Asia/Taipei`）、`-j 4` 讀取 metadata 的平行數、`--tmp-dir` 本機轉檔暫存位置、`--report` 報告路徑。

每次執行都會輸出 CSV 報告（預設 `renameimg-report-<時間>.csv`），列出原檔名、新檔名、採用的日期來源、壓縮前後大小、警告。

## Docker

映像已內建 ffmpeg、exiftool、tzdata。在小電腦上：

```sh
mkdir -p reports work        # 先建立，否則 Docker 會以 root 建立，容器內使用者無法寫入
docker compose build         # 下載慢可加 --build-arg DEBIAN_MIRROR=http://ftp.tw.debian.org
docker compose run --rm renameimg run /photos -n
docker compose run --rm renameimg run /photos
```

先修改 `compose.yaml`：

- `volumes` 的 `/mnt/photos` 改成照片的實際路徑（TrueNAS 的 dataset，或 NFS/SMB 掛載點）。
- `user` 改成照片檔案擁有者的 UID:GID（用 `ls -n` 查），新產生的檔案才不會變成 root 所有。
- `./work` 是轉檔暫存，建議放在本機 SSD。

`docker stop` 或 Ctrl+C 都會停止 ffmpeg 並寫出報告；Linux 無法設定檔案建立時間，只會設修改時間。

## 規則

**日期**：從下面四個來源中取最早的一個。

- metadata：EXIF `DateTimeOriginal` 或 QuickTime `CreationDate`/`CreateDate`
- 檔案建立時間
- 修改時間
- 檔名中的日期

早於 2000-01-01 或晚於現在的值會被丟棄。採用的日期比 metadata 早超過一年時，會在報告中標示警告。所有來源都無效時不改名。

**命名**：照片用 `IMG_YYYYMMDD_HHMMSS`，影片用 `VID_YYYYMMDD_HHMMSS`。同一秒的檔案加 `_1`、`_2`，副檔名一律小寫。Live Photo（同名的照片和 MOV）以及 `.aae`、`.xmp` 附屬檔會一起改名；Live Photo 的 MOV 不壓縮。RAW 只改名。不支援的檔案保持原樣，但會列入報告。

**時間與 metadata**：檔案的修改時間和建立時間會設為拍攝日期（Linux 無法設定建立時間）。照片或影片缺少拍攝日期時才補寫進檔案，已經有值的不覆蓋。

**影片壓縮**：`libx265 -preset slow -crf 26`，關鍵幀間隔 300 幀（適合畫面變化少的講課影片）。超過 1080p 的影片降到 1080p，超過 30fps 的降到 30fps，音訊轉成 AAC 96k 單聲道。HDR 以 10-bit 保留，GPS 等 metadata 也會保留。輸出的影片會寫入 `renameimg:v2` 標記。

以下情況不重壓：已經有標記的影片；HEVC 且位元率未超過門檻（1080p 為 4 Mbps，更高解析度為 10 Mbps）。

**安全機制**：先在本機暫存轉檔，再驗證輸出（影片長度相差 1 秒內、有影音串流），然後複製回 NAS，確認大小一致後才取代原檔。驗證失敗時保留原檔並記錄錯誤。中斷後留下的 `.renameimg-tmp-*` 檔會在下次執行時自動清除。

## 開發

```sh
uv run --group dev pytest
```
