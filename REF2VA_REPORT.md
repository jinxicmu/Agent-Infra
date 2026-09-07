# Ref2VA 接入与验证

## 实现

公共入口仍为 `POST /v2/video_generation`，查询仍为 `GET /v2/query/video_generation`。新增 `workflow_type: "ref2va"`；`content` 中传入一个文本项及 1–9 个 `role: "reference_image"` 的图片 URL。省略选择器时按图片角色推断；显式选择器必须与输入一致。不能混用参考图与首尾帧。

图片顺序对应 `<Picture 1>` 到 `<Picture N>`，提示词原样传递。Ref2VA 使用参考图引导身份、场景和风格，输出包含原生立体声音频；此版本没有开放参考视频和参考音频输入。使用示例及完整参数见 [API_CLIENT_GUIDE.md](API_CLIENT_GUIDE.md)。

| 项目 | Ref2VA 设置 |
|---|---|
| 主模型 | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` |
| LoRA | `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`，strength 1 |
| 采样 | Euler / simple / 4 步 / denoise 1 |
| shift | video 12，audio 3 |
| 参考图缩放 | `match`：保持比例、缩小到目标画布像素预算、不裁剪 |
| 默认参数 | `544P / 16:9 / 5s`，默认画布 960×544 |
| 可调参数 | `480P / 544P / 720P / 768P`；原有比例含 adaptive；整数时长 1–15 |
| 输出 | 24 fps，H3 的 17k+5 帧数网格，MP4 + 原生音频 |

两个模型文件增加约 22.93 GB 磁盘用量，均按 Hugging Face 发布的文件大小和 SHA-256 验证。复用已安装的 Qwen 文本编码器及音视频 VAE。安装器：`python -m worker.deploy.download_ref2va /path/to/ComfyUI/models`。

## 来源与取舍

以 [Comfy-Org R2V 模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_r2v.json) 为结构基础：独立 Ref2VA 主模型、`MiniMaxH3ReferenceToVideo` 条件节点、联合音视频 latent、双 VAE 解码和 SaveVideo。离线导出器删除示例图片/提示词及非 Turbo 分支，运行时仅绑定当前任务的输入。

采样参数遵循 [ModelTC Ref2VA Turbo 4-step v0.1 模型规格](https://github.com/ModelTC/Minimax-H3-Turbo#1-model-specs)，并核对其 [Turbo 工作流](https://github.com/ModelTC/Minimax-H3-Turbo/blob/main/example_workflows/video_minimax_h3_ref2v_lightx2v_turbo.json)。需要区分模型推荐值与示例编辑器中的值：此次固定快照的 Comfy 模板默认关闭 Turbo、使用 20 步；ModelTC 示例 JSON 的画布为 1 MP、时长 10 秒，而 README 的 Ref2VA 模型训练档位是 544p。服务明确采用 4 步及 544P 默认档位，保留用户可调画布与时长；没有直接沿用示例中所有编辑器默认值。

两个来源的固定提交、原始 JSON SHA-256，以及模型下载固定版本和 SHA-256，保存在 [REF2VA_PROVENANCE.json](workflows/REF2VA_PROVENANCE.json)。原始快照、导出器、API 图、参数表和注册表均受工作流 revision 约束。

## 架构兼容性

Cloud Run 继续管理 Public API、Worker API 和 Firestore 队列；两个本地 worker 各自轮询、持有一份任务租约并完整执行任务。任一 GPU 均可执行 Ref2VA 或原有 I2V/FL2V，没有新增本地公共端口或独立队列。工作流注册表选择对应图和参数绑定，结果使用对应 SaveVideo 节点。

I2V/FL2V 继续使用原来的 FL2VA 模型、768p Turbo LoRA 和 video/audio shift 6/3。其默认参数及已存在请求的幂等规范化保持兼容。Ref2VA 任务复用租约、恢复、上传和完成验证链路。历史视频仍为私有 GCS 对象，客户端 bearer key 不授予 GCS 读取权限。

## 验证记录

自动化：**71 个测试通过**，含原有测试、Ref2VA 参数默认值/显式覆盖、参考图数量限制、混合角色拒绝、HTTP 与 Firestore 任务分配、幂等、顺序绑定、adaptive，以及任务之间不复用参考条件。Firestore 使用本地 emulator。

本机原生 ComfyUI 校验：1 张和 9 张参考图均通过节点 schema/连线校验；此项不等于 9 张参考图已完成真实生成。真实测试从 Cloud Run HTTP 创建开始，经过 Firestore → worker → ComfyUI → GCS → Cloud Run 查询，并下载指定 generation 校验 CRC32C 和 ffprobe 音视频参数。

部署日期：2026-09-06（工作站时间）。Cloud Run 最终 revision：`ai-studio-h3-00012-lwq`，100% 流量，新任务准入开启。部署镜像：`us-central1-docker.pkg.dev/novvy-dev/cloud-run-source-deploy/ai-studio-h3@sha256:1968d6d8ce78d59bebd2b6fd8b202d4225a7aafb20800bc68dd5fbd7726d9301`。工作流 revision：`ee41720182b348be841a31cb17b7d530fee5823d8cf55c832aad2e3783decd77`。

真实任务 **6/6 成功**，每张 GPU 均完成 Ref2VA → I2V/FL2V → Ref2VA 的切换。各任务均验证了对应主模型/LoRA、采样步数、shift、参考输入数量、输出宽高/帧数、24 fps、立体声 AAC、GCS generation 和 CRC32C。

| 场景 | Worker | 实测输出 | API inference_time | 私有 GCS 视频 |
|---|---|---|---|---|
| ref_single | local-5090-1 | 960×544 / 124 帧 | 48.724s | [视频](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_ca27d5eb40e04df4be2ad594e781ec20.mp4) |
| ref_multiple | local-5090-0 | 864×480 / 107 帧 | 44.416s | [视频](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_a063d317988f4464a6e35254326dfb45.mp4) |
| i2v_after_ref | local-5090-0 | 1344×768 / 124 帧 | 56.938s | [视频](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_195104de49574d1c835ed7b9a94f47bd.mp4) |
| fl2v_after_ref | local-5090-1 | 832×480 / 107 帧 | 29.368s | [视频](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_fe74b27fbc004852b338ad10735f9ae7.mp4) |
| ref_switch_1 | local-5090-0 | 960×544 / 107 帧 | 34.988s | [视频](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_81d1913f80d84001abd70c8a09b49690.mp4) |
| ref_switch_2 | local-5090-1 | 960×544 / 107 帧 | 34.960s | [视频](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_2e169430b6f5437f8241c0e3bc8b6650.mp4) |

`inference_time` 是 API 阶段墙钟时间，包含模型加载及 ComfyUI 执行，并非纯 GPU 采样时间。双参考图测试使用同一测试图片的两个独立输入项，验证双输入链路；不同图片顺序由绑定测试覆盖。这些测试验证执行链路，不代表对全部 1–9 图组合和所有分辨率/时长组合的质量或性能承诺。

资源采样期间最低可用 RAM 约 **4.4 GiB**；未出现 OOM 或 ComfyUI 执行失败。系统存在少量 swap 使用，两套常驻模型下的剩余内存仍有限，因此本次不据此承诺参考图数量增加后的固定延迟。运行时采样、测试请求、下载视频和临时凭证均留在 Git 忽略目录。临时测试输入的 GCS 读取授权已撤销。
