# 数据目录说明

本仓库不包含原始 PDF、向量索引或本地 SQLite 元数据，以防止未经核实地再分发第三方资料，并保持仓库轻量。

## 准备资料

1. 阅读 `manifests/mofcom_guides.json`，从其中列出的官方来源下载 PDF；
2. 将文件放入 `raw/`，文件名须与 manifest 中的 `local_path` 一致；
3. 在项目根目录执行 `python -m scripts.ingest`。

执行后生成的 `index/` 和 `metadata.db` 均是本机运行时数据，不应提交到 Git。

请在使用或再分发资料前，确认来源页面的版权、许可和更新状态。
