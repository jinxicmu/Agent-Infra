# H3 可配置参数：实现与端到端验证

日期：2026-09-06（工作站本地日期）。状态：已部署并验证。

## 当前客户端契约

- `resolution`：480P、720P、768P，默认 768P。
- `ratio`：1:1、2:3、3:2、3:4、4:3、9:16、16:9、21:9、adaptive，默认 16:9。
- `duration`：1–15 的整数，默认 5。
- 三项均可省略；Cloud Run 填入默认值后持久化。首帧必填，末帧仍可选。
- 分辨率档位控制源工作流的总像素预算，不保证任意比例下的短边等于档位数字。实际宽高按 32 对齐，完整尺寸表见 [客户端指南](API_CLIENT_GUIDE.md)。
- 时长按 24 fps 和 17k+5 帧网格向上对齐，不保证容器时长恰好为请求整数。
- 新成功任务的 `task.output` 返回实际 width、height、fps、frame_count、duration_seconds；旧任务可能为 null。

## 实现

共享的 `workflows/parameters.py` 与 `PRESETS.json` 定义默认值、允许范围及尺寸/帧数算法。Cloud Run 和 worker 使用同一版本策略；策略和计算代码都纳入 workflow manifest 哈希。源 UI 工作流原件保持不变，默认画布仍为 1344×768，默认时长仍对应 124 帧。

Worker 把请求解析成 H3 的 width/height 和 duration；adaptive 读取首帧真实尺寸来确定比例，保留原节点的缩放逻辑，不增加预缩放。生成后 ffprobe 测量输出规格，随已校验的视频写入 GCS 元数据；Cloud Run 再核对该规格与请求的画布、帧数和时长要求，并存入任务结果。

## 真实 HTTP 端到端验证

四条任务通过公开 Cloud Run POST 创建，经过 Firestore 分配、独立 GPU worker、ComfyUI、GCS 上传和公开 GET 查询，再下载输出核验。未直接调用 runner.py 或向 ComfyUI 提交测试图。输入使用此前 clipboard.png 的相同固定 generation，提示词仍为用户提供的中文问诊场景。

| 请求 | 输入 | Worker | 实际画布 | 帧数 | 实际时长 | API 执行阶段耗时 |
|---|---|---|---|---:|---:|---:|
| 480P / 9:16 / 4s | 1 张 | local-5090-1 | 480×832 | 107 | 4.459s | 15.832s |
| 720P / 1:1 / 1s | 2 张 | local-5090-0 | 960×960 | 39 | 1.625s | 15.706s |
| 768P / adaptive / 6s | 1 张 | local-5090-1 | 1344×768 | 158 | 6.584s | 67.532s |
| 480P / 16:9 / 15s | 2 张 | local-5090-0 | 832×480 | 362 | 15.084s | 56.165s |

全部 MP4 均为 H.264 / 24 fps，并包含 AAC 双声道音频。独立下载后的 CRC32C 与云端返回一致；ffprobe 结果与 `task.output` 一致；实际 ComfyUI history 中的画布、时长和末帧连接与请求一致。计时为心跳观测的执行阶段墙钟时间，不是延迟 SLA，也不代表已经对所有允许组合进行性能/质量验证。

输出：

- `portrait4s`：[gen_f408214c1a54431a95f829296c1e97eb](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_f408214c1a54431a95f829296c1e97eb.mp4)；generation `1788757222565693`；CRC32C `rbqEmw==`。
- `square1s`：[gen_9191dcc8f737485aae7a67c1d10f55d6](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_9191dcc8f737485aae7a67c1d10f55d6.mp4)；generation `1788757224251183`；CRC32C `nLOgcw==`。
- `adaptive6s`：[gen_952e988b54cf4243a41e189005de9603](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_952e988b54cf4243a41e189005de9603.mp4)；generation `1788757292634082`；CRC32C `vhflXg==`。
- `long15s`：[gen_53ed496ba8134039a972179d8ead9f49](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_53ed496ba8134039a972179d8ead9f49.mp4)；generation `1788757285339807`；CRC32C `Vi2ylA==`。

## 部署与回滚

- Cloud Run 当前 revision：`ai-studio-h3-00008-mdn`，项目 `novvy-dev`，区域 `us-central1`。
- 镜像：`us-central1-docker.pkg.dev/novvy-dev/cloud-run-source-deploy/ai-studio-h3@sha256:c67eaf43e483da983aee6bc9010b468deeb484002301b8f005559e492e4ff0a8`。
- Workflow revision：`7be6926b7da2552590d82320424a8bd8c76589bd58c51a8412aa18e48052fc29`。
- 63 项自动化测试通过。覆盖默认值归一化、参数边界、严格整数、动态/自适应画布、输出规格验证以及现有任务/租约/恢复协议。
- 发布时暂停新提交、清空旧任务后停止空闲 worker，再协调更新并恢复提交。ComfyUI/模型进程未重启。
- 运行目录：`Agent-Infra/`；开发目录：`Agent-Infra-h3-parameters/`。旧代码备份：`Agent-Infra/runtime/releases/pre-parameters-7be6926b/`。
- 临时测试图片读取授权已撤销，本地签名 URL 文件已删除，测试 Firestore emulator 已停止。
- 测试视频与完整证据位于开发目录的 `runtime/parameter-e2e/`，未纳入 Git。
