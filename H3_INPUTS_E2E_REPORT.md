# H3 I2V / FL2V 部署与端到端测试

> 最新参数能力与部署见 [H3_PARAMETERS_REPORT.md](H3_PARAMETERS_REPORT.md)；本文件保留之前版本的验证记录。

日期：2026-09-06。状态：已部署，两轮、四条真实任务全部成功。

## 当前部署

- Cloud Run：`ai-studio-h3-00005-ssb`，`novvy-dev / us-central1`。
- API：`https://ai-studio-h3-jvljvcyoaa-uc.a.run.app`。
- 镜像：`us-central1-docker.pkg.dev/novvy-dev/cloud-run-source-deploy/ai-studio-h3@sha256:473f7bf7320b1ea4704bc50e15197bc8ae23f57930779a06657a9a5dd0580ab0`。
- Workflow revision：`e3b6726a0b25c6585edaea0de973ac2bf6fdf926fc81e8c6d69869a071994606`。
- 运行代码位于 `Agent-Infra/`；开发副本位于 `Agent-Infra-h3-sage41s/`。
- 首帧必填，末帧可省略；见 [API 示例](API_USAGE_H3.md)。
- 已恢复新任务提交；两个 worker 与两个 ComfyUI 服务运行正常。

## 测试方法

每轮通过真实客户端 API 提交两条 realtime 请求，由 Firestore 分配给两个独立 GPU worker，执行 ComfyUI、上传私有 GCS、回报完成，再通过客户端查询确认成功。未直接向 ComfyUI 提交测试任务。

输入：`gs://self_deployed_model_working_dir/test_image_input_dir/clipboard.png`，generation `1788725004457070`，原图 1376×768；SHA-256 `684953abe43bda9cf7eeae65f425e4701b59d245fd340854a4071d238247a2a5`。双帧组首尾均使用该图。下载采用 generation 固定的短期签名 URL；测试后已移除临时单对象读取授权并删除本地签名 URL 文件。

用户提示词逐字传递：

```text
景别：过肩镜头/患者看医生
运镜：切入，稳定构图
情绪/动作：女医生抬头看向男患者，进入问诊状态。
台词：女医生：你这些症状从什么时候开始的？
音效：环境底噪降低，语音清晰
时长：4s
```

API 参数为 `duration: 5`、`resolution: "768P"`、`ratio: "16:9"`。提示词中的 4s 不修改 API 时长。

## 实测结果

| 轮次 | 输入 | Worker | API 执行阶段耗时 | 端到端耗时 | 视频 |
|---|---|---|---:|---:|---|
| 1 | 仅首帧 | local-5090-1 | 53.639 s | 56.987 s | [打开视频](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_0ca1d57a19724e07839711be6d2eaec9.mp4) |
| 1 | 首尾帧 | local-5090-0 | 52.391 s | 56.696 s | [打开视频](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_ddd8c62cca7c4f518273aa03f14a9a6b.mp4) |
| 2 | 仅首帧 | local-5090-0 | 48.563 s | 50.726 s | [打开视频](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_9bc55a0e91664c7ca934f93aae007b13.mp4) |
| 2 | 首尾帧 | local-5090-1 | 55.488 s | 59.981 s | [打开视频](https://storage.cloud.google.com/self_deployed_model_working_dir/generated_video_dir/gen_58fae5dc3ac749a2ae9039d9d5936b6a.mp4) |

每张 GPU 都完成过单首帧与首尾帧任务。上述耗时来自 API 的心跳阶段时间戳，是执行阶段墙钟耗时，包含模型准备与输出处理，不是纯 GPU kernel 或采样计时。上传很快且没有单独 uploading 心跳时，上传耗时可能记作 0、并入执行阶段，不代表没有发生上传。两轮样本不构成稳定性能基准。

所有视频均已下载并通过 ffprobe 验证：**1344×768，H.264，24 fps，124 帧，5.167 秒，AAC 双声道音频**。GCS generation、对象 CRC32C 与本地文件 CRC32C 一致。这里只验证音频轨存在，没有宣称逐字语音转写一致或主观画质达标。

## 输出定位与完整性

- 第 1 轮 `first_only`：`gen_0ca1d57a19724e07839711be6d2eaec9`；generation `1788736634880999`；CRC32C `KZKBAg==`；772,544 bytes。
- 第 1 轮 `first_and_last`：`gen_ddd8c62cca7c4f518273aa03f14a9a6b`；generation `1788736634939911`；CRC32C `bXPVjA==`；625,160 bytes。
- 第 2 轮 `first_only`：`gen_9bc55a0e91664c7ca934f93aae007b13`；generation `1788736899036690`；CRC32C `8aNhdg==`；675,255 bytes。
- 第 2 轮 `first_and_last`：`gen_58fae5dc3ac749a2ae9039d9d5936b6a`；generation `1788736908635953`；CRC32C `EMOgWA==`；641,150 bytes。

## 验证与发布措施

- 45 项自动化测试通过，数据库测试只使用 Firestore emulator。
- 检查了两轮实际 ComfyUI history 中的执行图：提示词原样、输入图片数量正确、单帧没有末帧连接、四步采样、sigma shift 6/3、固定画布和正确 seed。
- 先使用旧 workflow revision 暂停新增提交，确认队列和活动租约清空，再停止空闲 worker；随后协调发布新 revision，启动 worker，恢复提交。
- ComfyUI/模型进程未重启；第二轮提交前等待了非测试 ComfyUI 任务自然完成，没有中断其他任务。
- 旧代码备份：`Agent-Infra/runtime/releases/pre-h3-inputs-20260906/`。旧云端镜像与 revision 保留以供协调回滚。
- 测试证据和下载的视频位于 `Agent-Infra-h3-sage41s/runtime/h3-inputs-e2e/`，第二轮在 `round2/`；临时输入签名 URL 不写入本报告。
- 监控设计工作仍暂停；本次不部署监控服务。
